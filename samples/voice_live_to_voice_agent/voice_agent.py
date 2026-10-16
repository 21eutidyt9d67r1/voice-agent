"""Step 2: the same cascade settings, saved as a Foundry Voice Agent."""

from __future__ import annotations

import argparse
import asyncio
import os
import uuid
from copy import deepcopy
from pathlib import Path

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import VoiceAgentDefinition
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from migration_common import (
    INSTRUCTIONS, MODALITIES, MODEL, NOISE_REDUCTION, RATE,
    TOOLS, TRANSCRIPTION, TURN_DETECTION, VOICE, _validate_project_endpoint,
    talk, validate_definition,
)


def build_definition() -> VoiceAgentDefinition:
    return VoiceAgentDefinition(deepcopy({
        "kind": "voice",
        "model_type": "managed",
        "model": MODEL,
        "instructions": INSTRUCTIONS,
        "output_modalities": MODALITIES,
        "tools": TOOLS,
        "tool_choice": "auto",
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": RATE},
                "transcription": TRANSCRIPTION,
                "noise_reduction": NOISE_REDUCTION,
                "turn_detection": TURN_DETECTION,
            },
            "output": {
                "format": {"type": "audio/pcm", "rate": RATE},
                "voice": VOICE["name"],
                "voice_type": VOICE["type"],
            },
        },
        "store": False,
    }))


async def run(endpoint: str, agent_name: str | None, create_only: bool) -> None:
    endpoint = _validate_project_endpoint(endpoint)
    definition = build_definition()
    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint, credential=credential, allow_preview=True,
    ) as client:
        if agent_name:
            agent = await client.agents.get(agent_name=agent_name)
            version = agent.versions.latest
        else:
            agent_name = f"voice-cascade-migration-{uuid.uuid4().hex[:8]}"
            created = await client.agents.create_version(
                agent_name=agent_name, definition=definition,
                description="Same cascade settings as the direct Voice Live sample.",
            )
            version = await client.agents.get_version(
                agent_name=agent_name, agent_version=created.version,
            )
        validate_definition(version.definition, definition)
        if not create_only:
            await client.agents.enable(agent_name)
        print(f"Agent: {agent_name} (version {version.version}); model: {MODEL}")
        print("Agent retained for reuse. Conversation/audio persistence is disabled.")
        if create_only:
            return
        # No session.update: the agent supplies the saved settings.
        async with client.beta.voice_agents.realtime.connect(agent_name=agent_name) as connection:
            await talk(connection)


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("AZURE_VOICE_AGENTS_ENDPOINT"))
    parser.add_argument("--agent-name", help="Reuse a matching agent without changing its settings.")
    parser.add_argument("--create-only", action="store_true", help="Publish/read back without microphone access.")
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("Set AZURE_VOICE_AGENTS_ENDPOINT or pass --endpoint.")
    try:
        asyncio.run(run(args.endpoint, args.agent_name, args.create_only))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
