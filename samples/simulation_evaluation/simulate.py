"""Generate and evaluate conversations with Foundry's cloud simulation API."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import time
import uuid
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

if TYPE_CHECKING:
    from openai import OpenAI

API_VERSION = "2025-11-15-preview"
HERE = Path(__file__).resolve().parent
TERMINAL_STATES = {"completed", "failed", "canceled"}


def required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise ValueError(f"Set {name} before running this command.")
    return value


def project_endpoint() -> str:
    endpoint = required_env("AZURE_AI_PROJECT_ENDPOINT").rstrip("/")
    parsed = urlparse(endpoint)
    if (
        parsed.scheme != "https"
        or not re.fullmatch(
            r"[a-z0-9][a-z0-9-]*\.services\.ai\.azure\.com",
            parsed.hostname or "",
            re.IGNORECASE,
        )
        or not re.fullmatch(r"/api/projects/[A-Za-z0-9._-]+", parsed.path)
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Use an HTTPS Foundry project endpoint without query parameters.")
    return endpoint


def positive_seconds(value: str) -> float:
    result = float(value)
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("Expected a finite number greater than zero.")
    return result


def load_scenarios(path: Path) -> list[dict[str, str]]:
    scenarios = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{number}: invalid JSON.") from error
        if not isinstance(row, dict) or set(row) != {
            "test_case_id", "test_case_description"
        }:
            raise ValueError(
                f"{path}:{number}: provide only test_case_id and test_case_description."
            )
        identifier = row["test_case_id"]
        description = row["test_case_description"]
        if (
            not isinstance(identifier, str)
            or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", identifier)
            or identifier in seen
            or not isinstance(description, str)
            or not 1 <= len(description) <= 2500
            or not description.strip()
        ):
            raise ValueError(f"{path}:{number}: invalid or duplicate scenario.")
        seen.add(identifier)
        scenarios.append(row)
    if not scenarios:
        raise ValueError("Provide at least one scenario.")
    return scenarios


def build_requests(args: argparse.Namespace) -> dict[str, Any]:
    scenarios = load_scenarios(args.scenarios)
    if len(scenarios) * args.repetitions > 20:
        raise ValueError("This sample permits at most 20 conversations per run.")
    agent_name = required_env("FOUNDRY_AGENT_NAME")
    agent_version = required_env("FOUNDRY_AGENT_VERSION")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,62}", agent_name):
        raise ValueError("FOUNDRY_AGENT_NAME must be a valid agent name.")
    if not re.fullmatch(r"[1-9][0-9]*", agent_version):
        raise ValueError("FOUNDRY_AGENT_VERSION must pin a positive integer version.")
    simulator_model = required_env("AZURE_AI_SIMULATOR_MODEL")
    if not re.fullmatch(r"[^/\s<>]+/[^/\s<>]+", simulator_model):
        raise ValueError("AZURE_AI_SIMULATOR_MODEL must be connectionName/deploymentName.")
    judge_model = required_env("AZURE_AI_MODEL_DEPLOYMENT_NAME")
    model_configuration: dict[str, Any] = {"model": simulator_model}
    if args.voice_name:
        if not re.fullmatch(r"[A-Za-z0-9-]+Neural", args.voice_name):
            raise ValueError("Use an Azure standard neural voice name.")
        model_configuration["voice_model"] = {
            "type": "azure-standard",
            "name": args.voice_name,
        }
    return {
        "endpoint": project_endpoint(),
        "mode": "voice" if args.voice_name else "text",
        "expected_conversations": len(scenarios) * args.repetitions,
        "evaluation": {
            "name": "Voice Agent scenario simulation",
            "data_source_config": {
                "type": "custom",
                "item_schema": {
                    "type": "object",
                    "properties": {"messages": {"type": "array"}},
                    "required": ["messages"],
                },
                "include_sample_schema": False,
            },
            "testing_criteria": [
                {
                    "type": "azure_ai_evaluator",
                    "name": name,
                    "evaluator_name": f"builtin.{name}",
                    "initialization_parameters": {"model": judge_model},
                    "data_mapping": {"messages": "{{item.messages}}"},
                }
                for name in ("task_completion", "coherence")
            ],
        },
        "run": {
            "name": "scenario-simulation-run",
            "evaluation_level": "conversation",
            "data_source": {
                "type": "azure_ai_user_conversation_simulation",
                "source": {
                    "type": "inline_user_conversation_simulation",
                    "test_cases": scenarios,
                },
                "target": {
                    "type": "azure_ai_agent",
                    "name": agent_name,
                    "version": agent_version,
                },
                "model_configuration": model_configuration,
                "default_simulation_configuration": {
                    "max_num_turns": args.max_turns,
                    "conversation_repetitions": args.repetitions,
                    "enable_conversation_dataset_generation": True,
                },
            },
        },
    }


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=True) + "\n", encoding="utf-8")


def collect_results(
    client: OpenAI,
    eval_id: str,
    run_id: str,
    output: Path,
    timeout_seconds: float,
    expected_conversations: int | None = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    while True:
        run = client.evals.runs.retrieve(run_id=run_id, eval_id=eval_id)
        write_json(output / "run.json", run.to_dict())
        if run.status in TERMINAL_STATES:
            break
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(
                f"Stopped waiting for {eval_id}/{run_id}; the cloud run is NOT canceled. "
                "Use the results command to resume, or cancel it in Foundry."
            )
        time.sleep(min(5, remaining))
    if run.status != "completed":
        raise RuntimeError(f"Simulation ended in {run.status}: {run.error}")
    # The SDK iterator follows all pages; individual errors are not passing scores.
    items = [
        item.to_dict()
        for item in client.evals.runs.output_items.list(run_id=run_id, eval_id=eval_id)
    ]
    write_json(output / "output_items.json", items)
    counts = run.result_counts
    if (
        not items
        or counts.errored
        or counts.total == 0
        or len(items) != counts.total
        or (expected_conversations is not None and counts.total != expected_conversations)
    ):
        raise RuntimeError("The completed run has missing output or evaluation errors; inspect artifacts.")
    if any(item.get("status") != "pass" for item in items):
        raise RuntimeError("One or more output items did not pass; inspect output_items.json.")
    for item in items:
        results = {result["name"]: result for result in item.get("results", [])}
        if any(
            results.get(name, {}).get("passed") is not True
            for name in ("task_completion", "coherence")
        ):
            raise RuntimeError("Missing or failing conversation scores; inspect output_items.json.")
    if counts.failed:
        raise RuntimeError("One or more conversations failed evaluation; inspect output_items.json.")
    print(f"Cloud run completed: {eval_id}/{run_id}; inspect scores and reasons in {output}.")
    print(f"Report URL: {run.report_url}")


def submit(client: OpenAI, plan: dict[str, Any], output: Path) -> tuple[str, str]:
    evaluation = client.evals.create(**plan["evaluation"])
    write_json(output / "receipt.json", {"eval_id": evaluation.id, "run_id": None})
    print(f"Evaluation ID: {evaluation.id}", flush=True)
    request = plan["run"]
    run = client.evals.runs.create(
        eval_id=evaluation.id,
        name=request["name"],
        data_source=request["data_source"],
        extra_body={"evaluation_level": request["evaluation_level"]},
    )
    write_json(output / "receipt.json", {"eval_id": evaluation.id, "run_id": run.id})
    print(f"Run ID: {run.id}", flush=True)
    return evaluation.id, run.id


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest="command", required=True)
    for name in ("plan", "submit", "results"):
        command = commands.add_parser(name)
        if name != "results":
            command.add_argument("--scenarios", type=Path, default=HERE / "scenarios.jsonl")
            command.add_argument("--max-turns", type=int, choices=range(1, 21), default=4)
            command.add_argument("--repetitions", type=int, choices=range(1, 6), default=1)
            command.add_argument("--voice-name", help="Enable cloud voice simulation with this standard neural voice.")
        else:
            command.add_argument("--eval-id", required=True)
            command.add_argument("--run-id", required=True)
            command.add_argument(
                "--expected-conversations", type=int, choices=range(1, 21), required=True
            )
        if name != "plan":
            command.add_argument("--timeout-seconds", type=positive_seconds, default=600)
            command.add_argument("--output", type=Path)
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    plan = build_requests(args) if args.command != "results" else None
    if args.command == "plan":
        print(json.dumps(plan, indent=2))
        return

    from azure.ai.projects import AIProjectClient
    from azure.identity import DefaultAzureCredential

    endpoint = plan["endpoint"] if plan is not None else project_endpoint()
    output = args.output or Path("voice-agent-output") / f"simulation-{uuid.uuid4().hex}"
    output.mkdir(parents=True, exist_ok=False)
    print(f"Artifacts: {output.resolve()}", flush=True)
    if plan is not None:
        write_json(output / "request.json", plan)
    with (
        DefaultAzureCredential() as credential,
        AIProjectClient(endpoint=endpoint, credential=credential) as project,
        project.get_openai_client(
            base_url=f"{endpoint}/openai",
            default_query={"api-version": API_VERSION},
            timeout=30,
            max_retries=0,
        ) as client,
    ):
        if plan is not None:
            eval_id, run_id = submit(client, plan, output)
        else:
            eval_id, run_id = args.eval_id, args.run_id
            write_json(output / "receipt.json", {"eval_id": eval_id, "run_id": run_id})
        collect_results(
            client, eval_id, run_id, output, args.timeout_seconds,
            plan["expected_conversations"] if plan is not None else args.expected_conversations,
        )


if __name__ == "__main__":
    main()
