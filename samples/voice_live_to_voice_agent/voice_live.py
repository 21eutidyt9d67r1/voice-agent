"""Step 1: direct Voice Live, using Azure Speech -> GPT-4.1 mini -> Azure TTS."""

from __future__ import annotations

import argparse
import asyncio
import os
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from azure.ai.voicelive.aio import connect
from azure.ai.voicelive.models import RequestSession
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from migration_common import (
    INSTRUCTIONS, MODALITIES, MODEL, NOISE_REDUCTION, RATE,
    TOOLS, TRANSCRIPTION, TURN_DETECTION, VOICE, talk,
)


def build_session() -> RequestSession:
    return RequestSession(deepcopy({
        "instructions": INSTRUCTIONS,
        "modalities": MODALITIES,
        "input_audio_format": "pcm16",
        "input_audio_sampling_rate": RATE,
        "output_audio_format": "pcm16",
        "input_audio_transcription": TRANSCRIPTION,
        "input_audio_noise_reduction": NOISE_REDUCTION,
        "turn_detection": TURN_DETECTION,
        "voice": VOICE,
        "tools": TOOLS,
        "tool_choice": "auto",
    }))


async def run(endpoint: str) -> None:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https" or not parsed.hostname
        or parsed.path not in {"", "/"} or parsed.query or parsed.fragment
        or parsed.username or parsed.password or parsed.port
        or "<" in endpoint or ">" in endpoint
    ):
        raise ValueError("Use an HTTPS Voice Live resource root, not a Project endpoint.")
    async with DefaultAzureCredential() as credential:
        async with connect(
            endpoint=endpoint, credential=credential, model=MODEL,
            api_version="2026-04-10",
        ) as connection:
            await connection.session.update(session=build_session())
            await talk(connection)


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=os.getenv("AZURE_VOICELIVE_ENDPOINT"))
    args = parser.parse_args()
    if not args.endpoint:
        parser.error("Set AZURE_VOICELIVE_ENDPOINT or pass --endpoint.")
    try:
        asyncio.run(run(args.endpoint))
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
