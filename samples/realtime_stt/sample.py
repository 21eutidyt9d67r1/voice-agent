"""Create a Foundry realtime STT agent with VAD and preserve reported session usage."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import uuid
from collections import Counter
from collections.abc import Awaitable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import VoiceAgentDefinition
from azure.core.exceptions import AzureError
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv

from samples.gpt_live.python.audio_common import FRAME_BYTES, FRAMES, RATE, Audio, AudioError

logger = logging.getLogger(__name__)
transcript_logger = logging.getLogger(f"{__name__}.transcripts")
transcript_logger.propagate = False  # Requested console text must not enter diagnostic log handlers.

DEFAULT_MODEL = "gpt-5.6-luna"  # A managed text session model; this sample never requests an LLM response.
DEFAULT_STT_MODEL = "mai-transcribe-2"  # Explicit MAI version; azure-speech selects Azure Speech STT.
DEFAULT_VAD = "server_vad"  # Automatically commits utterances while response creation remains disabled.
CAPTURE_SECONDS = 10.0  # Default duration for a microphone run.
TAIL_SECONDS = 2.0  # Silence lets VAD commit the final utterance before session.close.
EVENT_TIMEOUT_SECONDS = 60  # Bounds readiness, transcription settlement, and final usage waits.
SESSION_TIMEOUT_SECONDS = 180  # Bounds the entire session, including paced WAV input.
SILENCE_DURATION_MS = 500  # VAD's silence boundary; shorter than the supplied trailing silence.
TRANSCRIPTION_MODELS = ("mai-transcribe-2", "azure-speech")  # Public identifiers supported by this sample.
VAD_TYPES = ("server_vad", "azure_semantic_vad_multilingual")  # Supported local turn detectors.


@dataclass(frozen=True)
class Options:
    """Connection, agent, and audio choices for one STT session."""

    endpoint: str
    agent_name: str | None = None
    model: str = DEFAULT_MODEL
    stt_model: str = DEFAULT_STT_MODEL
    vad_type: str = DEFAULT_VAD
    wav: Path | None = None
    duration: float = CAPTURE_SECONDS
    require_usage: bool = False


@dataclass(frozen=True)
class Transcript:
    """One completed utterance, correlated with its audio commit."""

    item_id: str
    text: str


@dataclass(frozen=True)
class STTResult:
    """Transcripts and the original cumulative usage from session.closed."""

    agent_name: str
    agent_version: str
    session_id: str
    event_id: str | None
    reason: str | None
    transcripts: list[Transcript]
    usage: dict[str, Any] | None
    usage_status: str
    event_counts: dict[str, int]


@dataclass
class _SessionState:
    ready: asyncio.Future[dict[str, Any]]
    closed: asyncio.Future[dict[str, Any] | None]
    session_id: str = ""
    close_requested: bool = False
    settled: asyncio.Event = field(default_factory=asyncio.Event)
    committed: set[str] = field(default_factory=set)
    speaking: set[str] = field(default_factory=set)
    transcripts: dict[str, Transcript] = field(default_factory=dict)
    events: Counter[str] = field(default_factory=Counter)


def _definition(options: Options) -> VoiceAgentDefinition:
    """Persist STT-only behavior in the agent rather than a client session update."""
    return VoiceAgentDefinition(
        {
            "kind": "voice",
            "model_type": "managed",
            "model": options.model,
            "audio": {
                "input": {
                    "format": {"type": "audio/pcm", "rate": RATE},
                    "transcription": {"model": options.stt_model},
                    "turn_detection": {
                        "type": options.vad_type,
                        "silence_duration_ms": SILENCE_DURATION_MS,
                        "create_response": False,
                        "interrupt_response": False,
                    },
                },
            },
            "output_modalities": ["text"],
            "store": True,
        }
    )


def _validate_definition(definition: dict[str, Any], options: Options) -> None:
    """Refuse unsafe existing definitions without modifying them."""
    audio_input = definition.get("audio", {}).get("input", {})
    _validate_input(audio_input, options)
    if definition.get("kind") != "voice" or definition.get("greeting"):
        raise ValueError("Use a voice agent without a greeting for STT-only operation.")
    logger.info("Stored agent definition has VAD enabled and automatic responses disabled")


def _validate_input(audio_input: dict[str, Any], options: Options) -> None:
    """Verify that the service preserved the requested transcription and VAD."""
    vad = audio_input.get("turn_detection") or {}
    transcription = audio_input.get("transcription") or {}
    if vad.get("create_response") is not False:
        raise ValueError("The agent must set turn_detection.create_response=false.")
    if vad.get("type") != options.vad_type or transcription.get("model") != options.stt_model:
        raise ValueError("Agent transcription/VAD settings do not match the selected options.")
    if audio_input.get("format") != {"type": "audio/pcm", "rate": RATE}:
        raise ValueError(f"Agent input must use mono PCM16 at {RATE} Hz.")


async def _agent(client: Any, options: Options) -> tuple[str, str]:
    """Create a new agent or read an existing agent without changing it."""
    if options.agent_name:
        logger.info("Reading existing agent %s", options.agent_name)
        agent = await client.agents.get(agent_name=options.agent_name)
        version = agent.versions.latest
    else:
        name = f"realtime-stt-{uuid.uuid4().hex[:12]}"
        logger.info("Creating realtime STT agent %s", name)
        created = await client.agents.create_version(
            agent_name=name,
            definition=_definition(options),
            description="Realtime speech transcription with VAD; no automatic LLM responses.",
        )
        await client.agents.enable(name)
        version = await client.agents.get_version(agent_name=name, agent_version=created.version)
        logger.info("Created agent %s version %s", name, version.version)
    _validate_definition(version.definition.as_dict(), options)
    return version.name, version.version


def _observe(event: dict[str, Any], state: _SessionState) -> None:
    """Track every committed item until its transcription finishes."""
    kind = event["type"]
    state.events[kind] += 1
    logger.debug("Received event %s", kind)
    if kind == "error" or kind == "conversation.item.input_audio_transcription.failed":
        code = (event.get("error") or {}).get("code", "unknown")
        logger.error("Voice Agent reported error code %s", code)
        raise RuntimeError(f"Voice Agent error: {code}")
    if kind.startswith("response."):
        logger.error("Unexpected response event %s in STT-only session", kind)
        raise RuntimeError("Unexpected LLM response; STT-only configuration was not preserved.")
    if kind == "session.updated" and not state.ready.done():
        state.session_id = event["session"]["id"]
        state.ready.set_result(event["session"])
    elif kind == "session.closed" and not state.closed.done():
        state.closed.set_result(event)
    elif kind == "input_audio_buffer.speech_started":
        state.speaking.add(event["item_id"])
    elif kind == "input_audio_buffer.speech_stopped":
        state.speaking.discard(event["item_id"])
    elif kind == "input_audio_buffer.committed":
        state.committed.add(event["item_id"])
    elif kind == "conversation.item.input_audio_transcription.completed":
        item_id = event["item_id"]
        state.transcripts[item_id] = Transcript(item_id, event["transcript"])
        transcript_logger.info("%s", event["transcript"])
        logger.info("Transcription completed for item %s (%s characters)", item_id, len(event["transcript"]))
    _update_settled(state)


def _update_settled(state: _SessionState) -> None:
    """Require all admitted utterances, rather than only the first transcript."""
    if state.committed and not state.speaking and state.committed <= state.transcripts.keys():
        state.settled.set()
    else:
        state.settled.clear()


async def _receive_events(connection: Any, state: _SessionState) -> None:
    """Own the only WebSocket reader for the entire session."""
    while True:
        try:
            event = await connection.recv()
        except ConnectionResetError as error:
            if not state.close_requested or error.__cause__ is not None:
                raise ConnectionError("Transport failed before final usage; usage is unconfirmed.") from error
            logger.error("Voice endpoint closed without session.closed; final usage is unconfirmed")
            state.closed.set_result(None)
            return
        if event is None:
            raise ConnectionError("Connection ended before final usage; usage is unconfirmed.")
        payload = event.as_dict() if hasattr(event, "as_dict") else dict(event)
        _observe(payload, state)
        if payload["type"] == "session.closed":
            return


async def _wait[ResultType](
    completion: Awaitable[ResultType],
    receiver: asyncio.Task[None],
) -> ResultType:
    """Propagate receiver errors while waiting for an event or transcription."""
    task = asyncio.ensure_future(completion)
    try:
        async with asyncio.timeout(EVENT_TIMEOUT_SECONDS):
            done, _ = await asyncio.wait((task, receiver), return_when=asyncio.FIRST_COMPLETED)
            if receiver in done:
                await receiver
            if task in done:
                return await task
            raise ConnectionError("Connection ended without the expected event.")
    finally:
        if not task.done():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


async def _silence(connection: Any) -> None:
    """End microphone input with paced silence instead of an extra empty commit."""
    for _ in range(int(TAIL_SECONDS * RATE / FRAMES)):
        await connection.input_audio_buffer.append(audio=bytes(FRAME_BYTES))
        await asyncio.sleep(FRAMES / RATE)


async def _stream_audio(connection: Any, audio: Audio, options: Options) -> None:
    """Reuse the shared audio source for paced WAV or microphone input."""
    stop = asyncio.Event()
    deadline = asyncio.get_running_loop().time() + options.duration
    logger.info("Streaming %s input", "WAV" if options.wav else "microphone")
    audio.start()
    async for pcm in audio.frames(stop):
        await connection.input_audio_buffer.append(audio=pcm)
        if not options.wav and asyncio.get_running_loop().time() >= deadline:
            audio.stop_microphone()
            break
    if not options.wav:
        await _silence(connection)
    logger.info("Audio input finished; waiting for every committed transcription")


def _result(
    event: dict[str, Any] | None,
    state: _SessionState,
    identity: tuple[str, str],
) -> STTResult:
    """Preserve final usage or explicitly return an unconfirmed gap."""
    usage = event["usage"] if event is not None else None
    status = usage.get("status", "unknown") if usage is not None else "unconfirmed"
    if status != "complete":
        logger.error("Final usage is %s; a complete token total is unavailable", status)
    elif usage is not None:
        logger.info("Final usage status=%s audio_tokens=%s", status, usage["input_token_details"]["audio_tokens"])
    return STTResult(
        agent_name=identity[0],
        agent_version=identity[1],
        session_id=state.session_id,
        event_id=event["event_id"] if event is not None else None,
        reason=event["reason"] if event is not None else None,
        transcripts=list(state.transcripts.values()),
        usage=usage,
        usage_status=status,
        event_counts=dict(state.events),
    )


async def _session(connection: Any, audio: Audio, options: Options, identity: tuple[str, str]) -> STTResult:
    """Stream input and explicitly close only after all transcriptions settle."""
    loop = asyncio.get_running_loop()
    state = _SessionState(loop.create_future(), loop.create_future())
    receiver = asyncio.create_task(_receive_events(connection, state))
    try:
        session = await _wait(state.ready, receiver)
        audio_input = session.get("audio", {}).get("input")
        if audio_input is None:
            audio_input = {
                "format": {"type": "audio/pcm", "rate": session.get("input_audio_sampling_rate")},
                "transcription": session.get("input_audio_transcription"),
                "turn_detection": session.get("turn_detection"),
            }
        _validate_input(audio_input, options)
        await _wait(_stream_audio(connection, audio, options), receiver)
        await _wait(state.settled.wait(), receiver)
        logger.info("Requesting final cumulative session usage")
        state.close_requested = True
        await connection.send({"type": "session.close"})
        event = await _wait(state.closed, receiver)
        result = _result(event, state, identity)
        if options.require_usage and result.usage_status != "complete":
            raise RuntimeError("The voice endpoint did not provide complete final usage.")
        return result
    finally:
        if not receiver.done():
            receiver.cancel()
        await asyncio.gather(receiver, return_exceptions=True)


async def _connect(client: Any, audio: Audio, options: Options, identity: tuple[str, str]) -> STTResult:
    """Keep the session deadline outside the SDK connection lifetime."""
    async with asyncio.timeout(SESSION_TIMEOUT_SECONDS):
        async with client.beta.voice_agents.realtime.connect(agent_name=identity[0]) as connection:
            return await _session(connection, audio, options, identity)


async def run(options: Options) -> STTResult:
    """Create or reuse an STT agent and return transcripts and final usage.

    Parameters
    ----------
    options
        Foundry project, transcription model, VAD, and audio-source settings.

    Returns
    -------
    STTResult
        Completed transcripts and original usage, or usage=None and status=unconfirmed when
        the endpoint closes normally without a final usage event.

    Raises
    ------
    ValueError
        The configuration or audio format is unsuitable for STT-only operation.
    RuntimeError
        The service reports an error or produces an unexpected response.
    ConnectionError
        The transport ends before final usage.
    TimeoutError
        Input, transcription settlement, or close does not complete in time.
    """
    if options.duration <= 0:
        raise ValueError("Microphone duration must be positive.")
    with Audio(input_wav=options.wav, no_playback=True, tail_seconds=TAIL_SECONDS) as audio:
        async with (
            DefaultAzureCredential() as credential,
            AIProjectClient(endpoint=options.endpoint, credential=credential, allow_preview=True) as client,
        ):
            identity = await _agent(client, options)
            return await _connect(client, audio, options, identity)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent-name", help="Reuse an existing compatible agent without modifying it.")
    parser.add_argument("--wav", type=Path, help="Mono PCM16 WAV at 24000 Hz; omit for the microphone.")
    parser.add_argument(
        "--duration", type=float, default=CAPTURE_SECONDS, help="Microphone capture duration in seconds."
    )
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Managed session model; no inference is requested.")
    parser.add_argument("--stt-model", choices=TRANSCRIPTION_MODELS, default=DEFAULT_STT_MODEL)
    parser.add_argument("--vad", choices=VAD_TYPES, default=DEFAULT_VAD)
    parser.add_argument("--output", type=Path, help="Write transcripts and usage to a new JSON file.")
    parser.add_argument("--require-usage", action="store_true", help="Fail unless complete final usage is received.")
    return parser.parse_args()


def _configure_transcript_console() -> None:
    """Display completed utterances immediately through a dedicated stdout handler."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("Recognized: %(message)s"))
    transcript_logger.addHandler(handler)
    transcript_logger.setLevel(logging.INFO)


def _main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    logging.getLogger("azure").setLevel(logging.WARNING)
    _configure_transcript_console()
    args = _arguments()
    endpoint = os.getenv("AZURE_VOICE_AGENTS_ENDPOINT", "").strip().rstrip("/")
    if not endpoint:
        raise ValueError("Set AZURE_VOICE_AGENTS_ENDPOINT to your HTTPS Foundry project endpoint.")
    options = Options(
        endpoint=endpoint,
        agent_name=args.agent_name,
        model=args.model,
        stt_model=args.stt_model,
        vad_type=args.vad,
        wav=args.wav,
        duration=args.duration,
        require_usage=args.require_usage,
    )
    result = asyncio.run(run(options))
    if args.output:
        with args.output.open("x", encoding="utf-8") as output:
            json.dump(asdict(result), output, ensure_ascii=False, indent=2)
            output.write("\n")
        logger.info("Saved transcripts and final usage to %s", args.output)
    logger.info("Agent retained for reuse: %s version %s", result.agent_name, result.agent_version)


if __name__ == "__main__":
    try:
        _main()
    except (AzureError, AudioError, ConnectionError, RuntimeError, TimeoutError, ValueError, OSError) as error:
        logger.error("STT session failed (%s); final usage may be unconfirmed", type(error).__name__)
        raise SystemExit(1) from None
