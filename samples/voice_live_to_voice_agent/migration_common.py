"""Identical cascade settings and device handling for both migration steps."""

from __future__ import annotations

import asyncio
import base64
import json
import math
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from migration_audio import Audio, RATE
from voice_agent_sdk_common import _canonical_definition, _validate_project_endpoint

MODEL = "gpt-4.1-mini"
INSTRUCTIONS = (
    "You are a friendly voice assistant. Speak English and keep replies short. "
    "Ask one question at a time. Do not use Markdown or read formatting aloud."
    " Always use add_numbers when asked to add two numbers. "
    "After the function result arrives, briefly state the sum."
)
TOOLS = [{
    "type": "function",
    "name": "add_numbers",
    "description": "Add two numbers using a function executed locally by this client.",
    "parameters": {
        "type": "object",
        "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
        "required": ["a", "b"],
        "additionalProperties": False,
    },
}]
TRANSCRIPTION = {"model": "azure-speech", "language": "en-US"}
VOICE = {"type": "azure-standard", "name": "en-US-Ava:DragonHDLatestNeural"}
MODALITIES = ["text", "audio"]
NOISE_REDUCTION = {"type": "azure_deep_noise_suppression"}
TURN_DETECTION = {
    "type": "server_vad",
    "threshold": 0.5,
    "prefix_padding_ms": 300,
    "silence_duration_ms": 700,
    "create_response": True,
    "interrupt_response": True,
}


class AudioBuffer(Protocol):
    async def append(self, *, audio: str) -> None: ...


class Responses(Protocol):
    async def create(self) -> None: ...


class Connection(Protocol):
    input_audio_buffer: AudioBuffer
    response: Responses

    async def recv(self) -> Mapping[str, Any]: ...
    async def send(self, event: Mapping[str, Any]) -> None: ...


def execute_function(name: str, arguments: str) -> dict[str, float]:
    """Dispatch only the sample's allowlisted local function."""
    if name != "add_numbers":
        raise ValueError(f"Unsupported local function: {name!r}")
    values = json.loads(arguments)
    if not isinstance(values, dict) or set(values) != {"a", "b"}:
        raise ValueError("add_numbers requires exactly a and b.")
    for value in values.values():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError("add_numbers arguments must be finite numbers.")
        try:
            finite = math.isfinite(value)
        except OverflowError as error:
            raise ValueError("add_numbers arguments must be finite numbers.") from error
        if not finite:
            raise ValueError("add_numbers arguments must be finite numbers.")
    total = values["a"] + values["b"]
    try:
        finite = math.isfinite(total)
    except OverflowError as error:
        raise ValueError("add_numbers result must be finite.") from error
    if not finite:
        raise ValueError("add_numbers result must be finite.")
    return {"sum": total}


async def handle_functions(
    event: Mapping[str, Any], connection: Connection, completed_calls: set[str],
) -> None:
    """Both SDKs expose complete function arguments in response.done.output."""
    if event.get("type") != "response.done":
        return
    response = event.get("response") or {}
    if response.get("status") != "completed":
        return
    outputs = []
    for item in response.get("output") or []:
        if item.get("type") != "function_call":
            continue
        call_id = item.get("call_id")
        if not isinstance(call_id, str) or not call_id:
            raise ValueError("Local function call is missing call_id.")
        if call_id in completed_calls:
            continue
        name, arguments = item.get("name"), item.get("arguments")
        if not isinstance(name, str) or not isinstance(arguments, str):
            raise ValueError("Local function call must contain a name and JSON arguments.")
        result = execute_function(name, arguments)
        print(f"Local function: {name}({arguments}) -> {json.dumps(result, allow_nan=False)}")
        outputs.append({
            "type": "function_call_output", "call_id": call_id,
            "output": json.dumps(result, allow_nan=False),
        })
        completed_calls.add(call_id)
    if outputs:
        # Wait for response.done, then submit all results before one continuation.
        for output in outputs:
            await connection.send({"type": "conversation.item.create", "item": output})
        await connection.response.create()


def validate_definition(actual: Any, expected: Any) -> None:
    """Check all requested settings, allowing service-added defaults."""
    def check(stored: Any, requested: Any, path: str) -> None:
        if isinstance(requested, dict):
            if not isinstance(stored, dict):
                raise ValueError(f"Stored setting differs at {path}: {stored!r}")
            for key, value in requested.items():
                check(stored.get(key), value, f"{path}.{key}")
        elif isinstance(requested, list):
            if not isinstance(stored, list) or len(stored) != len(requested):
                raise ValueError(f"Stored setting differs at {path}: {stored!r}")
            for index, (actual_item, expected_item) in enumerate(zip(stored, requested)):
                check(actual_item, expected_item, f"{path}[{index}]")
        elif stored != requested:
            raise ValueError(
                f"Stored setting differs at {path}: expected {requested!r}, got {stored!r}"
            )

    check(_canonical_definition(actual), _canonical_definition(expected), "definition")


def handle_event(event: Mapping[str, Any], audio: Audio | None = None) -> None:
    kind = event.get("type")
    if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
        raise RuntimeError(f"Service error: {event.get('error')}")
    if kind == "warning":
        print(f"Service warning: {dict(event)}", file=sys.stderr)
    elif kind == "response.done":
        response = event.get("response") or {}
        if response.get("status") in {"failed", "incomplete"}:
            raise RuntimeError(f"Response did not complete: {dict(response)}")
    elif kind == "input_audio_buffer.speech_started" and audio:
        with audio.lock:
            audio.output.clear()
    elif kind in {"response.audio.delta", "response.output_audio.delta"} and audio:
        audio.play(base64.b64decode(event["delta"], validate=True))
    elif kind == "conversation.item.input_audio_transcription.completed":
        print(f"You: {event['transcript']}")
    elif kind in {"response.audio_transcript.done", "response.output_audio_transcript.done"}:
        print(f"Assistant: {event['transcript']}")


async def talk(connection: Connection) -> None:
    # Both services acknowledge applied settings before capture starts.
    async with asyncio.timeout(30):
        while True:
            event = await connection.recv()
            handle_event(event)
            if event.get("type") == "session.updated":
                break

    with Audio() as audio:
        audio.start()
        print("Ready. Speak into your microphone; interrupt anytime. Ctrl+C to stop.")
        stop = asyncio.Event()

        async def send() -> None:
            async for pcm in audio.frames(stop):
                await connection.input_audio_buffer.append(
                    audio=base64.b64encode(pcm).decode("ascii")
                )

        async def receive() -> None:
            completed_calls: set[str] = set()
            while True:
                event = await connection.recv()
                handle_event(event, audio)
                await handle_functions(event, connection, completed_calls)

        tasks = [asyncio.create_task(send()), asyncio.create_task(receive())]
        try:
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
            raise RuntimeError("Audio session ended unexpectedly.")
        finally:
            stop.set()
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
