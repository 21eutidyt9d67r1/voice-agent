#!/usr/bin/env python3
"""Create or reuse a Foundry GPT Live agent and stream audio with the Azure AI Projects SDK."""

import argparse
import asyncio
import base64
import contextlib
import os
import signal
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.aio.operations import AsyncBetaLiveConnection
from azure.ai.projects.models import (
    LiveInitialSessionAudioOutputParam,
    LiveInitialSessionAudioParam,
    LiveResponsesDelegationParam,
    LiveResponsesDelegationSettingsInputParam,
    LiveSessionAudioFormatPCMParam,
    VoiceAgentLiveDefinition,
)
from azure.core.exceptions import (
    ClientAuthenticationError,
    HttpResponseError,
    ResourceNotFoundError,
)
from azure.identity.aio import AzureCliCredential
from dotenv import load_dotenv

from audio_common import Audio, AudioError, RATE
from transcript_common import TranscriptDisplay

ENGLISH_TEACHER_INSTRUCTIONS = (
    "You are a patient English teacher helping the learner practice spoken English. "
    "Ask one short question at a time and let the learner answer. Gently correct "
    "grammar or vocabulary mistakes with an improved sentence and a brief explanation. "
    "Keep replies concise and encouraging. Use English for practice; if the learner "
    "asks in Chinese, briefly explain in Chinese and then return to English."
)
BACKEND_INSTRUCTIONS = (
    "You are an expert English teacher supporting a spoken English lesson. "
    "Give one accurate, concise grammar explanation and one example or corrected sentence. "
    "Write guidance for the voice teacher, not a long essay."
)


class DemoError(Exception):
    pass


def live_audio():
    """PCM16 at RATE in both directions, spoken with the marin voice."""
    return LiveInitialSessionAudioParam(
        format=LiveSessionAudioFormatPCMParam(rate=RATE),
        output=LiveInitialSessionAudioOutputParam(voice="marin"),
    )


# Agent configuration is intentionally fully visible here, separate from the SDK conversation.
# VoiceAgentLiveDefinition sets kind=voice, sub_protocol=live, and model_type=self_deployed.
def agent_definition():
    backend = required("RESPONSE_DELEGATION_DEPLOYMENT")
    instructions = ENGLISH_TEACHER_INSTRUCTIONS + (
        " Handle greetings and casual conversation yourself. For grammar corrections, "
        "grammar explanations, or lesson planning, always delegate to the Responses "
        "English-teacher backend first, then explain its guidance aloud."
    )
    return VoiceAgentLiveDefinition(
        model=required("GPT_LIVE_DEPLOYMENT"),
        instructions=instructions,
        audio=live_audio(),
        delegation=LiveResponsesDelegationParam(
            responses=LiveResponsesDelegationSettingsInputParam(
                model=backend, instructions=BACKEND_INSTRUCTIONS
            )
        ),
        # Persist in Foundry for the shared conversation downloader.
        store=True,
    )


async def converse(
    connection: AsyncBetaLiveConnection,
    audio: Audio,
    transcript: TranscriptDisplay,
    backend_model: str,
    *,
    managed_delegation: bool = False,
    event_handler=None,
) -> str | None:
    """The whole SDK event/audio loop is here so the sample can be read on its own."""
    events = connection.__aiter__()
    stop = transcript.stop_requested
    loop = asyncio.get_running_loop()
    old_sigint = signal.getsignal(signal.SIGINT)
    signal.signal(signal.SIGINT, lambda *_: loop.call_soon_threadsafe(stop.set))
    session_id = None
    conversation_id = None
    closed = close_sent = False
    audio_started = False
    replied = set()
    latest_delegation = None
    forwarded = set()
    tasks = []
    delegation_title = "Managed delegation" if managed_delegation else "Delegation"

    async def observe(event):
        nonlocal closed, latest_delegation
        # The SDK returns generated models for known Live events and plain dicts for
        # events it does not model yet. Both are mappings, so dispatch on the wire type.
        event_type = event.get("type", "")
        if event_handler is not None:
            await event_handler(connection, event, transcript)
        if event_type == "error":
            raise DemoError(f"Live error: {event.error.message}")
        if event_type == "session.output_audio.delta":
            audio.play(base64.b64decode(event.delta, validate=True))
        elif event_type == "session.input_transcript.delta":
            transcript.append_user(event.delta)
        elif event_type == "session.output_transcript.delta":
            transcript.append_agent(event.delta)
        elif event_type == "session.delegation.created":
            delegation = event.delegation
            latest_delegation = delegation.id
            # The wire string; the typed attribute is an enum whose str() adds its class name.
            target = delegation["target"]
            if managed_delegation:
                # Managed sessions retain the native event name, but Foundry
                # projects its target to indicate that the service owns execution.
                if target != "foundry_managed_agent":
                    raise DemoError(
                        "Expected Foundry-managed delegation, but received "
                        f"delegation target '{target}'. Check that the "
                        "service supports foundry_managed_agent with tagged_text; "
                        "no client fallback was run."
                    )
                transcript.update_agent_activity(
                    delegation.id,
                    title=f"{delegation_title} → {backend_model}",
                    status="Prompt agent delegation requested",
                )
                return
            transcript.update_agent_activity(
                delegation.id,
                title=f"{delegation_title} → {backend_model if target == 'responses' else target}",
                status="Delegation requested",
            )
            if target == "client" and delegation.id not in replied:
                replied.add(delegation.id)
                content = "This demo uses a Responses backend, not a client executor. Please continue the English lesson."
                await connection.session.commentary.append(
                    delegation_id=delegation.id,
                    content=content,
                )
        elif event_type == "response.event":
            # Backend guidance is not the spoken teacher transcript. In managed mode this
            # is the prompt agent's raw tagged-text output; Foundry validates it and
            # forwards only accepted sections to GPT Live.
            backend = event.event
            kind = backend.get("type")
            activity_id = event.delegation_id or "uncorrelated-backend"
            statuses = {
                "response.created": "Backend response started",
                "response.in_progress": "Backend response in progress",
                "response.output_text.delta": "Receiving backend guidance",
                "response.completed": "Backend response completed",
                "response.failed": "Backend response failed",
                "response.incomplete": "Backend response incomplete",
                "error": "Backend error",
            }
            if kind in statuses:
                status = statuses[kind]
                if kind == "response.completed" and activity_id in forwarded:
                    status += "; accepted guidance forwarded to GPT Live"
                transcript.update_agent_activity(
                    activity_id,
                    title=f"{delegation_title if event.delegation_id else 'Uncorrelated backend'} → {backend_model}",
                    status=status,
                    delta=backend.get("delta", "")
                    if kind == "response.output_text.delta"
                    else "",
                )
            if kind in {
                "error",
                "response.failed",
                "response.incomplete",
            }:
                if managed_delegation:
                    # Foundry owns the managed fallback; keep the failure visible
                    # without retrying the backend or interrupting GPT Live.
                    return
                raise DemoError(
                    f"Teaching backend reported {backend['type']}; check its deployment and configuration."
                )
        elif managed_delegation and event_type in {
            "session.commentary.appended",
            "session.thinking.appended",
        }:
            # Foundry appends each accepted guidance section to GPT Live itself. The
            # acknowledgment carries no text or delegation ID, so mark the latest one.
            if latest_delegation is not None:
                forwarded.add(latest_delegation)
                section = event_type.split(".")[1]
                transcript.update_agent_activity(
                    latest_delegation,
                    status=f"Accepted {section} forwarded to GPT Live",
                )
        elif event_type == "session.closed":
            closed = True
            transcript.set_status(
                f"Session closed: {event.reason}; cumulative Live usage: {event.usage.seconds} seconds"
            )
            if event.reason == "connection_lost":
                raise DemoError(
                    "Upstream connection was lost; native finalization is not confirmed."
                )

    async def receive():
        async for event in events:
            await observe(event)
            if closed:
                return
        raise DemoError(
            "WebSocket ended without session.closed; finalization is unconfirmed."
        )

    async def send_microphone():
        # audio.frames() yields raw PCM; the SDK base64-encodes bytes before sending.
        async for pcm in audio.frames(stop):
            await connection.session.input_audio.append(audio=pcm)

    try:
        # Foundry owns session.start. Wait for service-owned readiness; do not start again.
        async with asyncio.timeout(30):
            async for event in events:
                await observe(event)
                if event.get("type") == "session.started":
                    session_id = event.session.id
                    # Foundry adds this top-level field; it is not session.id.
                    value = event.conversation_id
                    if isinstance(value, str) and value.strip():
                        conversation_id = value
                    actual_format = event.session.audio and event.session.audio.format
                    if actual_format and (actual_format.type, actual_format.rate) != (
                        "audio/pcm",
                        RATE,
                    ):
                        raise DemoError(
                            "The negotiated format is not the requested PCM16/24 kHz."
                        )
                    break
                if closed:
                    raise DemoError("Live closed before startup completed.")
            else:
                raise DemoError("WebSocket ended before session.started.")
        if not stop.is_set():
            transcript.set_status(
                f"Ready: {session_id}. Speak into your microphone; Ctrl+C ends the English lesson."
            )
            audio.start()
            audio_started = True
        receiver = asyncio.create_task(receive())
        sender = asyncio.create_task(send_microphone())
        stopped = asyncio.create_task(stop.wait())
        tasks.extend([receiver, sender, stopped])
        done, _ = await asyncio.wait(
            [receiver, sender, stopped], return_when=asyncio.FIRST_COMPLETED
        )
        if receiver in done:
            receiver.result()
        elif sender in done:
            sender.result()
        stop.set()
        audio.stop_microphone()
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        if not receiver.done():
            transcript.set_status("Closing; waiting for session.closed...")
            close_sent = True
            async with asyncio.timeout(5):
                await connection.session.close()
            async with asyncio.timeout(15):
                await receiver
        if audio_started:
            await audio.drain()
        return conversation_id
    except ConnectionResetError as exc:
        # The SDK ends iteration on a graceful close and raises this for an abnormal one.
        raise DemoError(
            "WebSocket ended without session.closed; finalization is unconfirmed."
        ) from exc
    finally:
        stop.set()
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if session_id and not closed and not close_sent:
            with contextlib.suppress(Exception):
                async with asyncio.timeout(3):
                    await connection.session.close()
        signal.signal(signal.SIGINT, old_sigint)


async def check_deployments(project, definition):
    """Check the configured model deployments with read-only requests."""
    deployments = {
        "GPT_LIVE_DEPLOYMENT": definition.model,
    }
    # Created definitions hold typed delegation models, while service readback returns
    # a plain dict. Both are mappings, so key access works for either.
    delegation = definition.delegation or {}
    if delegation.get("type") == "responses":
        deployments["RESPONSE_DELEGATION_DEPLOYMENT"] = delegation["responses"]["model"]
    for setting, name in deployments.items():
        with service_errors(
            f"Check deployment '{name}'",
            not_found=f"Deployment '{name}' was not found in this project. "
            f"Check the existing agent's deployment, or {setting} for a new agent.",
        ):
            deployment = await project.deployments.get(name)
        if deployment.name != name:
            raise DemoError(f"Deployment readback did not match {setting}='{name}'.")
        print(f"Deployment verified: {setting}={name}", flush=True)


async def main(*, auto_delete: bool = False):
    base = project_endpoint()
    existing_agent = os.getenv("AGENT_NAME", "").strip()
    name = existing_agent or f"english-teacher-{uuid4().hex[:12]}"
    definition = None if existing_agent else agent_definition()
    created = False
    credential = project_credential()
    async with (
        credential,
        # allow_preview sends the VoiceAgents=V1Preview feature header for voice agents.
        AIProjectClient(endpoint=base, credential=credential, allow_preview=True) as project,
    ):
        if definition is not None:
            await check_deployments(project, definition)
        try:
            with Audio() as audio:
                if not existing_agent:
                    with service_errors("Create agent"):
                        version = (
                            await project.agents.create_version(name, definition=definition)
                        ).version
                    created = True
                    print(
                        f"Created English teacher agent: {name}, version {version}",
                        flush=True,
                    )
                with service_errors(
                    "Read agent",
                    not_found=f"Agent '{name}' was not found in this project. Check AGENT_NAME."
                    if existing_agent
                    else None,
                ):
                    latest = (await project.agents.get(name)).versions.latest
                definition = latest.definition
                # Readback returns VoiceAgentLiveDefinition only for sub_protocol=live.
                if not isinstance(definition, VoiceAgentLiveDefinition):
                    raise DemoError(
                        "The agent must use sub_protocol=live. "
                        "Check AGENT_NAME or the created agent definition."
                    )
                if existing_agent:
                    version = latest.version
                    print(f"Using existing agent: {name}, version {version}", flush=True)
                    await check_deployments(project, definition)
                delegation = definition.delegation or {}
                managed_delegation = delegation.get("type") in {
                    "foundry_managed_agent",
                    "managed_prompt_agent",
                }
                backend_model = (
                    f"{delegation['agent_name']}:{delegation.get('agent_version') or 'active'}"
                    if managed_delegation
                    else (delegation.get("responses") or {}).get("model")
                    or delegation.get("type", "client")
                )

                # The SDK opens the agent's .../endpoint/protocols/voice/live/sessions
                # WebSocket with the project credential and the preview header.
                # Foundry sends session.start; the client only waits for session.started.
                async with project.beta.voice_agents.live.connect(
                    agent_name=name, agent_version=str(version)
                ) as connection:
                    async with TranscriptDisplay() as transcript:
                        conversation_id = await converse(
                            connection,
                            audio,
                            transcript,
                            backend_model,
                            managed_delegation=managed_delegation,
                        )
            if conversation_id:
                print(f"Conversation id: {conversation_id}", flush=True)
                if created and auto_delete:
                    print(
                        "The agent will be deleted (--auto-delete). "
                        "Omit this option to download the conversation later.",
                        flush=True,
                    )
                else:
                    downloader = (
                        Path(__file__).resolve().parents[2]
                        / "download_conversation_artifacts.py"
                    )
                    command_prefix = "& " if os.name == "nt" else ""
                    print(
                        "Download it later with the shared downloader "
                        "(run from the repository root):\n"
                        f"Set AZURE_VOICE_AGENTS_ENDPOINT to {base}.\n"
                        f'{command_prefix}"{sys.executable}" "{downloader}" '
                        f'"{name}" "{conversation_id}"',
                        flush=True,
                    )
            else:
                print("No persisted conversation id was returned.", flush=True)
        finally:
            if created and auto_delete:
                try:
                    with contextlib.suppress(ResourceNotFoundError):
                        await project.agents.delete(name)
                    print(f"Deleted temporary demo agent: {name}", flush=True)
                except Exception as exc:
                    print(
                        f"Cleanup failed ({type(exc).__name__}); delete agent {name} manually.",
                        flush=True,
                    )
            elif created:
                print(
                    f"Kept agent: {name}. Delete it in your Foundry project when finished.",
                    flush=True,
                )


# Settings, URL construction, and error handling stay in this sample.
def required(name):
    value = os.getenv(name, "").strip()
    if not value:
        raise DemoError(f"Set {name} in .env or the process environment.")
    return value


def project_endpoint():
    value = os.getenv("FOUNDRY_PROJECT_ENDPOINT", "").strip()
    if not value:
        raise DemoError(
            "Set FOUNDRY_PROJECT_ENDPOINT=https://YOUR-RESOURCE.services.ai.azure.com/api/projects/YOUR-PROJECT "
            "in .env. This creates a voice agent in an EXISTING project, not a new Azure project."
        )
    url = urlsplit(value.strip())
    local = url.hostname in {"localhost", "127.0.0.1", "::1"}
    path = url.path.rstrip("/")
    if (
        not url.hostname
        or url.username is not None
        or url.password is not None
        or url.query
        or url.fragment
        or (url.scheme != "https" and not (local and url.scheme == "http"))
        or not path.startswith("/api/projects/")
        or not path.removeprefix("/api/projects/")
        or "/" in path.removeprefix("/api/projects/")
    ):
        raise DemoError(
            "Use an HTTPS project endpoint ending in /api/projects/YOUR-PROJECT without credentials/query/fragment."
        )
    return urlunsplit((url.scheme, url.netloc, path, "", ""))


def project_credential():
    # Select the matching signed-in account without changing az's global default.
    subscription = os.getenv("AZURE_SUBSCRIPTION_ID", "").strip() or None
    return AzureCliCredential(subscription=subscription)


@contextlib.contextmanager
def service_errors(action, *, not_found=None):
    """Turn Projects SDK HTTP errors into short hints.

    Authentication failures keep their own handler in run_cli.
    """
    try:
        yield
    except ClientAuthenticationError:
        raise
    except HttpResponseError as exc:
        if exc.status_code == 404 and not_found:
            raise DemoError(not_found) from None
        hint = {
            403: "Check the signed-in identity's project permissions and preview access.",
            404: "Check the project endpoint and whether this service has the Live implementation.",
            429: "Deployment quota is exhausted; retry later.",
        }.get(exc.status_code, "Check the request and service configuration.")
        raise DemoError(f"{action}: HTTP {exc.status_code}. {hint}") from exc


def run_cli():
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument(
        "--auto-delete",
        action="store_true",
        default=False,
        help="Delete only the agent created by this run on exit (default: keep it).",
    )
    args = parser.parse_args()
    try:
        # samples/gpt_live/.env is shared by the Python and JavaScript samples.
        load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
        asyncio.run(main(auto_delete=args.auto_delete))
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        raise SystemExit(130)
    except ClientAuthenticationError:
        print(
            "\nAzure CLI authentication failed. Run az login with an account that "
            "can access this project, and check AZURE_SUBSCRIPTION_ID in .env.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    except (DemoError, AudioError) as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        raise SystemExit(1)
    except Exception as exc:
        response = getattr(exc, "response", None)
        status = getattr(exc, "status_code", None) or getattr(
            response, "status_code", None
        )
        detail = f" (HTTP {status})" if status else ""
        print(
            f"\n{type(exc).__name__}{detail}. Check your .env settings and endpoint access.",
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    run_cli()
