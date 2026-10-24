"""Create one stored Voice Agent, run four audio sessions, then evaluate transcripts."""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import math
import os
import uuid
import wave
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Literal, TypedDict

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.aio.operations import AsyncBetaRealtimeConnection
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator, VoiceAgentDefinition
from azure.core.exceptions import HttpResponseError
from azure.identity.aio import DefaultAzureCredential
from dotenv import load_dotenv
from openai import AsyncOpenAI
from openai.types.eval_create_params import DataSourceConfigCustom
from openai.types.evals.create_eval_jsonl_run_data_source_param import (
    CreateEvalJSONLRunDataSourceParam,
    SourceFileContent,
    SourceFileContentContent,
)
from openai.types.evals.run_retrieve_response import RunRetrieveResponse
from openai.types.evals.runs.output_item_list_response import OutputItemListResponse

TURN_TIMEOUT = 180
SAMPLE_RATE = 24000
SAMPLE_WIDTH = 2
CHUNK_BYTES = SAMPLE_RATE * SAMPLE_WIDTH // 10
EVALUATION_TIMEOUT = 300
POLL_INTERVAL = 5
TERMINAL_STATUSES = {"completed", "failed", "canceled", "cancelled"}
INSTRUCTIONS = (
    "You are a concise assistant for travel planning and a fictional shop's "
    "return-policy questions. For travel, keep track of the user's "
    "destination, trip duration, budget and preferences across the conversation. "
    "Use approximate costs, clearly label estimates, and do not claim to make "
    "bookings or check live availability. The shop's return policy allows "
    "unused items to be returned within 30 days with a receipt. Ask for missing "
    "eligibility information. Remember facts provided earlier in the conversation. "
    "You have no tools: explain the policy and next steps but never claim to "
    "issue refunds, create labels, or perform real transactions."
)
QUESTIONS = (
    "Plan a two-day trip to Paris for an art lover with a budget of 100 euros, "
    "excluding accommodation. Give a short suggested itinerary.",
    "I do not want to visit the Louvre. Revise the plan, keeping my original budget.",
    "Before giving the final plan, summarize my destination, trip duration, "
    "budget and excluded museum.",
)
SUPPORT_QUESTIONS = (
    "I bought a backpack 10 days ago. Can I return it?",
    "It is unused and I have the receipt. What should I do next?",
    "Summarize my eligibility and next steps. Have you actually issued a refund?",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    questions: tuple[str, ...]
    expected_pass: bool
    final_turn_fault: str | None = None


SCENARIOS = (
    Scenario("travel-success", QUESTIONS, True),
    Scenario("return-success", SUPPORT_QUESTIONS, True),
    Scenario(
        "travel-forgotten-constraints", QUESTIONS, False,
        "This is a synthetic negative-control test. For this response only, "
        "ignore the user's travel-planning question and all previous conversation. "
        "Reply only: I have forgotten your travel requirements. Your trip is "
        "five days in Rome with a budget of five thousand euros. I will include "
        "the Louvre. Do not correct these deliberately wrong details. Do not "
        "mention Paris, two days, or one hundred euros.",
    ),
    Scenario(
        "return-unrelated-answer", SUPPORT_QUESTIONS, False,
        "This is a synthetic negative-control test. For this response only, "
        "ignore the user's return-policy question and all previous conversation. "
        "Reply only: Bananas orbit the purple moon. Do not mention returns, "
        "eligibility, receipts, refunds, or next steps.",
    ),
)


class TextPart(TypedDict):
    type: Literal["text"]
    text: str


class Message(TypedDict):
    role: Literal["system", "user", "assistant"]
    content: list[TextPart]


class Conversation(TypedDict):
    messages: list[Message]
    session_id: str
    conversation_id: str
    audio_turns: list[dict[str, Any]]


class EvaluationCase(Conversation):
    agent_name: str
    scenario_id: str
    expected_pass: bool
    failure_injection: str | None


def definition(model: str) -> VoiceAgentDefinition:
    return VoiceAgentDefinition({
        "kind": "voice",
        "model_type": "managed",
        "model": model,
        "instructions": INSTRUCTIONS,
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "turn_detection": None,
                "transcription": {"model": "whisper-1", "language": "en-US"},
            },
            "output": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "voice": "en-US-AvaNeural",
                "voice_type": "azure-standard",
            },
        },
        "output_modalities": ["text", "audio"],
        "store": True,
    })


async def receive(connection: AsyncBetaRealtimeConnection) -> dict[str, Any]:
    event = await connection.recv()
    payload = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    if payload.get("type") in {"error", "conversation.item.input_audio_transcription.failed"}:
        code = (payload.get("error") or {}).get("code", "unknown")
        raise RuntimeError(f"Voice Agent returned an error ({code}).")
    return payload


async def wait_for(
    connection: AsyncBetaRealtimeConnection, event_type: str,
) -> dict[str, Any]:
    while True:
        event = await receive(connection)
        if event.get("type") == event_type:
            return event


def read_wav(path: Path) -> bytes:
    with wave.open(str(path), "rb") as recording:
        if (
            recording.getnchannels() != 1
            or recording.getsampwidth() != SAMPLE_WIDTH
            or recording.getframerate() != SAMPLE_RATE
            or recording.getcomptype() != "NONE"
        ):
            raise ValueError("Input must be uncompressed mono 16-bit PCM at 24000 Hz.")
        frames = recording.getnframes()
        if not SAMPLE_RATE // 10 <= frames <= SAMPLE_RATE * 30:
            raise ValueError("Input WAV must contain between 0.1 and 30 seconds.")
        pcm = recording.readframes(frames)
        if len(pcm) != frames * SAMPLE_WIDTH:
            raise ValueError("The input WAV is truncated.")
        return pcm


def write_wav(path: Path, pcm: bytes) -> None:
    if not pcm or len(pcm) % SAMPLE_WIDTH:
        raise ValueError("Output audio is missing or contains incomplete PCM samples.")
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as recording:
        recording.setparams((1, SAMPLE_WIDTH, SAMPLE_RATE, 0, "NONE", "not compressed"))
        recording.writeframes(pcm)


def input_file(audio_dir: Path, scenario: Scenario, index: int) -> Path:
    category = "travel" if scenario.name.startswith("travel-") else "return"
    return audio_dir / f"{category}-{index + 1}.wav"


async def wait_until(deadline: float) -> None:
    while (remaining := deadline - perf_counter()) > 0:
        await asyncio.sleep(remaining)


async def ask(
    connection: AsyncBetaRealtimeConnection, pcm: bytes, fault: str | None = None,
) -> tuple[str, str, bytes]:
    for offset in range(0, len(pcm), CHUNK_BYTES):
        chunk = pcm[offset:offset + CHUNK_BYTES]
        deadline = perf_counter() + len(chunk) / (SAMPLE_RATE * SAMPLE_WIDTH)
        await connection.input_audio_buffer.append(audio=chunk)
        await wait_until(deadline)
    await connection.input_audio_buffer.commit()
    event = await wait_for(connection, "conversation.item.input_audio_transcription.completed")
    transcript = (event.get("transcript") or "").strip()
    if not transcript:
        raise RuntimeError("Input speech produced no transcript; no response was requested.")
    if fault is None:
        await connection.response.create()
    else:
        await connection.response.create(response={"instructions": fault})
    audio = bytearray()
    spoken_parts: list[str] = []
    while True:
        event = await receive(connection)
        kind = event.get("type")
        if kind == "response.output_audio.delta":
            delta = event.get("delta")
            if isinstance(delta, str):
                delta = base64.b64decode(delta, validate=True)
            if not isinstance(delta, bytes):
                raise RuntimeError("Output audio delta has an unsupported format.")
            audio.extend(delta)
            if len(audio) > SAMPLE_RATE * SAMPLE_WIDTH * TURN_TIMEOUT:
                raise RuntimeError("Output audio exceeded the turn duration limit.")
        elif kind == "response.output_audio_transcript.done":
            spoken_parts.append(event.get("transcript") or "")
        elif kind == "response.done":
            if (event.get("response") or {}).get("status") != "completed":
                raise RuntimeError("The spoken response did not complete.")
            break
    spoken = "\n".join(spoken_parts).strip()
    if not audio or len(audio) % SAMPLE_WIDTH or not spoken:
        raise RuntimeError("Response must contain actual PCM audio and its spoken transcript.")
    return transcript, spoken, bytes(audio)


async def apply_final_turn_fault(
    connection: AsyncBetaRealtimeConnection, instructions: str, session_id: str,
) -> None:
    await connection.session.update(session={
        "type": "realtime", "instructions": instructions,
    })
    updated = await wait_for(connection, "session.updated")
    session = updated.get("session") or {}
    if session.get("id") != session_id or session.get("instructions") != instructions:
        raise RuntimeError("The service did not acknowledge the final-turn fault in this session.")


async def converse(
    connection: AsyncBetaRealtimeConnection, scenario: Scenario = SCENARIOS[0],
    *, audio_dir: Path, output_dir: Path,
) -> Conversation:
    conversation_id: str | None = None

    async def wait_ready() -> dict[str, Any]:
        nonlocal conversation_id
        while True:
            event = await receive(connection)
            if event.get("conversation_id"):
                conversation_id = event["conversation_id"]
            if event.get("type") == "session.updated":
                return event

    ready = await asyncio.wait_for(wait_ready(), TURN_TIMEOUT)
    session = ready.get("session") or {}
    session_id = session.get("id")
    if not isinstance(session_id, str) or not session_id:
        raise RuntimeError("The service did not return a realtime session ID.")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise RuntimeError("The stored session did not return a conversation ID.")
    audio_input = (session.get("audio") or {}).get("input") or {}
    if (
        "turn_detection" not in audio_input
        or audio_input["turn_detection"] is not None
        or "audio" not in (session.get("output_modalities") or [])
    ):
        raise RuntimeError("The session did not acknowledge manual audio turns.")

    messages: list[Message] = [{
        "role": "system", "content": [{"type": "text", "text": INSTRUCTIONS}],
    }]
    audio_turns: list[dict[str, Any]] = []
    for index, _question in enumerate(scenario.questions):
        fault = scenario.final_turn_fault if index == len(scenario.questions) - 1 else None
        if fault is not None:
            await asyncio.wait_for(
                apply_final_turn_fault(connection, fault, session_id), TURN_TIMEOUT,
            )
        source = input_file(audio_dir, scenario, index)
        pcm = read_wav(source)
        transcript, answer, audio = await asyncio.wait_for(ask(connection, pcm, fault), TURN_TIMEOUT)
        destination = output_dir / scenario.name / f"turn-{index + 1}-agent.wav"
        write_wav(destination, audio)
        audio_seconds = len(audio) / (SAMPLE_RATE * SAMPLE_WIDTH)
        playback_started = perf_counter()
        print(f"Headless playback wait: {scenario.name}, turn {index + 1}, {audio_seconds:.3f}s")
        await wait_until(playback_started + audio_seconds)
        playback_wait_seconds = perf_counter() - playback_started
        audio_turns.append({
            "input_file": str(source.resolve()),
            "output_file": str(destination.resolve()),
            "input_pcm_bytes": len(pcm),
            "output_pcm_bytes": len(audio),
            "output_audio_seconds": audio_seconds,
            "headless_playback_wait_seconds": playback_wait_seconds,
            "fault_instructions_acknowledged": fault is not None,
        })
        messages.extend([
            {"role": "user", "content": [{"type": "text", "text": transcript}]},
            {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        ])
    return {
        "messages": messages, "session_id": session_id,
        "conversation_id": conversation_id, "audio_turns": audio_turns,
    }


async def verify_persistence(
    project: AIProjectClient, agent_name: str, conversation_id: str,
) -> None:
    async def wait_stored() -> None:
        while True:
            try:
                conversation = await project.beta.voice_agents.conversations.get(
                    agent_name, conversation_id,
                )
                if conversation.status == "completed":
                    audio = await project.beta.voice_agents.conversations.get_audio(
                        agent_name, conversation_id,
                    )
                    duration = audio.duration_ms
                    seconds = (
                        duration.total_seconds() if isinstance(duration, timedelta)
                        else duration / 1000
                    )
                    if seconds <= 0:
                        raise RuntimeError("Stored conversation has no recorded audio duration.")
                    print(f"Verified stored conversation/audio: {conversation_id}")
                    return
                if conversation.status in {"failed", "canceled", "cancelled"}:
                    raise RuntimeError(f"Stored conversation ended as {conversation.status}.")
            except HttpResponseError as error:
                if error.status_code not in {404, 409}:
                    raise
            await asyncio.sleep(2)

    await asyncio.wait_for(wait_stored(), 120)


async def wait_for_evaluation(
    client: AsyncOpenAI, eval_id: str, run_id: str,
) -> RunRetrieveResponse:
    while True:
        run = await client.evals.runs.retrieve(eval_id=eval_id, run_id=run_id)
        if run.status in TERMINAL_STATUSES:
            return run
        if run.status not in {"queued", "in_progress"}:
            raise RuntimeError(f"Unknown evaluation status: {run.status}.")
        await asyncio.sleep(POLL_INTERVAL)


def summarize(
    run: RunRetrieveResponse, outputs: list[OutputItemListResponse], expected: int,
) -> dict[str, Any]:
    counts = run.result_counts
    if run.status != "completed":
        raise RuntimeError(
            f"Evaluation {run.id} ended with status {run.status}; inspect it in Foundry."
        )
    if (
        counts.errored != 0
        or counts.total != expected
        or counts.passed < 0
        or counts.failed < 0
        or counts.passed + counts.failed != expected
        or len(outputs) != expected
        or len({item.datasource_item_id for item in outputs}) != expected
    ):
        raise RuntimeError("Evaluation returned errors, incomplete rows, or inconsistent counts.")
    scores = []
    for item in outputs:
        if not item.results:
            raise RuntimeError("An output item is missing conversation evaluation results.")
        for result in item.results:
            if not result.name or not math.isfinite(result.score):
                raise RuntimeError("An output item returned an invalid evaluation result.")
        scores.append({
            "item": item.datasource_item_id,
            "scenario_id": item.datasource_item.get("scenario_id"),
            "expected_pass": item.datasource_item.get("expected_pass"),
            "actual_pass": all(result.passed for result in item.results),
            "results": [result.model_dump() for result in item.results],
        })
    if sum(all(result.passed for result in item.results) for item in outputs) != counts.passed:
        raise RuntimeError("Per-item results do not match the evaluation pass count.")
    return {
        "eval_id": run.eval_id,
        "run_id": run.id,
        "status": run.status,
        "counts": counts.model_dump(),
        "scores": scores,
        "report_url": run.report_url,
    }


async def evaluate(
    project: AIProjectClient, cases: list[EvaluationCase], judge_deployment: str,
    keep_resources: bool,
) -> dict[str, Any]:
    if not cases or len({case["scenario_id"] for case in cases}) != len(cases):
        raise ValueError("Provide a nonempty set of uniquely named conversation cases.")
    for case in cases:
        messages = case["messages"]
        roles = [message["role"] for message in messages]
        if (
            len(messages) < 5
            or roles[0] != "system"
            or roles[1:] != ["user", "assistant"] * ((len(messages) - 1) // 2)
        ):
            raise ValueError("Evaluation requires a system message and at least two complete turns.")
    if not judge_deployment.strip():
        raise ValueError("A Foundry judge model deployment is required.")
    async with project.get_openai_client(timeout=30, max_retries=0) as client:
        evaluation = await client.evals.create(
            name="Voice Agent multi-turn output quality",
            data_source_config=DataSourceConfigCustom(
                type="custom",
                item_schema={
                    "type": "object",
                    "properties": {
                        "messages": {"type": "array", "items": {"type": "object"}},
                        "agent_name": {"type": "string"},
                        "session_id": {"type": "string"},
                        "conversation_id": {"type": "string"},
                        "audio_turns": {"type": "array", "items": {"type": "object"}},
                        "scenario_id": {"type": "string"},
                        "expected_pass": {"type": "boolean"},
                        "failure_injection": {"type": ["string", "null"]},
                    },
                    "required": [
                        "messages", "agent_name", "session_id", "conversation_id", "audio_turns",
                        "scenario_id", "expected_pass", "failure_injection",
                    ],
                },
                include_sample_schema=False,
            ),
            testing_criteria=[TestingCriterionAzureAIEvaluator(
                type="azure_ai_evaluator",
                name="output_quality",
                evaluator_name="builtin.output_quality",
                data_mapping={"messages": "{{item.messages}}"},
                initialization_parameters={
                    "deployment_name": judge_deployment,
                    "evaluation_level": "conversation",
                },
            )],
        )
        print(f"Evaluation: {evaluation.id}")
        run_id = None
        terminal = False
        try:
            created = await client.evals.runs.create(
                eval_id=evaluation.id,
                name="voice-multi-turn-conversation-run",
                extra_body={"evaluation_level": "conversation"},
                data_source=CreateEvalJSONLRunDataSourceParam(
                    type="jsonl",
                    source=SourceFileContent(
                        type="file_content",
                        content=[SourceFileContentContent(item=dict(case)) for case in cases],
                    ),
                ),
            )
            run_id = created.id
            print(f"Evaluation run: {run_id}")
            run = await asyncio.wait_for(
                wait_for_evaluation(client, evaluation.id, run_id), EVALUATION_TIMEOUT,
            )
            terminal = True
            outputs = [
                item async for item in client.evals.runs.output_items.list(
                    eval_id=evaluation.id, run_id=run_id,
                )
            ]
            summary = summarize(run, outputs, len(cases))
            expected = {case["scenario_id"]: case["expected_pass"] for case in cases}
            if (
                {row["scenario_id"] for row in summary["scores"]} != set(expected)
                or any(row["expected_pass"] != expected[row["scenario_id"]] for row in summary["scores"])
            ):
                raise RuntimeError("Evaluation results do not identify the submitted scenarios.")
            summary["expectations_match"] = all(
                row["actual_pass"] == expected[row["scenario_id"]] for row in summary["scores"]
            )
            return summary
        finally:
            if keep_resources:
                print(f"Retained evaluation: {evaluation.id}; run: {run_id}")
            else:
                try:
                    if run_id is not None and not terminal:
                        await client.evals.runs.cancel(eval_id=evaluation.id, run_id=run_id)
                finally:
                    await client.evals.delete(eval_id=evaluation.id)
                    print(f"Deleted evaluation: {evaluation.id}")


async def run(
    endpoint: str, model: str, judge_deployment: str, keep_resources: bool = False,
    output: Path | None = None,
    *, audio_dir: Path, audio_output_dir: Path | None = None,
) -> dict[str, Any]:
    for scenario in SCENARIOS:
        for index in range(len(scenario.questions)):
            read_wav(input_file(audio_dir, scenario, index))
    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint.rstrip("/"), credential=credential, allow_preview=True,
    ) as project:
        cases: list[EvaluationCase] = []
        agent_name = f"voice-evaluation-{uuid.uuid4().hex[:12]}"
        created = await project.agents.create_version(
            agent_name=agent_name,
            definition=definition(model),
            description="One stored Voice Agent evaluated across four audio sessions.",
        )
        print(f"Voice Agent: {agent_name}")
        try:
            saved = await project.agents.get_version(
                agent_name=agent_name, agent_version=created.version,
            )
            if saved.definition["store"] is not True:
                raise RuntimeError("The saved Voice Agent definition did not enable store=True.")
            await project.agents.enable(agent_name=agent_name)
            for scenario in SCENARIOS:
                async with project.beta.voice_agents.realtime.connect(
                    agent_name=agent_name,
                ) as connection:
                    conversation = await converse(
                        connection, scenario, audio_dir=audio_dir,
                        output_dir=audio_output_dir or Path("voice-agent-output") / agent_name,
                    )
                print(f"Scenario: {scenario.name}; session: {conversation['session_id']}")
                await verify_persistence(project, agent_name, conversation["conversation_id"])
                cases.append({
                    "messages": conversation["messages"],
                    "agent_name": agent_name,
                    "session_id": conversation["session_id"],
                    "conversation_id": conversation["conversation_id"],
                    "audio_turns": conversation["audio_turns"],
                    "scenario_id": scenario.name,
                    "expected_pass": scenario.expected_pass,
                    "failure_injection": scenario.final_turn_fault,
                })
        finally:
            if keep_resources:
                print(f"Retained Voice Agent: {agent_name}")
            else:
                await project.agents.delete(agent_name=agent_name)
                print(f"Deleted Voice Agent: {agent_name}")
        print(f"Collected {len(cases)} independent multi-turn conversations.")
        summary = await evaluate(project, cases, judge_deployment, keep_resources)
        if output is not None:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(
                json.dumps({"conversations": cases, "evaluation": summary}, indent=2),
                encoding="utf-8",
            )
            print(f"Saved synthetic conversations and evaluation results: {output}")
        print(json.dumps(summary, indent=2))
        print("Scenario | Intended | Evaluator | Match")
        for row in summary["scores"]:
            print(
                f"{row['scenario_id']} | "
                f"{'PASS' if row['expected_pass'] else 'FAIL'} | "
                f"{'PASS' if row['actual_pass'] else 'FAIL'} | "
                f"{row['expected_pass'] == row['actual_pass']}"
            )
        if not summary["expectations_match"]:
            raise RuntimeError(
                "Evaluation completed but did not match all intended outcomes; "
                "inspect the actual scores and reasons rather than relabeling them."
            )
        return summary


def main() -> None:
    load_dotenv(Path(__file__).with_name(".env"))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-resources", action="store_true",
        help="Retain the created agent and evaluation, including on failure.",
    )
    parser.add_argument(
        "--output", type=Path,
        help="Save synthetic transcripts, fault metadata and actual results as JSON.",
    )
    parser.add_argument("--audio-dir", type=Path, required=True, help="Directory with six input WAVs.")
    parser.add_argument("--audio-output-dir", type=Path, help="Directory for actual agent output WAVs.")
    args = parser.parse_args()
    endpoint = os.getenv("AZURE_VOICE_AGENTS_ENDPOINT", "").strip()
    model = os.getenv("AZURE_VOICE_AGENTS_MODEL", "gpt-realtime").strip()
    judge_deployment = os.getenv("FOUNDRY_MODEL_NAME", "").strip()
    if not endpoint:
        parser.error("Set AZURE_VOICE_AGENTS_ENDPOINT in the environment or sample .env.")
    if not model:
        parser.error("AZURE_VOICE_AGENTS_MODEL must not be blank.")
    if not judge_deployment:
        parser.error("Set FOUNDRY_MODEL_NAME to the judge model deployment in your Project.")
    asyncio.run(run(
        endpoint, model, judge_deployment, args.keep_resources, args.output,
        audio_dir=args.audio_dir, audio_output_dir=args.audio_output_dir,
    ))


if __name__ == "__main__":
    main()
