"""Talk to a voice-first GPT Realtime Data Zone, regional, or Azure Realtime agent."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from pathlib import Path

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import VoiceAgentDefinition
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from basic_voice_agent import run_microphone_session, SAMPLE_RATE
from voice_agent_sdk_common import _canonical_definition, _validate_project_endpoint


MODEL = "gpt-realtime-2.1-datazone"
MODELS = (MODEL, "azure-realtime", "gpt-realtime-regional")
INSTRUCTIONS = (
    "You are a friendly voice-first assistant. Speak natural American English. "
    "Keep replies short, ask one question at a time, and let the caller interrupt. "
    "Do not use Markdown or read formatting aloud."
)


def build_definition(model: str = MODEL) -> VoiceAgentDefinition:
    if model not in MODELS:
        raise ValueError(f"Choose a supported sample model: {', '.join(MODELS)}.")
    voice = (
        {"type": "azure-realtime-native", "name": "ava"}
        if model == "azure-realtime"
        else {
            "type": "azure-standard",
            "name": (
                "en-IN-Diya:DragonHDLatestNeural"
                if model == "gpt-realtime-regional"
                else "en-US-Ava:DragonHDLatestNeural"
            ),
        }
    )
    return VoiceAgentDefinition(
        {
            "kind": "voice",
            "model_type": "managed",
            "model": model,
            "instructions": INSTRUCTIONS,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "transcription": {"model": "whisper-1", "language": "en-US"},
                    "noise_reduction": {"type": "azure_deep_noise_suppression"},
                    "turn_detection": {
                        "type": "server_vad",
                        "threshold": 0.5,
                        "prefix_padding_ms": 300,
                        "silence_duration_ms": 700,
                        "create_response": True,
                        "interrupt_response": True,
                    },
                },
                "output": {
                    "format": {"type": "audio/pcm", "rate": SAMPLE_RATE},
                    "voice": voice["name"],
                    "voice_type": voice["type"],
                },
            },
            "output_modalities": ["text", "audio"],
            "store": True,
        }
    )


def validate_definition(definition: VoiceAgentDefinition, model: str = MODEL) -> None:
    if model not in MODELS:
        raise ValueError(f"Choose a supported sample model: {', '.join(MODELS)}.")
    stored = _canonical_definition(definition)
    if (
        stored.get("kind") != "voice"
        or stored.get("model_type") != "managed"
        or stored.get("model") != model
    ):
        raise ValueError(f"Agent must be kind=voice with managed model={model}.")
    audio = stored.get("audio") or {}
    audio_input = audio.get("input") or {}
    audio_output = audio.get("output") or {}
    vad = audio_input.get("turn_detection") or {}
    pcm = {"type": "audio/pcm", "rate": SAMPLE_RATE}
    if (
        audio_input.get("format") != pcm
        or audio_output.get("format") != pcm
        or "audio" not in (stored.get("output_modalities") or [])
        or vad.get("create_response") is not True
        or vad.get("interrupt_response") is not True
    ):
        raise ValueError("Agent must support PCM24k audio, automatic replies, and interruption.")
    if model == "azure-realtime":
        voice = audio_output.get("voice")
        if (
            not isinstance(voice, dict)
            or voice.get("type") != "azure-realtime-native"
            or voice.get("name") != "ava"
        ):
            raise ValueError(
                "This Azure Realtime sample requires voice_type=azure-realtime-native "
                f"and voice=ava; received {voice!r}."
            )


async def run(
    endpoint: str, agent_name: str | None, create_only: bool, model: str = MODEL
) -> None:
    endpoint = _validate_project_endpoint(endpoint)
    definition = build_definition(model)
    if model == "azure-realtime":
        print("Azure Realtime sample target region: Japan East (japaneast).")
        print("Use a Japan East Foundry Project; the endpoint URL alone does not verify its region.")
    elif model == "gpt-realtime-regional":
        print("GPT Realtime Regional sample target region: South India (southindia).")
        print("Use an eligible South India Foundry Project; the endpoint URL alone does not verify its region.")
    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential, allow_preview=True
    ) as client:
        if agent_name:
            agent = await client.agents.get(agent_name=agent_name)
            version = agent.versions.latest
        else:
            agent_name = f"voice-realtime-datazone-{uuid.uuid4().hex[:8]}"
            created = await client.agents.create_version(
                agent_name=agent_name,
                description=f"Voice-first {model} sample.",
                definition=definition,
            )
            version = await client.agents.get_version(
                agent_name=agent_name, agent_version=created.version
            )
            validate_definition(version.definition, model)
            await client.agents.enable(agent_name)
        validate_definition(version.definition, model)
        print(f"Agent: {agent_name} (version {version.version})")
        print(f"Model: {model}")
        print(f"System prompt: {len(version.definition.instructions or '')} characters")
        print("Agent retained. Sessions are stored; do not share sensitive test audio.")
        if create_only:
            return
        conversation_id = await run_microphone_session(client, agent_name)
        if conversation_id:
            print(f"Conversation: {conversation_id}")
            print(
                "Download recording and conversation: "
                f"python samples/download_conversation_artifacts.py {agent_name} {conversation_id}"
            )


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--endpoint", default=os.getenv("AZURE_VOICE_AGENTS_ENDPOINT"),
        help="Eligible Project: US for Data Zone, Japan East for Azure Realtime, South India for GPT Realtime Regional.",
    )
    parser.add_argument("--agent-name", help="Reuse an existing matching voice agent without modifying it.")
    parser.add_argument("--model", choices=MODELS, default=MODEL, help="Explicit managed model; no automatic fallback.")
    parser.add_argument("--create-only", action="store_true", help="Publish/read back without opening the microphone.")
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("Set AZURE_VOICE_AGENTS_ENDPOINT or pass --endpoint.")
    try:
        asyncio.run(run(args.endpoint, args.agent_name, args.create_only, args.model))
    except KeyboardInterrupt:
        print("\nInterrupted.")


if __name__ == "__main__":
    main()
