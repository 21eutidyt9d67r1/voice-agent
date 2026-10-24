"""Offline contracts with real Projects/OpenAI clients and synthetic HTTP responses."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

import httpx2
from azure.ai.projects import AIProjectClient
from azure.core.credentials import AccessToken
from openai import InternalServerError, OpenAI


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "simulation_sample", ROOT / "samples" / "simulation_evaluation" / "simulate.py"
)
sample = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sample)
ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"
ENV = {
    "AZURE_AI_PROJECT_ENDPOINT": ENDPOINT,
    "FOUNDRY_AGENT_NAME": "appointment-test",
    "FOUNDRY_AGENT_VERSION": "2",
    "AZURE_AI_SIMULATOR_MODEL": "sample-connection/simulator",
    "AZURE_AI_MODEL_DEPLOYMENT_NAME": "judge",
}


def run_payload(status="completed", total=2, failed=0, errored=0):
    return {
        "id": "run_1",
        "eval_id": "eval_1",
        "status": status,
        "error": {"code": "synthetic", "message": "Synthetic service failure"} if status == "failed" else None,
        "report_url": "https://example.invalid/synthetic-report",
        "result_counts": {
            "total": total,
            "passed": total - failed - errored,
            "failed": failed,
            "errored": errored,
        },
        "output_datasets": [{
            "type": "simulated_user_conversations",
            "dataset": {"id": "dataset_1", "name": "synthetic", "version": "1"},
        }],
    }


def output_item(number=1, status="pass"):
    return {
        "id": f"item_{number}",
        "status": status,
        "datasource_item": {"messages": [
            {"role": "user", "content": "Synthetic generated question"},
            {"role": "assistant", "content": "Synthetic agent reply"},
        ]},
        "results": [
            {"name": name, "passed": status == "pass", "score": 4.0}
            for name in ("task_completion", "coherence")
        ],
    }


class OfflineCredential:
    def get_token(self, *args, **kwargs):
        return AccessToken("offline-test-token", 4102444800)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass


class SimulationTests(unittest.TestCase):
    def setUp(self):
        self.environment = patch.dict(os.environ, ENV, clear=True)
        self.environment.start()
        self.addCleanup(self.environment.stop)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.output = Path(self.temp.name)
        self.requests = []

    def plan(self, *args):
        return sample.build_requests(sample.parser().parse_args(["plan", *args]))

    def client(self, handler):
        def record(request):
            self.requests.append(request)
            return handler(request)

        client = OpenAI(
            api_key="offline-test-token",
            base_url=f"{ENDPOINT}/openai",
            default_query={"api-version": sample.API_VERSION},
            http_client=httpx2.Client(transport=httpx2.MockTransport(record)),
            max_retries=0,
        )
        self.addCleanup(client.close)
        return client

    def test_scenarios_are_goals_not_fixed_turn_scripts(self):
        plan = self.plan()
        source = plan["run"]["data_source"]["source"]
        self.assertEqual(source["type"], "inline_user_conversation_simulation")
        self.assertEqual(len(source["test_cases"]), 2)
        self.assertEqual(plan["expected_conversations"], 2)
        for row in source["test_cases"]:
            self.assertEqual(set(row), {"test_case_id", "test_case_description"})
        self.assertNotIn("voice_model", plan["run"]["data_source"]["model_configuration"])

    def test_voice_and_repetition_configuration(self):
        plan = self.plan("--voice-name", "en-US-AvaMultilingualNeural", "--repetitions", "2")
        self.assertEqual(plan["mode"], "voice")
        self.assertEqual(plan["expected_conversations"], 4)
        self.assertEqual(plan["run"]["data_source"]["model_configuration"]["voice_model"], {
            "type": "azure-standard", "name": "en-US-AvaMultilingualNeural",
        })

    def test_exact_conversation_evaluator_mapping_and_pinned_target(self):
        plan = self.plan()
        self.assertEqual(plan["run"]["evaluation_level"], "conversation")
        self.assertEqual(plan["run"]["data_source"]["target"], {
            "type": "azure_ai_agent", "name": "appointment-test", "version": "2",
        })
        for criterion in plan["evaluation"]["testing_criteria"]:
            self.assertEqual(criterion["data_mapping"], {"messages": "{{item.messages}}"})
            self.assertEqual(criterion["initialization_parameters"], {"model": "judge"})

    def test_plan_has_no_cloud_calls_or_local_result_files(self):
        with patch("azure.identity.DefaultAzureCredential") as credential, redirect_stdout(io.StringIO()) as stdout:
            sample.main(["plan"])
        credential.assert_not_called()
        self.assertEqual(json.loads(stdout.getvalue()), self.plan())
        self.assertEqual(list(self.output.iterdir()), [])

    def test_required_configuration_is_not_defaulted(self):
        for name in ENV:
            with self.subTest(name=name), patch.dict(os.environ, {name: ""}):
                with self.assertRaisesRegex(ValueError, name):
                    self.plan()

    def test_rejects_untrusted_project_endpoints(self):
        for endpoint in (
            "http://sample.services.ai.azure.com/api/projects/sample",
            "https://sample.services.ai.azure.com.attacker.invalid/api/projects/sample",
            f"{ENDPOINT}?token=secret",
            f"{ENDPOINT}#fragment",
            "https://user:secret@sample.services.ai.azure.com/api/projects/sample",
            "https://sample.services.ai.azure.com:443/api/projects/sample",
        ):
            with self.subTest(endpoint=endpoint), patch.dict(os.environ, {"AZURE_AI_PROJECT_ENDPOINT": endpoint}):
                with self.assertRaises(ValueError):
                    self.plan()

    def test_rejects_latest_version_and_invalid_simulator(self):
        for name, value in (
            ("FOUNDRY_AGENT_VERSION", "latest"),
            ("FOUNDRY_AGENT_NAME", "../agent"),
            ("AZURE_AI_SIMULATOR_MODEL", "connection/too/many/parts"),
            ("AZURE_AI_SIMULATOR_MODEL", "connection/<deployment>"),
        ):
            with self.subTest(name=name), patch.dict(os.environ, {name: value}):
                with self.assertRaises(ValueError):
                    self.plan()

    def test_existing_project_deployment_can_be_simulator(self):
        with patch.dict(os.environ, {"AZURE_AI_SIMULATOR_MODEL": "gpt-5-mini"}):
            plan = self.plan()
        self.assertEqual(
            plan["run"]["data_source"]["model_configuration"]["model"], "gpt-5-mini"
        )

    def test_rejects_nonfinite_timeouts_and_unbounded_turns(self):
        for args in (
            ["submit", "--timeout-seconds", "nan"],
            ["submit", "--timeout-seconds", "inf"],
            ["submit", "--timeout-seconds", "0"],
            ["plan", "--max-turns", "21"],
            ["plan", "--repetitions", "0"],
        ):
            with self.subTest(args=args), redirect_stdout(io.StringIO()), patch("sys.stderr", io.StringIO()):
                with self.assertRaises(SystemExit):
                    sample.parser().parse_args(args)

    def test_scenario_validation(self):
        path = self.output / "scenarios.jsonl"
        good = {"test_case_id": "one", "test_case_description": "Fictional goal"}
        for rows in (
            "",
            "{bad json",
            "[]",
            json.dumps({**good, "messages": []}),
            json.dumps({**good, "test_case_description": ""}),
            json.dumps({**good, "test_case_description": "x" * 2501}),
            json.dumps(good) + "\n" + json.dumps(good),
        ):
            with self.subTest(rows=rows[:60]):
                path.write_text(rows, encoding="utf-8")
                with self.assertRaises(ValueError):
                    sample.load_scenarios(path)

    def test_conversation_budget(self):
        path = self.output / "scenarios.jsonl"
        path.write_text("\n".join(json.dumps({
            "test_case_id": f"case-{i}", "test_case_description": "Fictional goal",
        }) for i in range(5)), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "at most 20"):
            self.plan("--scenarios", str(path), "--repetitions", "5")

    def test_real_projects_and_openai_sdk_submit_contract(self):
        def handler(request):
            if request.url.path.endswith("/runs"):
                return httpx2.Response(200, json=run_payload())
            return httpx2.Response(200, json={"id": "eval_1"})

        client = self.client(handler)
        http_client = client._client
        real_factory = AIProjectClient.get_openai_client

        def factory(project, **kwargs):
            self.assertEqual(kwargs["base_url"], f"{ENDPOINT}/openai")
            self.assertEqual(kwargs["default_query"], {"api-version": sample.API_VERSION})
            self.assertEqual(kwargs["max_retries"], 0)
            return real_factory(project, http_client=http_client, **kwargs)

        with (
            patch("azure.identity.DefaultAzureCredential", return_value=OfflineCredential()),
            patch.object(AIProjectClient, "get_openai_client", factory),
            patch.object(sample, "collect_results"),
            redirect_stdout(io.StringIO()),
        ):
            sample.main(["submit", "--output", str(self.output / "run")])
        self.assertEqual(len(self.requests), 2)
        plan = self.plan()
        self.assertEqual(json.loads(self.requests[0].content), plan["evaluation"])
        self.assertEqual(json.loads(self.requests[1].content), plan["run"])
        for request in self.requests:
            self.assertEqual(request.url.params["api-version"], sample.API_VERSION)
            self.assertEqual(request.headers["authorization"], "Bearer offline-test-token")
        receipt = json.loads((self.output / "run" / "receipt.json").read_text())
        self.assertEqual(receipt, {"eval_id": "eval_1", "run_id": "run_1"})

    def test_run_submission_error_is_not_retried_and_preserves_eval_id(self):
        def handler(request):
            if request.url.path.endswith("/runs"):
                return httpx2.Response(503, json={"error": {"message": "Synthetic unavailable"}})
            return httpx2.Response(200, json={"id": "eval_1"})

        with self.assertRaises(InternalServerError), redirect_stdout(io.StringIO()):
            sample.submit(self.client(handler), self.plan(), self.output)
        self.assertEqual(len(self.requests), 2)
        self.assertEqual(json.loads((self.output / "receipt.json").read_text()), {
            "eval_id": "eval_1", "run_id": None,
        })

    def collect(self, payload=None, items=None, expected=2):
        payload = payload if payload is not None else run_payload()
        items = items if items is not None else [output_item(1), output_item(2)]

        def handler(request):
            if request.url.path.endswith("/output_items"):
                return httpx2.Response(200, json={"data": items, "has_more": False})
            return httpx2.Response(200, json=payload)

        with redirect_stdout(io.StringIO()):
            sample.collect_results(self.client(handler), "eval_1", "run_1", self.output, 60, expected)

    def test_completed_run_preserves_scores_and_generated_dataset_reference(self):
        self.collect()
        self.assertEqual(json.loads((self.output / "output_items.json").read_text()), [output_item(1), output_item(2)])
        self.assertEqual(json.loads((self.output / "run.json").read_text())["output_datasets"], run_payload()["output_datasets"])

    def test_cloud_completed_item_status_requires_passing_judges(self):
        item = output_item(1)
        item["status"] = "completed"
        self.collect(payload=run_payload(total=1), items=[item], expected=1)
        item["results"][0]["passed"] = False
        with self.assertRaisesRegex(RuntimeError, "scores"):
            self.collect(payload=run_payload(total=1), items=[item], expected=1)

    def test_paginates_all_output_items(self):
        def handler(request):
            if not request.url.path.endswith("/output_items"):
                return httpx2.Response(200, json=run_payload())
            second_page = request.url.params.get("after") == "item_1"
            return httpx2.Response(200, json={
                "data": [output_item(2 if second_page else 1)],
                "has_more": not second_page,
                "first_id": "item_2" if second_page else "item_1",
                "last_id": "item_2" if second_page else "item_1",
            })

        sample.collect_results(self.client(handler), "eval_1", "run_1", self.output, 60, 2)
        self.assertEqual(len(self.requests), 3)
        self.assertEqual(len(json.loads((self.output / "output_items.json").read_text())), 2)

    def test_failed_and_canceled_runs_surface_error_without_fetching_scores(self):
        for status in ("failed", "canceled"):
            with self.subTest(status=status), self.assertRaisesRegex(RuntimeError, status):
                self.collect(payload=run_payload(status))
        self.assertEqual(len(self.requests), 2)

    def test_completed_is_not_a_passing_score(self):
        with self.assertRaisesRegex(RuntimeError, "did not pass"):
            self.collect(payload=run_payload(failed=1), items=[output_item(1, "fail"), output_item(2)])
        self.assertTrue((self.output / "output_items.json").is_file())

    def test_rejects_missing_partial_or_errored_results(self):
        cases = [
            (run_payload(), []),
            (run_payload(errored=1), [output_item(1), output_item(2, "error")]),
            (run_payload(total=1), [output_item(1)]),
            (run_payload(), [output_item(1)]),
            (run_payload(total=0), []),
        ]
        for payload, items in cases:
            with self.subTest(payload=payload), self.assertRaises(RuntimeError):
                self.collect(payload=payload, items=items)

    def test_rejects_missing_or_failing_evaluator_results_even_on_pass_item(self):
        for results in ([], [{"name": "coherence", "passed": True, "score": 4.0}]):
            item = output_item(1)
            item["results"] = results
            with self.subTest(results=results), self.assertRaisesRegex(RuntimeError, "scores"):
                self.collect(items=[item, output_item(2)])

    def test_timeout_preserves_run_and_does_not_cancel_or_resubmit(self):
        with patch.object(sample.time, "monotonic", side_effect=[0, 61]):
            with self.assertRaisesRegex(TimeoutError, "NOT canceled"):
                self.collect(payload=run_payload("in_progress"))
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0].method, "GET")
        self.assertTrue((self.output / "run.json").is_file())

    def test_results_resumes_without_simulation_configuration_or_new_submission(self):
        with (
            patch.dict(os.environ, {"AZURE_AI_PROJECT_ENDPOINT": ENDPOINT}, clear=True),
            patch("azure.identity.DefaultAzureCredential", return_value=OfflineCredential()),
            patch.object(AIProjectClient, "get_openai_client", return_value=self.client(
                lambda request: httpx2.Response(200, json=run_payload())
            )),
            patch.object(sample, "collect_results") as collect,
            patch.object(sample, "submit") as submit,
            redirect_stdout(io.StringIO()),
        ):
            sample.main([
                "results", "--eval-id", "eval_1", "--run-id", "run_1",
                "--expected-conversations", "2", "--output", str(self.output / "resume"),
            ])
        submit.assert_not_called()
        self.assertEqual(collect.call_args.args[1:3], ("eval_1", "run_1"))
        self.assertEqual(collect.call_args.args[-1], 2)

    def test_existing_output_directory_is_not_overwritten(self):
        with patch("azure.identity.DefaultAzureCredential") as credential:
            with self.assertRaises(FileExistsError):
                sample.main(["submit", "--output", str(self.output)])
        credential.assert_not_called()


if __name__ == "__main__":
    unittest.main()
