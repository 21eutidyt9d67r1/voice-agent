"""Create a Voice Agent, converse over text, and evaluate its actual replies."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypedDict

from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.aio.operations import AsyncBetaRealtimeConnection
from azure.ai.projects.models import TestingCriterionAzureAIEvaluator, VoiceAgentDefinition
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

TURN_TIMEOUT = 60
EVALUATION_TIMEOUT = 300
POLL_INTERVAL = 5
TERMINAL_STATUSES = {"completed", "failed", "canceled", "cancelled"}
INSTRUCTIONS = (
    "You are a concise travel planning assistant. Keep track of the user's "
    "destination, trip duration, budget and preferences across the conversation. "
    "Use approximate costs, clearly label estimates, and do not claim to make "
    "bookings or check live availability."
)
QUESTIONS = (
    "Plan a two-day trip to Paris for an art lover with a budget of 100 euros, "
    "excluding accommodation. Give a short suggested itinerary.",
    "I do not want to visit the Louvre. Revise the plan, keeping my original budget.",
    "Before giving the final plan, summarize my destination, trip duration, "
    "budget and excluded museum.",
)
SUPPORT_INSTRUCTIONS = (
    "You are a concise assistant for a fictional shop. Its return policy allows "
    "unused items to be returned within 30 days with a receipt. Ask for missing "
    "eligibility information. Remember facts provided earlier in the conversation. "
    "You have no tools: explain the policy and next steps but never claim to "
    "issue refunds, create labels, or perform real transactions."
)
SUPPORT_QUESTIONS = (
    "I bought a backpack 10 days ago. Can I return it?",
    "It is unused and I have the receipt. What should I do next?",
    "Summarize my eligibility and next steps. Have you actually issued a refund?",
)


@dataclass(frozen=True)
class Scenario:
    name: str
    instructions: str
    questions: tuple[str, ...]
    expected_pass: bool
    final_turn_fault: str | None = None


SCENARIOS = (
    Scenario("travel-success", INSTRUCTIONS, QUESTIONS, True),
    Scenario("return-success", SUPPORT_INSTRUCTIONS, SUPPORT_QUESTIONS, True),
    Scenario(
        "travel-forgotten-constraints", INSTRUCTIONS, QUESTIONS, False,
        "For this synthetic negative-control test, reply with exactly this text "
        "and nothing else: Your trip is five days in Rome with a budget of 5000 "
        "euros. I recommend visiting the Louvre.",
    ),
    Scenario(
        "return-unrelated-answer", SUPPORT_INSTRUCTIONS, SUPPORT_QUESTIONS, False,
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


class EvaluationCase(Conversation):
    scenario_id: str
    expected_pass: bool
    failure_injection: str | None


def definition(model: str, instructions: str = INSTRUCTIONS) -> VoiceAgentDefinition:
    return VoiceAgentDefinition({
        "kind": "voice",
        "model_type": "managed",
        "model": model,
        "instructions": instructions,
        "audio": {
            "input": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "turn_detection": None,
            },
            "output": {
                "format": {"type": "audio/pcm", "rate": 24000},
                "voice": "en-US-AvaNeural",
                "voice_type": "azure-standard",
            },
        },
        "output_modalities": ["text"],
        "store": False,
    })


async def receive(connection: AsyncBetaRealtimeConnection) -> dict[str, Any]:
    event = await connection.recv()
    payload = event.as_dict() if hasattr(event, "as_dict") else dict(event)
    if payload.get("type") == "error":
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


def response_text(response: dict[str, Any]) -> str:
    if response.get("status") != "completed":
        raise RuntimeError(
            f"Voice response did not complete: {response.get('status', 'unknown')}."
        )
    parts = [
        part["text"]
        for item in response.get("output", [])
        if item.get("type") == "message" and item.get("role") == "assistant"
        for part in item.get("content", [])
        if part.get("type") in {"text", "output_text"}
        and isinstance(part.get("text"), str)
    ]
    text = "\n".join(parts).strip()
    if not text:
        raise RuntimeError("Voice response completed without assistant text.")
    return text


async def ask(
    connection: AsyncBetaRealtimeConnection, question: str, fault: str | None = None,
) -> str:
    await connection.conversation.item.create(item={
        "id": uuid.uuid4().hex,
        "type": "message",
        "role": "user",
        "content": [{"type": "input_text", "text": question}],
    })
    if fault is None:
        await connection.response.create()
    else:
        await connection.response.create(response={"instructions": fault})
    event = await wait_for(connection, "response.done")
    return response_text(event.get("response") or {})


async def converse(
    connection: AsyncBetaRealtimeConnection, scenario: Scenario = SCENARIOS[0],
) -> Conversation:
    ready = await asyncio.wait_for(wait_for(connection, "session.updated"), TURN_TIMEOUT)
    session = ready.get("session") or {}
    audio_input = (session.get("audio") or {}).get("input") or {}
    if (
        "turn_detection" not in audio_input
        or audio_input["turn_detection"] is not None
        or session.get("output_modalities") != ["text"]
    ):
        raise RuntimeError("The session did not acknowledge manual text-only turns.")

    messages: list[Message] = [{
        "role": "system", "content": [{"type": "text", "text": scenario.instructions}],
    }]
    for index, question in enumerate(scenario.questions):
        fault = scenario.final_turn_fault if index == len(scenario.questions) - 1 else None
        answer = await asyncio.wait_for(ask(connection, question, fault), TURN_TIMEOUT)
        messages.extend([
            {"role": "user", "content": [{"type": "text", "text": question}]},
            {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        ])
    return {"messages": messages}


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
                        "scenario_id": {"type": "string"},
                        "expected_pass": {"type": "boolean"},
                        "failure_injection": {"type": ["string", "null"]},
                    },
                    "required": ["messages", "scenario_id", "expected_pass", "failure_injection"],
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
) -> dict[str, Any]:
    async with DefaultAzureCredential() as credential, AIProjectClient(
        endpoint=endpoint.rstrip("/"), credential=credential, allow_preview=True,
    ) as project:
        cases: list[EvaluationCase] = []
        for scenario in SCENARIOS:
            agent_name = f"voice-evaluation-{uuid.uuid4().hex[:12]}"
            await project.agents.create_version(
                agent_name=agent_name,
                definition=definition(model, scenario.instructions),
                description=f"Synthetic evaluation case: {scenario.name}.",
            )
            print(f"Scenario: {scenario.name}; Voice Agent: {agent_name}")
            try:
                await project.agents.enable(agent_name=agent_name)
                async with project.beta.voice_agents.realtime.connect(
                    agent_name=agent_name,
                ) as connection:
                    conversation = await converse(connection, scenario)
                cases.append({
                    "messages": conversation["messages"],
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
    asyncio.run(run(endpoint, model, judge_deployment, args.keep_resources, args.output))


if __name__ == "__main__":
    main()
