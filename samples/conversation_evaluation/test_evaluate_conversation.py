"""Offline lifecycle and request-shape tests; no live-service claims."""

from __future__ import annotations

import asyncio
import copy
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from openai.types.evals.runs.output_item_list_response import Result

import evaluate_conversation as sample

ANSWERS = ("Initial itinerary.", "Revised itinerary without the Louvre.", "Final plan and constraints.")


def completed_response(text: str) -> dict:
    return {
        "type": "response.done",
        "response": {
            "status": "completed",
            "output": [{
                "type": "message", "role": "assistant",
                "content": [{"type": "output_text", "text": text}],
            }],
        },
    }


def connection() -> SimpleNamespace:
    return SimpleNamespace(
        recv=AsyncMock(side_effect=[
            {"type": "session.created"},
            {
                "type": "session.updated",
                "session": {
                    "audio": {"input": {"turn_detection": None}},
                    "output_modalities": ["text"],
                },
            },
            {"type": "response.output_text.delta", "delta": "not a final answer"},
            *[completed_response(text) for text in ANSWERS],
        ]),
        conversation=SimpleNamespace(item=SimpleNamespace(create=AsyncMock())),
        response=SimpleNamespace(create=AsyncMock()),
    )


def result_counts(
    passed: int = 1, failed: int = 0, errored: int = 0, total: int = 1,
) -> SimpleNamespace:
    fields = {"total": total, "passed": passed, "failed": failed, "errored": errored}
    return SimpleNamespace(**fields, model_dump=lambda: fields.copy())


def evaluation_run(status: str = "completed") -> SimpleNamespace:
    return SimpleNamespace(
        id="run-owned", eval_id="eval-owned", status=status,
        result_counts=result_counts(),
        report_url="https://example.invalid/report",
    )


def output_items() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(
            datasource_item_id=index,
            datasource_item={"scenario_id": "test-session", "expected_pass": True},
            results=[Result(name="output_quality", score=4.0, passed=True)],
        )
        for index in range(1)
    ]


def context(value) -> MagicMock:
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=value)
    manager.__aexit__ = AsyncMock(return_value=False)
    return manager


def evaluation_client() -> tuple[MagicMock, SimpleNamespace]:
    async def items(**_kwargs):
        for item in output_items():
            yield item

    runs = SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(id="run-owned")),
        retrieve=AsyncMock(return_value=evaluation_run()),
        cancel=AsyncMock(),
        output_items=SimpleNamespace(list=MagicMock(side_effect=items)),
    )
    client = SimpleNamespace(evals=SimpleNamespace(
        create=AsyncMock(return_value=SimpleNamespace(id="eval-owned")),
        delete=AsyncMock(),
        runs=runs,
    ))
    project = MagicMock()
    project.get_openai_client.return_value = context(client)
    return project, client


CONVERSATION = {"messages": [
    {"role": "system", "content": [{"type": "text", "text": sample.INSTRUCTIONS}]},
    *[
        message
        for question, answer in zip(sample.QUESTIONS, ANSWERS)
        for message in (
            {"role": "user", "content": [{"type": "text", "text": question}]},
            {"role": "assistant", "content": [{"type": "text", "text": answer}]},
        )
    ],
]}
CASE = {
    **CONVERSATION,
    "scenario_id": "test-session",
    "expected_pass": True,
    "failure_injection": None,
}


class ConversationTests(unittest.IsolatedAsyncioTestCase):
    def test_definition_is_native_voice_manual_text_without_persistence(self):
        definition = sample.definition("gpt-realtime").as_dict()
        self.assertEqual(definition["kind"], "voice")
        self.assertEqual(definition["model"], "gpt-realtime")
        self.assertIsNone(definition["audio"]["input"]["turn_detection"])
        self.assertEqual(definition["output_modalities"], ["text"])
        self.assertFalse(definition["store"])

    async def test_three_turns_wait_for_final_replies_and_preserve_all_messages(self):
        conn = connection()

        async def create_response():
            expected_receives = (2, 4, 5)[conn.response.create.await_count - 1]
            self.assertEqual(conn.recv.await_count, expected_receives)

        conn.response.create.side_effect = create_response
        conversation = await sample.converse(conn)
        self.assertEqual(conversation, CONVERSATION)
        self.assertEqual(len(conversation["messages"]), 7)
        messages = conn.conversation.item.create.await_args_list
        self.assertEqual(len(messages), 3)
        self.assertEqual(messages[1].kwargs["item"]["content"], [
            {"type": "input_text", "text": sample.QUESTIONS[1]},
        ])
        self.assertNotEqual(
            messages[0].kwargs["item"]["id"], messages[1].kwargs["item"]["id"],
        )

    async def test_failures_never_create_evaluation_rows(self):
        for event in (
            {"type": "error", "error": {"code": "unsupported_model"}},
            {"type": "response.done", "response": {"status": "failed"}},
            completed_response(" "),
        ):
            with self.subTest(event=event):
                conn = connection()
                ready = {
                    "type": "session.updated",
                    "session": {
                        "audio": {"input": {"turn_detection": None}},
                        "output_modalities": ["text"],
                    },
                }
                conn.recv.side_effect = [ready, event]
                with self.assertRaises(RuntimeError):
                    await sample.converse(conn)
                self.assertEqual(conn.response.create.await_count, 1)
                self.assertEqual(conn.conversation.item.create.await_count, 1)

    async def test_rejects_automatic_responses_and_missing_acknowledgment(self):
        for audio_input in ({}, {"turn_detection": {"type": "server_vad"}}):
            conn = connection()
            conn.recv.side_effect = [{
                "type": "session.updated",
                "session": {
                    "audio": {"input": audio_input},
                    "output_modalities": ["text"],
                },
            }]
            with self.assertRaisesRegex(RuntimeError, "manual text-only"):
                await sample.converse(conn)
            conn.conversation.item.create.assert_not_awaited()

    async def test_silent_connection_times_out(self):
        conn = connection()

        async def stall():
            await asyncio.Event().wait()

        conn.recv = stall
        with patch.object(sample, "TURN_TIMEOUT", 0.01):
            with self.assertRaises(TimeoutError):
                await sample.converse(conn)

    async def test_negative_control_changes_only_final_response_request(self):
        conn = connection()
        scenario = sample.SCENARIOS[2]
        conversation = await sample.converse(conn, scenario)
        requests = conn.response.create.await_args_list
        self.assertEqual(requests[0].kwargs, {})
        self.assertEqual(requests[1].kwargs, {})
        self.assertEqual(requests[2].kwargs, {
            "response": {"instructions": scenario.final_turn_fault},
        })
        self.assertEqual(
            conversation["messages"][0]["content"][0]["text"], scenario.instructions,
        )
        self.assertEqual(conversation["messages"][-1]["content"][0]["text"], ANSWERS[-1])


class EvaluationTests(unittest.IsolatedAsyncioTestCase):
    async def test_conversation_level_criterion_full_messages_and_cleanup(self):
        project, client = evaluation_client()
        with redirect_stdout(io.StringIO()):
            summary = await sample.evaluate(project, [copy.deepcopy(CASE)], "judge", False)
        self.assertEqual(summary["counts"]["total"], 1)
        request = client.evals.create.await_args.kwargs
        self.assertEqual(request["data_source_config"]["type"], "custom")
        self.assertFalse(request["data_source_config"]["include_sample_schema"])
        criterion = request["testing_criteria"][0]
        self.assertEqual(criterion["type"], "azure_ai_evaluator")
        self.assertEqual(criterion["evaluator_name"], "builtin.output_quality")
        self.assertEqual(criterion["data_mapping"], {"messages": "{{item.messages}}"})
        self.assertEqual(criterion["initialization_parameters"], {
            "deployment_name": "judge", "evaluation_level": "conversation",
        })
        self.assertEqual(request["data_source_config"]["item_schema"], {
            "type": "object",
            "properties": {
                "messages": {"type": "array", "items": {"type": "object"}},
                "scenario_id": {"type": "string"},
                "expected_pass": {"type": "boolean"},
                "failure_injection": {"type": ["string", "null"]},
            },
            "required": ["messages", "scenario_id", "expected_pass", "failure_injection"],
        })
        run_request = client.evals.runs.create.await_args.kwargs
        self.assertTrue(run_request["name"].strip())
        self.assertEqual(run_request["extra_body"], {"evaluation_level": "conversation"})
        self.assertEqual(run_request["data_source"], {
            "type": "jsonl",
            "source": {"type": "file_content", "content": [{"item": CASE}]},
        })
        client.evals.runs.output_items.list.assert_called_once_with(
            eval_id="eval-owned", run_id="run-owned",
        )
        client.evals.delete.assert_awaited_once_with(eval_id="eval-owned")
        client.evals.runs.cancel.assert_not_awaited()

    async def test_polls_pending_statuses(self):
        _, client = evaluation_client()
        client.evals.runs.retrieve.side_effect = [
            evaluation_run("queued"), evaluation_run("in_progress"), evaluation_run(),
        ]
        with patch.object(sample, "POLL_INTERVAL", 0):
            run = await sample.wait_for_evaluation(client, "eval-owned", "run-owned")
        self.assertEqual(run.status, "completed")
        self.assertEqual(client.evals.runs.retrieve.await_count, 3)

    async def test_timeout_cancels_run_and_deletes_evaluation(self):
        project, client = evaluation_client()
        client.evals.runs.retrieve.return_value = evaluation_run("in_progress")
        with patch.object(sample, "EVALUATION_TIMEOUT", 0.01):
            with redirect_stdout(io.StringIO()), self.assertRaises(TimeoutError):
                await sample.evaluate(project, [CASE], "judge", False)
        client.evals.runs.cancel.assert_awaited_once_with(
            eval_id="eval-owned", run_id="run-owned",
        )
        client.evals.delete.assert_awaited_once_with(eval_id="eval-owned")

    async def test_cancel_failure_does_not_skip_evaluation_deletion(self):
        project, client = evaluation_client()
        client.evals.runs.retrieve.side_effect = RuntimeError("read failed")
        client.evals.runs.cancel.side_effect = RuntimeError("cancel failed")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "cancel failed"):
            await sample.evaluate(project, [CASE], "judge", False)
        client.evals.delete.assert_awaited_once_with(eval_id="eval-owned")

    async def test_failed_create_still_deletes_evaluation(self):
        project, client = evaluation_client()
        client.evals.runs.create.side_effect = RuntimeError("create run failed")
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "create run"):
            await sample.evaluate(project, [CASE], "judge", False)
        client.evals.delete.assert_awaited_once_with(eval_id="eval-owned")
        client.evals.runs.cancel.assert_not_awaited()

    async def test_terminal_failure_is_not_reported_as_success(self):
        for status in ("failed", "canceled", "cancelled"):
            with self.subTest(status=status):
                project, client = evaluation_client()
                client.evals.runs.retrieve.return_value = evaluation_run(status)
                with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, status):
                    await sample.evaluate(project, [CASE], "judge", False)
                client.evals.delete.assert_awaited_once_with(eval_id="eval-owned")
                client.evals.runs.cancel.assert_not_awaited()

    async def test_keep_resources_does_not_delete_or_cancel(self):
        project, client = evaluation_client()
        with redirect_stdout(io.StringIO()):
            await sample.evaluate(project, [CASE], "judge", True)
        client.evals.delete.assert_not_awaited()
        client.evals.runs.cancel.assert_not_awaited()

    async def test_empty_or_single_turn_conversation_is_rejected_before_service_calls(self):
        project, client = evaluation_client()
        for messages in ([], CONVERSATION["messages"][:3]):
            with self.assertRaises(ValueError):
                await sample.evaluate(project, [{**CASE, "messages": messages}], "judge", False)
        client.evals.create.assert_not_awaited()

    async def test_judge_model_is_required(self):
        project, client = evaluation_client()
        with self.assertRaisesRegex(ValueError, "judge model"):
            await sample.evaluate(project, [CASE], " ", False)
        client.evals.create.assert_not_awaited()

    async def test_empty_or_duplicate_cases_are_rejected(self):
        project, client = evaluation_client()
        for cases in ([], [CASE, CASE]):
            with self.assertRaises(ValueError):
                await sample.evaluate(project, cases, "judge", False)
        client.evals.create.assert_not_awaited()

    async def test_expected_failure_is_not_an_evaluation_error(self):
        project, client = evaluation_client()
        run = evaluation_run()
        run.result_counts = result_counts(passed=0, failed=1)
        client.evals.runs.retrieve.return_value = run

        async def items(**_kwargs):
            item = output_items()[0]
            item.datasource_item["expected_pass"] = False
            item.results = [Result(name="output_quality", score=1, passed=False)]
            yield item

        client.evals.runs.output_items.list.side_effect = items
        with redirect_stdout(io.StringIO()):
            summary = await sample.evaluate(
                project, [{**CASE, "expected_pass": False}], "judge", False,
            )
        self.assertTrue(summary["expectations_match"])
        self.assertEqual(summary["counts"]["errored"], 0)
        self.assertFalse(summary["scores"][0]["actual_pass"])

    def test_rejects_incomplete_errored_duplicate_or_invalid_results(self):
        for defect in ("missing", "duplicate", "errored", "counts", "grader", "nan", "pass"):
            with self.subTest(defect=defect):
                run, outputs = evaluation_run(), output_items()
                expected = 1
                if defect == "missing":
                    outputs.pop()
                elif defect == "duplicate":
                    outputs.append(copy.deepcopy(outputs[0]))
                    run.result_counts = result_counts(passed=2, total=2)
                    expected = 2
                elif defect == "errored":
                    run.result_counts.errored = 1
                elif defect == "counts":
                    run.result_counts.total = 0
                elif defect == "grader":
                    outputs[0].results = []
                elif defect == "nan":
                    outputs[0].results[0].score = float("nan")
                elif defect == "pass":
                    outputs[0].results[0].passed = False
                with self.assertRaises(RuntimeError):
                    sample.summarize(run, outputs, expected)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_agent_cleanup_on_conversation_or_evaluation_failure(self):
        for failing_phase in ("enable", "conversation", "evaluation", "threshold", None):
            with self.subTest(phase=failing_phase):
                agents = SimpleNamespace(
                    create_version=AsyncMock(),
                    enable=AsyncMock(),
                    delete=AsyncMock(),
                )
                project = SimpleNamespace(
                    agents=agents,
                    beta=SimpleNamespace(voice_agents=SimpleNamespace(
                        realtime=SimpleNamespace(connect=MagicMock(
                            return_value=context(connection()),
                        )),
                    )),
                )
                if failing_phase == "enable":
                    agents.enable.side_effect = RuntimeError("enable failed")
                conversation = AsyncMock(return_value=CONVERSATION)
                evaluation = AsyncMock(return_value={
                    "counts": {"failed": 1 if failing_phase == "threshold" else 0},
                    "scores": [],
                    "expectations_match": failing_phase != "threshold",
                })
                if failing_phase == "conversation":
                    conversation.side_effect = RuntimeError("conversation failed")
                elif failing_phase == "evaluation":
                    evaluation.side_effect = RuntimeError("evaluation failed")
                with (
                    patch.object(sample, "DefaultAzureCredential", return_value=context(None)),
                    patch.object(sample, "AIProjectClient", return_value=context(project)),
                    patch.object(sample, "converse", conversation),
                    patch.object(sample, "evaluate", evaluation),
                    redirect_stdout(io.StringIO()),
                ):
                    if failing_phase:
                        with self.assertRaises(RuntimeError):
                            await sample.run("https://example.invalid", "gpt-realtime", "judge")
                    else:
                        await sample.run("https://example.invalid", "gpt-realtime", "judge")
                name = agents.create_version.await_args.kwargs["agent_name"]
                self.assertEqual(agents.delete.await_count, agents.create_version.await_count)
                self.assertEqual(agents.delete.await_args.kwargs["agent_name"], name)
                if failing_phase in {"enable", "conversation"}:
                    evaluation.assert_not_awaited()
                else:
                    cases = evaluation.await_args.args[1]
                    self.assertEqual(len(cases), 4)
                    self.assertEqual(
                        [case["expected_pass"] for case in cases], [True, True, False, False],
                    )
                    self.assertTrue(all(case["messages"] == CONVERSATION["messages"] for case in cases))
                    self.assertEqual(
                        [call.args[1].name for call in conversation.await_args_list],
                        [scenario.name for scenario in sample.SCENARIOS],
                    )
                    self.assertEqual(evaluation.await_args.args[2], "judge")

    async def test_mismatched_outcomes_are_saved_before_failure(self):
        agents = SimpleNamespace(
            create_version=AsyncMock(), enable=AsyncMock(), delete=AsyncMock(),
        )
        project = SimpleNamespace(
            agents=agents,
            beta=SimpleNamespace(voice_agents=SimpleNamespace(
                realtime=SimpleNamespace(connect=MagicMock(return_value=context(connection()))),
            )),
        )
        summary = {
            "counts": {"passed": 3, "failed": 1, "errored": 0, "total": 4},
            "scores": [{
                "scenario_id": scenario.name,
                "expected_pass": scenario.expected_pass,
                "actual_pass": True,
                "results": [],
            } for scenario in sample.SCENARIOS],
            "expectations_match": False,
        }
        with (
            tempfile.TemporaryDirectory() as directory,
            patch.object(sample, "DefaultAzureCredential", return_value=context(None)),
            patch.object(sample, "AIProjectClient", return_value=context(project)),
            patch.object(sample, "converse", AsyncMock(return_value=CONVERSATION)),
            patch.object(sample, "evaluate", AsyncMock(return_value=summary)),
            redirect_stdout(io.StringIO()),
        ):
            output = Path(directory) / "nested" / "evidence.json"
            with self.assertRaisesRegex(RuntimeError, "did not match"):
                await sample.run(
                    "https://example.invalid", "gpt-realtime", "judge", output=output,
                )
            evidence = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(evidence["evaluation"], summary)
            self.assertEqual(len(evidence["conversations"]), 4)
            self.assertEqual(
                evidence["conversations"][2]["failure_injection"],
                sample.SCENARIOS[2].final_turn_fault,
            )
        self.assertEqual(agents.delete.await_count, 4)


if __name__ == "__main__":
    unittest.main()
