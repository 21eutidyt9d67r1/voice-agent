#!/usr/bin/env python3
"""Receive transfer and end-conversation events on a customer-owned GPT Live WebSocket."""

from __future__ import annotations

import argparse
import asyncio
import base64
import contextlib
import json
import os
from pathlib import Path
import re
import signal
import sys
from urllib.parse import quote, urlsplit, urlunsplit

from control_events import CallControlEvents, TOOL_NAME, agent_definition, offline_demo

SCOPE = "https://ai.azure.com/.default"
FEATURE_HEADERS = {"Foundry-Features": "VoiceAgents=V1Preview"}


def project_endpoint(value):
    value = (value or "").strip().rstrip("/")
    url = urlsplit(value)
    if (url.scheme != "https" or url.username or url.password or url.port not in (None, 443)
            or not re.fullmatch(r"[a-z0-9][a-z0-9-]*\.services\.ai\.azure\.com", url.hostname or "")
            or not re.fullmatch(r"/api/projects/[^/]+", url.path) or url.query or url.fragment):
        raise ValueError("Set PROJECT_ENDPOINT=https://<resource>.services.ai.azure.com/api/projects/<project>.")
    return value


def session_url(endpoint, name):
    url = urlsplit(project_endpoint(endpoint))
    return urlunsplit(("wss", url.netloc, url.path + "/agents/" + quote(name, safe="")
                       + "/endpoint/protocols/voice/live/sessions", "", ""))


async def headers(credential):
    token = await credential.get_token(SCOPE)
    return {"Authorization": "Bearer " + token.token, **FEATURE_HEADERS}


async def rest(client, credential, endpoint, method, path, **kwargs):
    async with client.request(method, endpoint + path, params={"api-version": "v1"},
                              headers=await headers(credential), allow_redirects=False, **kwargs) as response:
        if not 200 <= response.status < 300:
            request_id = response.headers.get("x-ms-request-id", "not supplied")
            raise RuntimeError(f"{method} {path}: HTTP {response.status}; request-id={request_id}")
        return await response.json()


def verify_agent(agent):
    latest = (agent.get("versions") or {}).get("latest") or {}
    definition = latest.get("definition") or {}
    backend = (definition.get("delegation") or {}).get("responses") or {}
    tools = backend.get("tools") or []
    if (definition.get("kind") != "voice" or definition.get("sub_protocol") != "live"
            or (definition.get("delegation") or {}).get("type") != "responses"
            or sum(tool.get("type") == "function" and tool.get("name") == TOOL_NAME for tool in tools) != 1
            or not any(tool.get("name") == "end_conversation" for tool in definition.get("system_tools") or [])
            or not isinstance(latest.get("version"), (str, int))):
        raise ValueError("Use the native Live Agent created by this sample, with transfer_call and system ending configured.")
    return str(latest["version"])


def report(kind, **values):
    print(json.dumps({"event": kind, **values}, ensure_ascii=False), flush=True)


async def converse(ws, audio, *, guidance=None, stop=None, callback=None):
    """One socket reader; a bounded worker executes only transfer_call callbacks."""
    stop = stop or asyncio.Event()
    send_lock = asyncio.Lock()
    ready = asyncio.get_running_loop().create_future()
    closed = False
    guidance_pending = False
    agent_ending = False
    close_sent = False

    async def send(message):
        async with asyncio.timeout(5):
            async with send_lock:
                await ws.send_json(message)

    events = CallControlEvents(send, **({"callback": callback} if callback else {}))
    events.start()

    async def receive():
        nonlocal closed, guidance_pending, agent_ending
        async for message in ws:
            # aiohttp.WSMsgType.TEXT has value 1; keep protocol tests independent of aiohttp imports.
            if message.type != 1:
                if message.type == 2:
                    raise ValueError("Expected JSON text frames, not binary audio.")
                continue
            event = json.loads(message.data)
            kind = event.get("type")
            if kind == "session.started":
                if ready.done() or guidance_pending:
                    raise ValueError("Repeated session.started.")
                session = event.get("session") or {}
                if (session.get("audio") or {}).get("format") != {"type": "audio/pcm", "rate": 24000}:
                    raise ValueError("The session must negotiate mono PCM16 at 24 kHz.")
                report(kind, session_id=session.get("id"), conversation_id=event.get("conversation_id"))
                if guidance:
                    guidance_pending = True
                    await send({"type": "session.instructions.append", "delegation_id": None, "content": guidance})
                else:
                    ready.set_result(None)
            elif kind == "session.instructions.appended" and guidance_pending:
                guidance_pending = False
                ready.set_result(None)
            elif kind == "session.output_audio.delta":
                audio.play(base64.b64decode(event.get("delta", ""), validate=True))
            elif kind in {"session.input_transcript.delta", "session.output_transcript.delta"}:
                report(kind, delta=event.get("delta", ""))
            elif kind == "response.event":
                events.observe(event)
                nested = event.get("event") or {}
                if nested.get("type") in {"response.created", "response.completed", "response.failed", "response.cancelled", "response.incomplete"}:
                    report(kind, delegation_id=event.get("delegation_id"), backend_event=nested.get("type"))
            elif kind == "session.closed":
                closed = True
                await events.close()
                report(kind, reason=event.get("reason"))
                if event.get("reason") == "connection_lost":
                    raise RuntimeError("Live connection was lost; finalization is unconfirmed.")
                return
            elif kind == "error":
                # Do not log raw service messages that can contain private conversation data.
                raise RuntimeError("Agent reported an error; code=" + str((event.get("error") or {}).get("code", "unknown")))
            elif kind == "session.end_conversation.completed":
                agent_ending = True
                await events.close()
                stop.set()
                report(kind, id=event.get("id"))
            elif kind in {"session.end_conversation.cancelled", "session.delegation.created"}:
                report(kind, id=event.get("id") or (event.get("delegation") or {}).get("id"))
        raise RuntimeError("WebSocket ended without session.closed; finalization is unconfirmed.")

    async def microphone():
        async for pcm in audio.frames(stop):
            await send({"type": "session.input_audio.append", "audio": base64.b64encode(pcm).decode("ascii")})

    receiver = asyncio.create_task(receive())
    startup = asyncio.create_task(asyncio.wait_for(asyncio.shield(ready), 30))
    sender = stopped = None
    try:
        done, _ = await asyncio.wait([startup, receiver, events.failure], return_when=asyncio.FIRST_COMPLETED)
        if receiver in done:
            receiver.result()
            raise RuntimeError("Session closed before it was ready.")
        if events.failure in done:
            raise events.failure.result()
        await startup
        audio.start()
        report("client.ready", message="Speak; ask for a human or voice specialist. Ctrl+C closes the session.")
        sender = asyncio.create_task(microphone())
        stopped = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait([receiver, sender, stopped, events.failure], return_when=asyncio.FIRST_COMPLETED)
        if events.failure in done:
            raise events.failure.result()
        if receiver in done:
            receiver.result()
        if sender in done:
            sender.result()
        stop.set()
        audio.stop_microphone()
        sender.cancel()
        await asyncio.gather(sender, return_exceptions=True)
        if not receiver.done():
            if not agent_ending:
                close_sent = True
                await send({"type": "session.close"})
            async with asyncio.timeout(15):
                await receiver
        if closed:
            await audio.drain()
    finally:
        stop.set()
        audio.stop_microphone()
        await events.close()
        tasks = [task for task in (receiver, startup, sender, stopped) if task is not None]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not closed and not close_sent and not agent_ending:
            with contextlib.suppress(Exception):
                await send({"type": "session.close"})


async def run(args):
    import aiohttp
    from azure.identity.aio import AzureCliCredential

    endpoint = project_endpoint(args.project_endpoint)
    subscription = os.getenv("AZURE_SUBSCRIPTION_ID") or None
    async with AzureCliCredential(subscription=subscription) as credential, aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=60), trust_env=False
    ) as client:
        path = "/agents/" + quote(args.agent_name, safe="")
        if args.command == "create":
            definition = agent_definition(args.live_model, args.responses_model)
            await rest(client, credential, endpoint, "POST", "/agents", json={"name": args.agent_name, "definition": definition})
            report("client.agent_created", agent_name=args.agent_name)
            return
        agent = await rest(client, credential, endpoint, "GET", path)
        version = verify_agent(agent)
        # Reuse the repository's tested device/cadence helper; it owns no protocol reader.
        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "gpt_live" / "python"))
        from audio_common import Audio

        stop = asyncio.Event()
        previous = signal.signal(signal.SIGINT, lambda *_: stop.set())
        try:
            with Audio() as audio:
                async with client.ws_connect(session_url(endpoint, args.agent_name),
                    params={"api-version": "v1", "x-agent-version-override": version},
                    headers=await headers(credential), heartbeat=20, max_msg_size=1024 * 1024) as ws:
                    # Foundry starts the saved Agent. Do not send session.start or session.update.
                    await converse(ws, audio, guidance=args.session_guidance, stop=stop)
        finally:
            signal.signal(signal.SIGINT, previous)


def main():
    try:
        from dotenv import load_dotenv
    except ModuleNotFoundError:
        pass
    else:
        load_dotenv(Path(__file__).with_name(".env"), interpolate=False)
    parser = argparse.ArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("--project-endpoint", default=os.getenv("PROJECT_ENDPOINT"))
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="Create a new sample Agent; existing Agents are never updated")
    create.add_argument("--agent-name", required=True)
    create.add_argument("--live-model", default=os.getenv("GPT_LIVE_DEPLOYMENT"))
    create.add_argument("--responses-model", default=os.getenv("RESPONSES_MODEL_DEPLOYMENT"))
    create.add_argument("--dry-run", action="store_true")
    connect = commands.add_parser("connect", help="Talk to the saved sample Agent through WebSocket")
    connect.add_argument("--agent-name", required=True)
    connect.add_argument("--session-guidance", help="Optional trusted developer guidance appended after session.started")
    commands.add_parser("demo", help="Replay transfer and ending events offline; no Azure, microphone or network")
    args = parser.parse_args()
    if args.command == "demo":
        asyncio.run(offline_demo())
    elif args.command == "create" and args.dry_run:
        print(json.dumps({"name": args.agent_name, "definition": agent_definition(args.live_model, args.responses_model)}, indent=2))
    else:
        if args.command == "connect" and args.session_guidance and len(args.session_guidance.encode("utf-8")) > 350:
            raise ValueError("Keep session guidance within 350 UTF-8 bytes for this sample.")
        asyncio.run(run(args))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as error:
        # Keep tokens, raw HTTP response bodies, callback failures and credentials out of errors.
        if isinstance(error, (ValueError, RuntimeError)):
            print(f"Error: {error}", file=sys.stderr)
        else:
            print(f"Error: {type(error).__name__}; check configuration, authentication and service availability.", file=sys.stderr)
        raise SystemExit(1)
