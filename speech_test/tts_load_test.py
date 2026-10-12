"""Bounded threaded Speech TTS component load test with Azure CLI authentication."""

from __future__ import annotations

import argparse
import concurrent.futures
import http.client
import json
import math
import shutil
import ssl
import subprocess
import threading
import time
import wave
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

VOICE = "en-IN-DiyaTurboNeural"
TEXT = "Hello, this is a text-to-speech demo. Welcome to our TTS portal!"
LEVELS = [4, 8, 16, 24, 32, 40, 50]
OUTPUT_FORMAT = "riff-24khz-16bit-mono-pcm"
RAW_FORMAT = "raw-24khz-16bit-mono-pcm"
NS = "{http://www.w3.org/2001/10/synthesis}"


def azure_json(*arguments: str) -> Any:
    executable = shutil.which("az")
    if not executable:
        raise RuntimeError("Azure CLI is required. Install it and run az login.")
    result = subprocess.run(
        [executable, *arguments, "--output", "json", "--only-show-errors"],
        capture_output=True, text=True, check=False,
    )
    if result.returncode:
        raise RuntimeError(f"Azure CLI failed: {result.stderr.strip()}")
    return json.loads(result.stdout)


def validate_ssml(path: Path) -> bytes:
    data = path.read_bytes()
    root = ET.fromstring(data)
    voices = root.findall(f"{NS}voice")
    if (
        root.tag != f"{NS}speak"
        or root.get("{http://www.w3.org/XML/1998/namespace}lang") != "en-IN"
        or len(voices) != 1
        or voices[0].get("name") != VOICE
        or " ".join("".join(voices[0].itertext()).split()) != TEXT
    ):
        raise ValueError(f"Use the exact en-IN {VOICE} voice and supplied demo text.")
    return data


def audio_duration(data: bytes, output_format: str = OUTPUT_FORMAT) -> float:
    if output_format == RAW_FORMAT:
        if not data or len(data) % 2:
            raise ValueError("Expected nonempty, sample-aligned PCM16 audio.")
        if data.startswith(b"RIFF") and data[8:12] == b"WAVE":
            raise ValueError("Expected raw PCM, not a WAV container.")
        if not any(data):
            raise ValueError("Returned audio is entirely silent.")
        return len(data) / (24000 * 2)
    if output_format != OUTPUT_FORMAT:
        raise ValueError(f"Unsupported output format: {output_format}")
    with wave.open(BytesIO(data), "rb") as audio:
        if (
            audio.getnchannels() != 1 or audio.getsampwidth() != 2
            or audio.getframerate() != 24000 or audio.getcomptype() != "NONE"
            or audio.getnframes() == 0
        ):
            raise ValueError("Expected nonempty mono PCM16 24 kHz WAV audio.")
        frames = audio.getnframes()
        pcm = audio.readframes(frames)
        if len(pcm) != frames * 2:
            raise ValueError("Truncated WAV audio.")
        if not any(pcm):
            raise ValueError("Returned audio is entirely silent.")
        return frames / 24000


def percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(fraction * len(ordered)) - 1)], 2)


class Inflight:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.current = 0
        self.peak = 0

    def enter(self) -> None:
        with self.lock:
            self.current += 1
            self.peak = max(self.peak, self.current)

    def leave(self) -> None:
        with self.lock:
            self.current -= 1


class HttpClient(http.client.HTTPSConnection):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.connect_count = 0

    def connect(self) -> None:
        super().connect()
        self.connect_count += 1


def synthesize(
    connection: HttpClient, authorization: str, ssml: bytes,
    inflight: Inflight, worker: int, sequence: int,
    output_format: str = OUTPUT_FORMAT,
) -> tuple[dict[str, Any], bytes]:
    started = time.perf_counter()
    row: dict[str, Any] = {
        "worker": worker, "sequence": sequence, "success": False,
        "status": None, "first_byte_ms": None, "first_audio_sample_ms": None,
    }
    audio = b""
    had_socket = connection.sock is not None
    connects_before = connection.connect_count
    inflight.enter()
    try:
        connection.request("POST", "/cognitiveservices/v1", ssml, {
            "Authorization": authorization,
            "Content-Type": "application/ssml+xml",
            "X-Microsoft-OutputFormat": output_format,
            "User-Agent": "voice-agent-speech-component-test",
        })
        response = connection.getresponse()
        row["status"] = response.status
        row["request_id"] = (
            response.getheader("x-requestid") or response.getheader("apim-request-id")
        )
        row["retry_after"] = response.getheader("Retry-After")
        first = response.read(1)
        first_byte_ms = (time.perf_counter() - started) * 1000 if first else None
        first_audio_sample_ms = None
        if response.status == 200 and output_format == RAW_FORMAT:
            first += response.read(1)
            if len(first) != 2:
                raise ValueError("Raw response ended before the first complete PCM16 sample.")
            first_audio_sample_ms = (time.perf_counter() - started) * 1000
        data = first + response.read()
        if response.status != 200:
            # Do not dump response bodies, which may contain request or authentication data.
            row["error"] = f"HTTP {response.status} {response.reason}"
        else:
            duration = audio_duration(data, output_format)
            row.update(
                success=True, first_byte_ms=round(first_byte_ms, 2),
                audio_seconds=round(duration, 3), bytes=len(data),
                first_audio_sample_ms=(
                    round(first_audio_sample_ms, 2) if first_audio_sample_ms is not None else None
                ),
            )
            audio = data
    except (OSError, http.client.HTTPException, ValueError, wave.Error, EOFError) as error:
        row["error"] = f"{type(error).__name__}: {error}"
        connection.close()
    finally:
        row["connection_reused"] = (
            had_socket and connection.connect_count == connects_before
        )
        row["new_connections"] = connection.connect_count - connects_before
        row["total_ms"] = round((time.perf_counter() - started) * 1000, 2)
        inflight.leave()
    return row, audio


def run_stage(
    host: str, authorization: str, ssml: bytes, threads: int,
    requests_per_worker: int, timeout: float,
    output_format: str = OUTPUT_FORMAT,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    measurement_started: list[float] = []
    barrier = threading.Barrier(
        threads, action=lambda: measurement_started.append(time.perf_counter()),
    )
    inflight = Inflight()
    warmup_inflight = Inflight()
    warmups: list[dict[str, Any]] = []
    warmup_lock = threading.Lock()
    tls = ssl.create_default_context()

    def worker(index: int) -> list[dict[str, Any]]:
        connection = HttpClient(host, timeout=timeout, context=tls)
        rows = []
        try:
            warmup, _ = synthesize(
                connection, authorization, ssml, warmup_inflight, index, -1,
                output_format,
            )
            if warmup["success"] and connection.sock is None:
                warmup["success"] = False
                warmup["error"] = "Server closed the connection after warmup; client is not warm."
            with warmup_lock:
                warmups.append(warmup)
            if not warmup["success"]:
                barrier.abort()
                return rows
            try:
                barrier.wait(timeout=max(60, timeout * 2))
            except threading.BrokenBarrierError:
                return rows
            for sequence in range(requests_per_worker):
                row, _ = synthesize(
                    connection, authorization, ssml, inflight, index, sequence, output_format,
                )
                rows.append(row)
        finally:
            connection.close()
        return rows

    preparation_started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=threads) as executor:
        futures = [executor.submit(worker, index) for index in range(threads)]
        rows = [row for future in futures for row in future.result()]
    finished = time.perf_counter()
    seconds = finished - measurement_started[0] if measurement_started else 0
    successes = [row for row in rows if row["success"]]
    warmed_successes = [row for row in successes if row["connection_reused"]]
    first = [row["first_byte_ms"] for row in warmed_successes]
    total = [row["total_ms"] for row in warmed_successes]
    first_audio = [
        row["first_audio_sample_ms"] for row in warmed_successes
        if row.get("first_audio_sample_ms") is not None
    ]
    summary = {
        "threads": threads, "peak_inflight": inflight.peak, "requests": len(rows),
        "successes": len(successes), "failures": len(rows) - len(successes),
        "http_429": sum(row["status"] == 429 for row in rows),
        "warmup_requests": len(warmups),
        "warmup_failures": sum(not row["success"] for row in warmups),
        "warmup_results": sorted(warmups, key=lambda row: row["worker"]),
        "warmed_successes": len(warmed_successes),
        "cold_successes": len(successes) - len(warmed_successes),
        "measured_new_connections": sum(row["new_connections"] for row in rows),
        "warmup_seconds": round(
            (measurement_started[0] if measurement_started else finished) - preparation_started, 3,
        ),
        "elapsed_seconds": round(seconds, 3),
        "successful_requests_per_second": round(len(successes) / seconds, 3) if seconds else 0,
        "first_byte_ms": {
            label: percentile(first, fraction)
            for label, fraction in [("p50", .5), ("p95", .95), ("p99", .99)]
        },
        "first_audio_sample_ms": {
            label: percentile(first_audio, fraction)
            for label, fraction in [("p50", .5), ("p95", .95), ("p99", .99)]
        },
        "total_ms": {
            label: percentile(total, fraction)
            for label, fraction in [("p50", .5), ("p95", .95), ("p99", .99)]
        },
    }
    return summary, rows


def save_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(report, indent=2, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def positive_int(value: str) -> int:
    parsed = int(value)
    if parsed <= 0:
        raise argparse.ArgumentTypeError("Must be positive.")
    return parsed


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--resource-id", required=True, help="Central India Speech/Foundry resource ARM ID.")
    parser.add_argument("--levels", type=positive_int, nargs="+", default=LEVELS)
    parser.add_argument("--requests-per-worker", type=positive_int, default=20)
    parser.add_argument("--timeout", type=positive_int, default=30)
    parser.add_argument("--stage-gap", type=positive_int, default=5)
    parser.add_argument("--ssml", type=Path, default=Path(__file__).with_name("diya_turbo.ssml"))
    parser.add_argument("--audio-format", choices=("riff", "raw"), default="riff")
    parser.add_argument("--output", type=Path, default=Path(__file__).parent / "results" / "diya-turbo.json")
    args = parser.parse_args()
    if args.levels != sorted(set(args.levels)) or args.levels[-1] > 50:
        parser.error("Levels must be strictly increasing and at most 50 threads.")
    resource = azure_json("resource", "show", "--ids", args.resource_id)
    if resource["location"].lower() != "centralindia":
        parser.error("The resource must be in Central India; no region fallback is allowed.")
    if resource.get("kind") not in {"SpeechServices", "AIServices", "CognitiveServices"}:
        parser.error("Select a Speech or Foundry resource.")
    ssml = validate_ssml(args.ssml)
    output_format = RAW_FORMAT if args.audio_format == "raw" else OUTPUT_FORMAT
    host = "centralindia.tts.speech.microsoft.com"

    def authorization() -> str:
        token = azure_json(
            "account", "get-access-token", "--resource", "https://cognitiveservices.azure.com",
            "--subscription", args.resource_id.split("/")[2],
        )
        return f"Bearer aad#{args.resource_id}#{token['accessToken']}"

    report: dict[str, Any] = {
        "started_at": datetime.now(timezone.utc).isoformat(),
        "region": "centralindia", "resource_id": args.resource_id, "voice": VOICE,
        "text": TEXT, "host": host, "output_format": output_format,
        "first_audio_sample_definition": (
            "Request start to arrival of the first complete PCM16 sample (2 body bytes); "
            "may be silence, not speaker onset."
            if args.audio_format == "raw" else "Not measured for WAV output."
        ),
        "levels": args.levels, "requests_per_worker": args.requests_per_worker,
        "method": (
            "Closed-loop threads; one unmeasured, fully drained synthesis per worker "
            "before a synchronized measured start; same client reused; no retries."
        ),
        "latency_population": "Successful measured requests with no new connection.",
        "stages": [], "requests": [], "completed": False,
    }
    save_report(args.output, report)
    connection = HttpClient(host, timeout=args.timeout)
    try:
        smoke, audio = synthesize(
            connection, authorization(), ssml, Inflight(), 0, 0, output_format,
        )
    finally:
        connection.close()
    report["smoke"] = smoke
    save_report(args.output, report)
    if not smoke["success"]:
        raise RuntimeError(f"Voice smoke test failed; load not started: {smoke.get('error')}")
    if args.audio_format == "raw":
        args.output.with_suffix(".pcm").write_bytes(audio)
        with wave.open(str(args.output.with_suffix(".wav")), "wb") as wav:
            wav.setparams((1, 2, 24000, 0, "NONE", "not compressed"))
            wav.writeframes(audio)
    else:
        args.output.with_suffix(".wav").write_bytes(audio)
    print(f"Smoke passed: {VOICE}; audio {smoke['audio_seconds']} s.")
    for threads in args.levels:
        summary, rows = run_stage(
            host, authorization(), ssml, threads, args.requests_per_worker, args.timeout,
            output_format,
        )
        report["stages"].append(summary)
        report["requests"].extend(dict(row, threads=threads) for row in rows)
        save_report(args.output, report)
        print(json.dumps({key: value for key, value in summary.items() if key != "warmup_results"}), flush=True)
        if summary["warmup_failures"] or summary["requests"] != threads * args.requests_per_worker:
            raise RuntimeError("Stopping ramp: not every worker completed warmup and measurement.")
        if (
            summary["failures"] / summary["requests"] > .1
            or any(row["status"] in {401, 403} for row in rows)
        ):
            raise RuntimeError("Stopping ramp: authorization failure or more than 10% failed requests.")
        if threads != args.levels[-1]:
            time.sleep(args.stage_gap)
    report["completed"] = True
    report["finished_at"] = datetime.now(timezone.utc).isoformat()
    save_report(args.output, report)
    print(f"Report: {args.output}; smoke WAV: {args.output.with_suffix('.wav')}")
    if any(stage["failures"] for stage in report["stages"]):
        raise RuntimeError("Ramp completed with request failures; inspect the report.")


if __name__ == "__main__":
    main()
