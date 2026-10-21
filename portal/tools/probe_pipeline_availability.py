# Copyright (c) Microsoft. All rights reserved.
"""Probe which Editor model, transcription (STT) and voice choices work in one Foundry Project.

Every candidate comes from the Editor's own catalog in static/handoff/handoff-core.mjs. Each one
is published as a temporary voice Agent, exercised once over the real Voice WebSocket, and then
deleted:

- model: a text turn must return audio;
- voice: a text turn on an available compatible model must return audio;
- STT: audio recorded from a model probe is sent as input and must produce a transcription.

Only an explicit service rejection (HTTP 4xx on publication or an ``error`` event) marks a choice
unavailable. Timeouts, throttling and server errors are recorded as ``unknown`` so that a transient
failure never hides a working choice. The Editor reads the output file and hides only choices
whose ``available`` is ``false``, and only for the Project the file was probed against.

Publishing and Voice sessions call the real service and may incur charges.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import copy
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import subprocess
import sys
from urllib.parse import quote
import uuid

import requests

PORTAL_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PORTAL_ROOT))

from common import AgentsConfig  # noqa: E402
from demo_server import (  # noqa: E402
    ProjectWebSocketConnect,
    build_upstream_ws_headers,
    build_upstream_ws_url,
)

CORE_MODULE = PORTAL_ROOT / "static" / "handoff" / "handoff-core.mjs"
DEFAULT_OUTPUT = PORTAL_ROOT / "static" / "handoff" / "pipeline-availability.json"
PREFERRED_BASE_MODEL = "gpt-realtime"
SESSION_SECONDS = 60
AUDIO_EVENTS = {"response.output_audio.delta", "response.audio.delta"}
TRANSCRIPTION_DONE = "conversation.item.input_audio_transcription.completed"
TRANSCRIPTION_FAILED = "conversation.item.input_audio_transcription.failed"
PROBE_TEXT = "Say hello in one short sentence."

# Dump the Editor catalog, with each model's compatible and default choices, as JSON.
CATALOG_SCRIPT = """
const m = await import(process.argv[1]);
const C = m.PIPELINE_COMPONENTS;
const models = C.model.map((model) => {
  const pipeline = m.estimatePipeline({ model: model.id }).pipeline;
  const compatible = (kind) => m.pipelineComponentOptions(kind, { model: model.id })
    .filter((item) => item.compatible !== false).map((item) => item.id);
  return {
    id: model.id,
    architecture: model.architecture,
    stt: compatible("stt"),
    voices: compatible("voice"),
    defaultStt: pipeline.stt.id,
    defaultVoice: pipeline.voice.id,
  };
});
console.log(JSON.stringify({
  models,
  stt: C.stt.map((item) => item.id),
  voices: C.voice.map((item) => ({ id: item.id, type: item.type })),
  blank: m.createBlankDefinition(),
}));
"""


class Unavailable(Exception):
    """The service explicitly rejected the choice."""


class Unknown(Exception):
    """The probe could not reach a verdict (timeout, throttling, server or transport error)."""


def load_catalog() -> dict:
    output = subprocess.run(
        ["node", "--input-type=module", "-e", CATALOG_SCRIPT, CORE_MODULE.as_uri()],
        check=True, capture_output=True, text=True,
    ).stdout
    return json.loads(output)


def short(text: str, limit: int = 300) -> str:
    return " ".join(str(text).split())[:limit]


def probe_name(kind: str, value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "-", value).strip("-").lower()[:30]
    return f"availability-probe-{kind}-{slug}-{uuid.uuid4().hex[:6]}"


def probe_definition(blank: dict, model: str, stt: str, voice: str, voice_types: dict) -> dict:
    definition = copy.deepcopy(blank)
    definition.pop("handoff", None)
    definition["model"] = model
    definition["model_type"] = "managed"
    definition["store"] = False
    definition["instructions"] = "You are an availability probe. Reply with one short sentence."
    definition["audio"]["input"]["transcription"] = {"model": stt}
    # Written the way the Editor writes it: a bare name only for OpenAI voices.
    voice_type = voice_types.get(voice, "openai")
    definition["audio"]["output"]["voice"] = (
        voice if voice_type == "openai" else {"type": voice_type, "name": voice}
    )
    return definition


def publish(cfg: AgentsConfig, name: str, definition: dict) -> None:
    response = requests.post(
        f"{cfg.agents_base}/agents/{quote(name, safe='')}/versions",
        params={"api-version": cfg.api_version},
        headers=cfg.rest_headers(),
        json={
            "definition": definition,
            "description": "Pipeline availability probe; deleted after the probe.",
        },
        timeout=120,
    )
    if response.status_code in (401, 403, 408, 429) or response.status_code >= 500:
        raise Unknown(f"publish HTTP {response.status_code}: {short(response.text)}")
    if response.status_code >= 400:
        raise Unavailable(f"publish HTTP {response.status_code}: {short(response.text)}")


def delete(cfg: AgentsConfig, name: str) -> None:
    try:
        requests.delete(cfg.agent_url(name), headers=cfg.rest_headers(), timeout=60)
    except requests.RequestException:
        pass  # The probe Agent name is unique; a failed cleanup does not affect results.


async def voice_session(cfg: AgentsConfig, agent: str, *, audio: bytes = b"") -> dict:
    """Send a text turn (or ``audio`` as input) and collect output audio or a transcription."""
    path = f"/agents/{quote(agent, safe='')}/endpoint/protocols/voice"
    url, _ = build_upstream_ws_url(cfg, path, {"store": "false"})
    headers = await asyncio.to_thread(build_upstream_ws_headers, cfg, {})
    result = {"pcm": bytearray(), "transcript": None}
    try:
        async with ProjectWebSocketConnect(
            url, additional_headers=headers, max_size=16 * 1024 * 1024, open_timeout=60,
        ) as socket:
            sent = False
            deadline = asyncio.get_running_loop().time() + SESSION_SECONDS
            while True:
                remaining = deadline - asyncio.get_running_loop().time()
                if remaining <= 0:
                    raise Unknown("no result within the session time limit")
                try:
                    raw = await asyncio.wait_for(socket.recv(), timeout=min(remaining, 5))
                except asyncio.TimeoutError:
                    continue
                if isinstance(raw, bytes):
                    continue
                event = json.loads(raw)
                kind = str(event.get("type") or "")
                if kind == "error":
                    message = short(json.dumps(event.get("error") or event))
                    if audio and "buffer" in message.lower() and "empty" in message.lower():
                        continue  # Server VAD already committed the audio before our commit.
                    raise Unavailable(f"service error: {message}")
                if kind in {"session.created", "session.updated"} and not sent:
                    sent = True
                    if audio:
                        for start in range(0, len(audio), 4800):
                            await socket.send(json.dumps({
                                "type": "input_audio_buffer.append",
                                "audio": base64.b64encode(audio[start:start + 4800]).decode(),
                            }))
                        await socket.send(json.dumps({
                            "type": "input_audio_buffer.append",
                            "audio": base64.b64encode(bytes(48000)).decode(),
                        }))
                        await socket.send(json.dumps({"type": "input_audio_buffer.commit"}))
                    else:
                        await socket.send(json.dumps({
                            "type": "conversation.item.create",
                            "item": {
                                "type": "message", "role": "user",
                                "content": [{"type": "input_text", "text": PROBE_TEXT}],
                            },
                        }))
                        await socket.send(json.dumps({"type": "response.create"}))
                elif kind in AUDIO_EVENTS and not audio:
                    result["pcm"].extend(base64.b64decode(event.get("delta") or ""))
                elif kind == "response.done" and not audio:
                    status = (event.get("response") or {}).get("status")
                    if status == "failed":
                        details = (event.get("response") or {}).get("status_details")
                        raise Unavailable(f"response failed: {short(json.dumps(details))}")
                    if not result["pcm"]:
                        raise Unavailable("response finished without audio")
                    return result
                elif kind == TRANSCRIPTION_DONE and audio:
                    result["transcript"] = str(event.get("transcript") or "")
                    return result
                elif kind == TRANSCRIPTION_FAILED and audio:
                    raise Unavailable(f"transcription failed: {short(json.dumps(event.get('error')))}")
    except (Unavailable, Unknown):
        raise
    except Exception as error:  # noqa: BLE001 - transport problems are not availability verdicts
        raise Unknown(f"{type(error).__name__}: {short(error)}") from error


async def probe(cfg, kind, value, definition, *, audio=b""):
    name = probe_name(kind, value)
    try:
        await asyncio.to_thread(publish, cfg, name, definition)
        session = await voice_session(cfg, name, audio=audio)
        entry = {"available": True}
        if audio:
            entry["transcript"] = session["transcript"][:80]
        return entry, bytes(session["pcm"])
    except Unavailable as error:
        return {"available": False, "reason": str(error)}, b""
    except Unknown as error:
        return {"available": None, "reason": str(error)}, b""
    finally:
        await asyncio.to_thread(delete, cfg, name)


async def run(cfg: AgentsConfig, catalog: dict, kinds: set[str], concurrency: int) -> dict:
    gate = asyncio.Semaphore(concurrency)
    models = {model["id"]: model for model in catalog["models"]}
    blank = catalog["blank"]
    voice_types = {voice["id"]: voice["type"] for voice in catalog["voices"]}
    results = {"models": {}, "stt": {}, "voices": {}}
    recorded = {}

    async def limited(kind, value, definition, audio=b""):
        async with gate:
            entry, pcm = await probe(cfg, kind, value, definition, audio=audio)
        print(f"{kind:6} {value:40} {entry['available']} {entry.get('reason', '')[:100]}", flush=True)
        return value, entry, pcm

    if kinds & {"model", "stt", "voice"}:
        jobs = [
            limited("model", model["id"], probe_definition(
                blank, model["id"], model["defaultStt"], model["defaultVoice"], voice_types,
            ))
            for model in models.values()
        ] if "model" in kinds else [
            limited("model", PREFERRED_BASE_MODEL, probe_definition(
                blank, PREFERRED_BASE_MODEL,
                models[PREFERRED_BASE_MODEL]["defaultStt"], models[PREFERRED_BASE_MODEL]["defaultVoice"],
                voice_types,
            )),
        ]
        for value, entry, pcm in await asyncio.gather(*jobs):
            if "model" in kinds or entry["available"]:
                results["models"][value] = entry
            if pcm:
                recorded[value] = pcm

    def base_model(choices_key: str, value: str) -> str | None:
        candidates = [
            model for model in models.values()
            if value in model[choices_key] and results["models"].get(model["id"], {}).get("available")
        ]
        preferred = [model for model in candidates if model["id"] == PREFERRED_BASE_MODEL]
        chosen = preferred or candidates
        return chosen[0]["id"] if chosen else None

    if "voice" in kinds:
        jobs = []
        for voice in (item["id"] for item in catalog["voices"]):
            model = base_model("voices", voice)
            if model is None:
                results["voices"][voice] = {
                    "available": False, "reason": "no available model supports this voice",
                }
                continue
            jobs.append(limited("voice", voice, probe_definition(
                blank, model, models[model]["defaultStt"], voice, voice_types,
            )))
        for value, entry, _ in await asyncio.gather(*jobs):
            results["voices"][value] = entry

    if "stt" in kinds:
        audio = recorded.get(PREFERRED_BASE_MODEL) or next(iter(recorded.values()), b"")
        jobs = []
        for stt in catalog["stt"]:
            model = base_model("stt", stt)
            if model is None:
                results["stt"][stt] = {
                    "available": False, "reason": "no available model supports this transcriber",
                }
                continue
            if not audio:
                results["stt"][stt] = {
                    "available": None, "reason": "no recorded audio to transcribe",
                }
                continue
            jobs.append(limited("stt", stt, probe_definition(
                blank, model, stt, models[model]["defaultVoice"], voice_types,
            ), audio))
        for value, entry, _ in await asyncio.gather(*jobs):
            results["stt"][value] = entry
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", 1)[0])
    parser.add_argument("--project-endpoint", required=True,
                        help="https://<account>.services.ai.azure.com/api/projects/<project>")
    parser.add_argument("--credential-mode", choices=("default", "cli"), default="cli")
    parser.add_argument("--kinds", default="model,stt,voice",
                        help="Comma-separated subset of model, stt, voice.")
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    kinds = {item.strip() for item in args.kinds.split(",") if item.strip()}
    if not kinds <= {"model", "stt", "voice"}:
        parser.error("--kinds accepts only model, stt and voice")
    cfg = AgentsConfig.from_endpoint(args.project_endpoint, credential_mode=args.credential_mode)
    catalog = load_catalog()
    results = asyncio.run(run(cfg, catalog, kinds, max(1, args.concurrency)))
    if not any(entry["available"] for entry in results["models"].values()):
        # Every choice is probed through a model; if none works, the probe itself is suspect.
        raise SystemExit("No model passed the probe; not writing results. Check the errors above.")
    previous = {}
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
        if previous.get("project") != f"{cfg.account}@{cfg.project}":
            previous = {}
    document = {
        "schema_version": 1,
        "probed_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        # Matches the Editor's /config "project" value, so the file applies only to this Project.
        "project": f"{cfg.account}@{cfg.project}",
        "models": results["models"] if "model" in kinds else previous.get("models", {}),
        "stt": results["stt"] if "stt" in kinds else previous.get("stt", {}),
        "voices": results["voices"] if "voice" in kinds else previous.get("voices", {}),
    }
    args.output.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    for key in ("models", "stt", "voices"):
        entries = document[key].values()
        print(
            f"{key}: {sum(1 for e in entries if e['available'] is True)} available, "
            f"{sum(1 for e in entries if e['available'] is False)} unavailable, "
            f"{sum(1 for e in entries if e['available'] is None)} unknown"
        )
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
