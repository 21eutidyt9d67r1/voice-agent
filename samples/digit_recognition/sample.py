"""Collect spoken identifiers with the server-managed digit_recognition tool."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path
from typing import Any

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.aio.operations import AsyncBetaRealtimeConnection
from azure.ai.projects.models import VoiceAgentDefinition
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

# Reuse the common SDK and PCM microphone/playback helpers when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from basic_voice_agent import AudioProcessor, audio_bytes, event_value, pyaudio
from voice_agent_sdk_common import (
    _validate_agent_name,
    _validate_project_endpoint,
    validate_definition,
)

SAMPLE_DIR = Path(__file__).resolve().parent
READY_TIMEOUT_SECONDS = 30  # Bound the wait before opening audio devices.
TRANSCRIPTION_MODELS = ("mai-transcribe-2", "azure-speech")


def build_definition(
    *, transcription_model: str = "mai-transcribe-2", language: str = ""
) -> VoiceAgentDefinition:
    """Load the example definition with explicit transcription overrides."""
    if transcription_model not in TRANSCRIPTION_MODELS:
        raise ValueError(f"Choose a transcription model from {TRANSCRIPTION_MODELS}.")
    locales = [locale.strip() for locale in language.split(",") if locale.strip()]
    if transcription_model == "mai-transcribe-2" and len(locales) > 1:
        raise ValueError(
            "MAI Transcribe accepts at most one language. Use a single locale "
            "or leave --language empty for automatic detection."
        )
    document = json.loads((SAMPLE_DIR / "agent.json").read_text(encoding="utf-8"))
    definition = document["definition"]
    transcription = {"model": transcription_model}
    if locales:
        transcription["language"] = ",".join(locales)
    definition["audio"]["input"]["transcription"] = transcription
    return VoiceAgentDefinition(definition)


def validate_agent_definition(
    actual: VoiceAgentDefinition, expected: VoiceAgentDefinition
) -> None:
    """Verify the definition, including an explicitly requested auto-detection mode."""
    validate_definition(actual, expected)
    requested = expected.as_dict()["audio"]["input"]["transcription"]
    stored = actual.as_dict()["audio"]["input"]["transcription"]
    if "language" not in requested and stored.get("language"):
        raise ValueError(
            "Stored transcription language must be omitted for automatic detection."
        )


def _check_error(event: Any) -> None:
    kind = event_value(event, "type")
    if kind == "error":
        error = event_value(event, "error")
        raise RuntimeError(
            f"Voice Agent error: {event_value(error, 'message') or 'unknown error'}"
        )
    if kind == "response.done":
        response = event_value(event, "response")
        if event_value(response, "status") in {"failed", "incomplete"}:
            raise RuntimeError(
                "The agent response did not complete. Check resource/model availability."
            )


async def _wait_ready(connection: AsyncBetaRealtimeConnection) -> None:
    while True:
        event = await connection.recv()
        _check_error(event)
        if event_value(event, "type") == "session.updated":
            return


def _handle_event(event: Any, audio: AudioProcessor, *, show_transcripts: bool) -> None:
    _check_error(event)
    kind = event_value(event, "type")
    if kind == "input_audio_buffer.speech_started":
        audio.skip_pending_audio()
    elif kind == "response.output_audio.delta":
        audio.queue_audio(audio_bytes(event_value(event, "delta")))
    elif kind == "conversation.item.input_audio_transcription.failed":
        print("Input transcription failed. Repeat the complete test identifier.")
    elif kind == "response.system_tool_arguments.done":
        if event_value(event, "name") == "digit_recognition":
            print("digit_recognition requested (executed by the service).")
        # Never send function_call_output or response.create for this system tool.
    elif show_transcripts:
        if kind == "conversation.item.input_audio_transcription.completed":
            print(f"You:   {event_value(event, 'transcript')}")
        elif kind == "response.output_audio_transcript.done":
            print(f"Agent: {event_value(event, 'transcript')}")


async def run_microphone_session(
    client: AIProjectClient, agent_name: str, *, show_transcripts: bool = False
) -> None:
    """Stream mono PCM after the stored agent settings have been acknowledged."""
    if pyaudio is None:
        raise RuntimeError(
            "Install the sample requirements and PortAudio to use the microphone."
        )
    async with client.beta.voice_agents.realtime.connect(
        agent_name=agent_name
    ) as connection:
        # The agent owns all configuration; no session.update is sent here.
        await asyncio.wait_for(_wait_ready(connection), timeout=READY_TIMEOUT_SECONDS)
        audio = AudioProcessor(connection)
        try:
            audio.start_playback()
            audio.start_capture()
            print(
                "Speak a test member ID. Pause for readback, then confirm or correct it."
            )
            print(
                "Use synthetic data only. Talk over a reply to interrupt. Ctrl+C to stop."
            )
            async for event in connection:
                _handle_event(event, audio, show_transcripts=show_transcripts)
        finally:
            audio.shutdown()


async def run(
    endpoint: str,
    *,
    agent_name: str | None = None,
    transcription_model: str = "mai-transcribe-2",
    language: str = "",
    create_only: bool = False,
    show_transcripts: bool = False,
) -> None:
    """Create/read back a sample agent, or reuse a matching one without modifying it."""
    endpoint = _validate_project_endpoint(endpoint)
    if agent_name:
        agent_name = _validate_agent_name(agent_name)
    definition = build_definition(
        transcription_model=transcription_model, language=language
    )
    async with (
        DefaultAzureCredential() as credential,
        AIProjectClient(
            endpoint=endpoint, credential=credential, allow_preview=True
        ) as client,
    ):
        if agent_name:
            agent = await client.agents.get(agent_name=agent_name)
            version = agent.versions.latest
        else:
            agent_name = f"voice-digit-recognition-{uuid.uuid4().hex[:8]}"
            created = await client.agents.create_version(
                agent_name=agent_name,
                description="Spoken identifier readback with server-managed digit recognition.",
                definition=definition,
            )
            version = await client.agents.get_version(
                agent_name=agent_name, agent_version=created.version
            )
            validate_agent_definition(version.definition, definition)
            await client.agents.enable(agent_name)
        validate_agent_definition(version.definition, definition)
        print(f"Agent: {agent_name} (version {version.version})")
        print(
            f"Transcription: {transcription_model}; language: {language or 'automatic detection'}"
        )
        print("Agent retained for reuse. Conversation/audio persistence is disabled.")
        if not create_only:
            await run_microphone_session(
                client, agent_name, show_transcripts=show_transcripts
            )


def main() -> None:
    """Run the folder-local sample without reading another sample's settings."""
    load_dotenv(SAMPLE_DIR / ".env")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("AZURE_VOICE_AGENTS_ENDPOINT"))
    parser.add_argument(
        "--agent-name", help="Reuse an enabled matching agent without modifying it."
    )
    parser.add_argument(
        "--transcription-model",
        choices=TRANSCRIPTION_MODELS,
        default=os.getenv("DIGIT_RECOGNITION_TRANSCRIPTION_MODEL", "mai-transcribe-2"),
    )
    parser.add_argument(
        "--language",
        default=os.getenv("DIGIT_RECOGNITION_LANGUAGE", ""),
        help="One MAI locale, an Azure Speech locale list, or an empty string for auto-detection.",
    )
    parser.add_argument(
        "--create-only",
        action="store_true",
        help="Publish/read back without a microphone.",
    )
    parser.add_argument(
        "--show-transcripts",
        action="store_true",
        help="Print test utterances to this terminal.",
    )
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("Set AZURE_VOICE_AGENTS_ENDPOINT in .env or pass --endpoint.")
    try:
        asyncio.run(
            run(
                args.endpoint,
                agent_name=args.agent_name,
                transcription_model=args.transcription_model,
                language=args.language,
                create_only=args.create_only,
                show_transcripts=args.show_transcripts,
            )
        )
    except KeyboardInterrupt:
        print("\nStopped.")
    except (ValueError, RuntimeError) as error:
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
