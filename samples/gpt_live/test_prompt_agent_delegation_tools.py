"""Offline tool/lifecycle/SDK tests; no Azure resources or physical audio devices."""

import asyncio
import base64
import contextlib
import io
import json
import os
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from azure.ai.projects.models import PromptAgentDefinition
from azure.core.credentials import AccessToken
from openai import AsyncOpenAI
from websockets.asyncio.server import serve

import prompt_agent_delegation as managed
import prompt_agent_delegation_tools as sample
from response_delegation import DemoError, converse


def function_call(call_id="call-1", **overrides):
    return {
        "type": "function_call",
        "call_id": call_id,
        "name": sample.DATETIME_TOOL_NAME,
        "arguments": "{}",
        **overrides,
    }


def envelope(kind, **fields):
    return SimpleNamespace(type=kind, **fields)


def backend(kind, delegation_id="delegation-1", **fields):
    return envelope(
        "response.event",
        delegation_id=delegation_id,
        event={"type": kind, **fields},
    )


class PayloadTests(unittest.TestCase):
    def test_prompt_tools_match_released_projects_sdk(self):
        payload = sample.prompt_agent_payload("tools-prompt", "text-model")
        definition = payload["definition"]
        self.assertEqual(PromptAgentDefinition(definition).as_dict(), definition)
        mcp, clock = definition["tools"]
        self.assertEqual(mcp["server_url"], sample.MCP_SERVER_URL)
        self.assertEqual(mcp["allowed_tools"], ["add"])
        self.assertEqual(mcp["require_approval"], "never")
        self.assertNotIn("headers", mcp)
        self.assertNotIn("authorization", mcp)
        self.assertEqual(clock["name"], sample.DATETIME_TOOL_NAME)
        self.assertTrue(clock["strict"])
        self.assertEqual(
            clock["parameters"],
            {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
        )
        self.assertEqual(definition["text"], {"format": {"type": "text"}})
        self.assertIn("[commentary]", definition["instructions"])

    def test_voice_retains_pinned_managed_reference(self):
        definition = sample.voice_agent_payload("voice", "live", "prompt", "7")["definition"]
        self.assertEqual(
            definition["delegation"],
            {"type": "foundry_managed_agent", "agent_name": "prompt", "agent_version": "7"},
        )
        self.assertTrue(definition["store"])
        self.assertIn("current-date/time", definition["instructions"])
        self.assertNotIn("tools", managed.prompt_agent_payload("plain", "text")["definition"])

    def test_datetime_is_one_instant_with_explicit_offsets(self):
        before = datetime.now(timezone.utc).replace(microsecond=0)
        result = sample.get_current_datetime()
        after = datetime.now(timezone.utc)
        local = datetime.fromisoformat(result["local_datetime"])
        utc = datetime.fromisoformat(result["utc_datetime"])
        self.assertIsNotNone(local.utcoffset())
        self.assertEqual(utc.utcoffset().total_seconds(), 0)
        self.assertEqual(local, utc)
        self.assertLessEqual(before, utc)
        self.assertLessEqual(utc, after)
        self.assertTrue(result["timezone"])

    def test_allowed_function_executes_once(self):
        with patch.object(sample, "get_current_datetime", return_value={"clock": "test"}) as clock:
            self.assertEqual(json.loads(sample.execute_function(function_call())), {"clock": "test"})
        clock.assert_called_once_with()

    def test_invalid_arguments_do_not_read_clock(self):
        for arguments in ("", "{", "null", "[]", "0", "false", '"{}"', '{"timezone":"UTC"}', None):
            with self.subTest(arguments=arguments):
                with patch.object(sample, "get_current_datetime") as clock:
                    output = json.loads(sample.execute_function(function_call(arguments=arguments)))
                self.assertEqual(output["error"], "invalid_arguments")
                clock.assert_not_called()

    def test_unknown_function_is_not_executed(self):
        with patch.object(sample, "get_current_datetime") as clock:
            output = json.loads(sample.execute_function(function_call(name="os.system")))
        self.assertEqual(output["error"], "unknown_function")
        clock.assert_not_called()


class ToolHandlerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.handler = sample.ManagedToolHandler()
        self.sent = []

        async def send_item(**kwargs):
            self.sent.append(("item", kwargs["item"]))

        async def resume(**kwargs):
            self.sent.append(("resume", kwargs))

        self.connection = SimpleNamespace(
            response=SimpleNamespace(
                item=SimpleNamespace(create=AsyncMock(side_effect=send_item)),
                create=AsyncMock(side_effect=resume),
            )
        )
        self.transcript = MagicMock()
        await self.created()

    async def observe(self, event):
        await self.handler(self.connection, event, self.transcript)

    async def created(self, response_id="response-1", delegation_id="delegation-1"):
        await self.observe(backend(
            "response.created", delegation_id, response={"id": response_id, "status": "in_progress"}
        ))

    async def done(self, call=None, delegation_id="delegation-1", **fields):
        await self.observe(backend(
            "response.output_item.done", delegation_id,
            item=function_call() if call is None else call, **fields,
        ))

    async def completed(self, response_id="response-1", delegation_id="delegation-1"):
        # The service strips lifecycle output. Calls must come from item.done.
        await self.observe(backend(
            "response.completed", delegation_id,
            response={"id": response_id, "status": "completed", "output": []},
        ))

    async def test_waits_for_terminal_response_then_returns_function_output(self):
        await self.done()
        self.assertEqual(self.sent, [])
        await self.completed()
        self.assertEqual([kind for kind, _ in self.sent], ["item", "resume"])
        item = self.sent[0][1]
        self.assertEqual(item["type"], "function_call_output")
        self.assertEqual(item["call_id"], "call-1")
        self.assertIn("utc_datetime", json.loads(item["output"]))

    async def test_parallel_outputs_precede_one_continuation(self):
        await self.done(function_call("call-1"))
        await self.done(function_call("call-2"))
        await self.completed()
        self.assertEqual([kind for kind, _ in self.sent], ["item", "item", "resume"])
        self.assertEqual([item["call_id"] for kind, item in self.sent if kind == "item"], ["call-1", "call-2"])

    async def test_duplicate_events_do_not_reexecute_or_resume(self):
        with patch.object(sample, "get_current_datetime", return_value={"clock": "once"}) as clock:
            await self.done()
            await self.done()
            await self.completed()
            await self.done()
            await self.completed()
        clock.assert_called_once_with()
        self.connection.response.create.assert_awaited_once_with()

    async def test_multiple_backend_rounds_keep_the_same_delegation(self):
        await self.done()
        await self.completed()
        await self.created("response-2")
        await self.done(function_call("call-2"))
        await self.completed("response-2")
        self.assertEqual([kind for kind, _ in self.sent], ["item", "resume", "item", "resume"])

    async def test_server_mcp_tools_and_partial_function_arguments_are_not_executed(self):
        with patch.object(sample, "get_current_datetime") as clock:
            for tool_type in ("mcp_call", "mcp_list_tools", "message"):
                await self.done({"type": tool_type, "output": "Not a local function."})
            await self.observe(backend("response.function_call_arguments.delta", delta="{}"))
            await self.completed()
        clock.assert_not_called()
        self.assertEqual(self.sent, [])

    async def test_invalid_and_unknown_calls_return_errors_without_executing(self):
        with patch.object(sample, "get_current_datetime") as clock:
            await self.done(function_call(arguments="not json"))
            await self.done(function_call("call-2", name="not_allowed"))
            await self.completed()
        clock.assert_not_called()
        errors = [json.loads(item["output"])["error"] for kind, item in self.sent if kind == "item"]
        self.assertEqual(errors, ["invalid_arguments", "unknown_function"])
        self.connection.response.create.assert_awaited_once_with()

    async def test_failed_backend_responses_never_execute_pending_calls(self):
        for index, phase in enumerate(("failed", "incomplete", "cancelled")):
            response_id = f"response-{phase}"
            await self.created(response_id)
            await self.done(function_call(f"call-{index}"))
            await self.observe(backend(f"response.{phase}", response={"id": response_id}))
            await self.completed(response_id)
        self.assertEqual(self.sent, [])

    async def test_finished_delegations_discard_pending_and_stale_events(self):
        for index, phase in enumerate(("completed", "failed")):
            delegation_id = f"delegation-{phase}"
            await self.created(f"response-{index}", delegation_id)
            await self.done(function_call(f"call-{index}"), delegation_id)
            await self.observe(envelope(f"session.managed_delegation.{phase}", delegation_id=delegation_id))
            await self.created(f"response-{index}", delegation_id)
            await self.done(function_call(f"call-{index}"), delegation_id)
            await self.completed(f"response-{index}", delegation_id)
        self.assertEqual(self.sent, [])
        self.assertFalse(self.handler.pending)

    async def test_delegations_do_not_share_pending_calls(self):
        await self.done()
        await self.created("other-response", "other-delegation")
        await self.completed("other-response", "other-delegation")
        self.assertEqual(self.sent, [])
        await self.completed()
        self.assertEqual(len(self.sent), 2)

    async def test_uncorrelated_events_are_ignored(self):
        await self.done(delegation_id=None)
        await self.completed()
        self.assertEqual(self.sent, [])

    async def test_missing_response_id_is_rejected(self):
        with self.assertRaisesRegex(DemoError, "correlated response"):
            await self.done(delegation_id="no-response")

    async def test_changed_call_is_rejected(self):
        await self.done()
        with self.assertRaisesRegex(DemoError, "changed"):
            await self.done(function_call(arguments='{"unexpected":true}'))
        self.assertEqual(self.sent, [])

    async def test_reused_call_id_is_rejected(self):
        await self.done()
        await self.completed()
        await self.created("response-2")
        with self.assertRaisesRegex(DemoError, "reused"):
            await self.done()


class OfflineCredential:
    async def get_token(self, *scopes, **kwargs):
        return AccessToken("offline-test-token", 4102444800)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def run_lifecycle(
        self, *, fail_voice=False, auto_delete=True,
        main_function=sample.main, session_events=None,
    ):
        self.requests = []
        self.created_payloads = []
        self.deleted = []

        def handle(request):
            self.requests.append((request.method, request.url.path))
            path = request.url.path
            if request.method == "GET" and "/deployments/" in path:
                return httpx.Response(200, json={"name": path.rsplit("/", 1)[-1]})
            if request.method == "POST":
                payload = json.loads(request.content)
                if payload["definition"]["kind"] == "voice" and fail_voice:
                    return httpx.Response(400, json={"error": {"code": "test_failure"}})
                self.created_payloads.append(payload)
                version = "7" if payload["definition"]["kind"] == "prompt" else "3"
                return httpx.Response(200, json={"versions": {"latest": {"version": version}}})
            if request.method == "GET" and "/versions/" in path:
                return httpx.Response(200, json={"definition": self.created_payloads[-1]["definition"]})
            if request.method == "DELETE":
                self.deleted.append(path.rsplit("/", 1)[-1])
                return httpx.Response(204)
            raise AssertionError(f"Unexpected request: {request.method} {path}")

        client_class = httpx.AsyncClient

        def make_client(**kwargs):
            return client_class(**kwargs, transport=httpx.MockTransport(handle))

        audio_factory = MagicMock(side_effect=AssertionError("Opened physical audio"))
        sdk_factory = MagicMock(side_effect=AssertionError("Opened a real Live session"))
        self.transcript = MagicMock()
        self.transcript.stop_requested = asyncio.Event()
        self.transcript.__aenter__.return_value = self.transcript
        if session_events is not None:
            self.audio = OfflineAudio()
            audio_factory = MagicMock(return_value=contextlib.nullcontext(self.audio))
            self.connection = MagicMock()

            async def stream():
                for event in session_events:
                    yield event

            self.connection.__aiter__.side_effect = stream
            self.connection.session.input_audio.append = AsyncMock()
            self.connection.session.close = AsyncMock()
            sdk = MagicMock()
            sdk.__aenter__.return_value = sdk
            sdk.live.connect.return_value.__aenter__.return_value = self.connection
            sdk_factory = MagicMock(return_value=sdk)

        with (
            patch.dict(os.environ, {
                "FOUNDRY_PROJECT_ENDPOINT": "https://sample.services.ai.azure.com/api/projects/test",
                "GPT_LIVE_DEPLOYMENT": "live-model",
                "RESPONSE_DELEGATION_DEPLOYMENT": "text-model",
            }),
            patch.object(managed, "project_credential", return_value=OfflineCredential()),
            patch.object(managed.httpx, "AsyncClient", side_effect=make_client),
            patch.object(managed, "Audio", audio_factory),
            patch.object(managed, "AsyncOpenAI", sdk_factory),
            patch.object(managed, "TranscriptDisplay", return_value=self.transcript),
            contextlib.redirect_stdout(io.StringIO()),
        ):
            await main_function(
                create_only=session_events is None, auto_delete=auto_delete
            )

    async def test_create_only_keeps_tool_agents_and_pins_returned_version(self):
        await self.run_lifecycle(auto_delete=False)
        self.assertEqual(self.deleted, [])
        prompt, voice = self.created_payloads
        self.assertEqual(len(prompt["definition"]["tools"]), 2)
        self.assertEqual(
            voice["definition"]["delegation"],
            {"type": "foundry_managed_agent", "agent_name": prompt["name"], "agent_version": "7"},
        )
        self.assertTrue(all(method == "GET" for method, _ in self.requests[:2]))

    async def test_cleanup_deletes_voice_before_prompt(self):
        await self.run_lifecycle()
        self.assertEqual(self.deleted, [payload["name"] for payload in reversed(self.created_payloads)])

    async def test_failed_voice_creation_cleans_only_created_prompt(self):
        with self.assertRaisesRegex(DemoError, "HTTP 400"):
            await self.run_lifecycle(fail_voice=True)
        self.assertEqual(len(self.created_payloads), 1)
        self.assertEqual(self.deleted, [self.created_payloads[0]["name"]])

    async def test_original_managed_sample_retains_plain_prompt_and_cleanup(self):
        await self.run_lifecycle(main_function=managed.main)
        prompt, voice = self.created_payloads
        self.assertNotIn("tools", prompt["definition"])
        self.assertEqual(prompt["definition"]["instructions"], managed.PROMPT_INSTRUCTIONS)
        self.assertEqual(voice["definition"]["delegation"]["agent_version"], "7")
        self.assertEqual(self.deleted, [voice["name"], prompt["name"]])

    async def test_original_main_handles_managed_notice_and_finishes_normal_session(self):
        await self.run_lifecycle(main_function=managed.main, session_events=[
            envelope(
                "session.started",
                conversation_id="conversation-original",
                session=SimpleNamespace(
                    id="session-original",
                    audio=SimpleNamespace(format=SimpleNamespace(type="audio/pcm", rate=24000)),
                ),
            ),
            envelope(
                "session.delegation.created",
                delegation=SimpleNamespace(
                    id="delegation-original", target="foundry_managed_agent"
                ),
            ),
            envelope(
                "session.managed_delegation.completed",
                delegation_id="delegation-original",
                spoken_text='Say "I went to school yesterday."',
                background_context="The past tense of go is went.",
            ),
            envelope("session.output_transcript.delta", delta="I went to school yesterday."),
            envelope(
                "session.closed",
                reason="client_request",
                usage=SimpleNamespace(seconds=1),
            ),
        ])
        self.assertIn("Prompt agent delegation requested", str(self.transcript.mock_calls))
        self.assertIn("[commentary]", str(self.transcript.mock_calls))
        self.transcript.append_agent.assert_called_once_with("I went to school yesterday.")
        self.connection.response.create.assert_not_called()
        self.connection.response.item.create.assert_not_called()
        self.connection.session.commentary.append.assert_not_called()
        self.assertTrue(self.audio.started)
        self.assertTrue(self.audio.stopped)
        prompt, voice = self.created_payloads
        self.assertNotIn("tools", prompt["definition"])
        self.assertEqual(self.deleted, [voice["name"], prompt["name"]])


class OfflineAudio:
    def __init__(self):
        self.started = False
        self.stopped = False
        self.played = []

    def start(self):
        self.started = True

    async def frames(self, stop):
        yield bytes(48)
        await stop.wait()

    def play(self, pcm):
        self.played.append(pcm)

    def stop_microphone(self):
        self.stopped = True

    async def drain(self):
        pass


class SDKLoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_live_sdk_routes_tool_output_and_only_displays_accepted_guidance(self):
        async def exchange(socket):
            async def send(kind, **fields):
                await socket.send(json.dumps({"type": kind, **fields}))

            async def send_backend(kind, **fields):
                await send("response.event", delegation_id="delegation-1", event={"type": kind, **fields})

            await send("session.started", conversation_id="conversation-offline", session={
                "id": "session-offline",
                "audio": {"format": {"type": "audio/pcm", "rate": 24000}},
            })
            await send(
                "session.delegation.created",
                event_id="event-delegation-1",
                offset_ms=1000,
                delegation={
                    "id": "delegation-1",
                    "type": "delegation",
                    "target": "foundry_managed_agent",
                },
            )
            await send_backend("response.created", response={"id": "response-1", "status": "in_progress"})
            await send_backend("response.output_item.done", item=function_call())
            await send_backend("response.completed", response={"id": "response-1", "status": "completed", "output": []})
            commands = []
            async for raw in socket:
                message = json.loads(raw)
                if message["type"].startswith("response."):
                    commands.append(message)
                if message["type"] == "response.create":
                    break
            self.assertEqual([command["type"] for command in commands], ["response.item.create", "response.create"])
            output = commands[0]["item"]
            self.assertEqual(output["call_id"], "call-1")
            self.assertIn("utc_datetime", json.loads(output["output"]))
            await send_backend("response.output_item.done", item={
                "type": "message", "content": [{"type": "output_text", "text": "UNVALIDATED_BACKEND_TEXT"}],
            })
            await send("session.managed_delegation.completed",
                       delegation_id="delegation-1", spoken_text="The clock was checked.", background_context="")
            await send("session.output_transcript.delta", delta="The clock was checked.")
            await send("session.output_audio.delta", delta=base64.b64encode(bytes(48)).decode("ascii"))
            await send("session.closed", reason="client_request", usage={"seconds": 1})

        async with serve(exchange, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            audio = OfflineAudio()
            transcript = MagicMock()
            transcript.stop_requested = asyncio.Event()
            async with AsyncOpenAI(
                api_key="offline-test-token", base_url=f"http://127.0.0.1:{port}/v1", max_retries=0
            ) as client:
                async with client.live.connect() as connection:
                    async with asyncio.timeout(10):
                        conversation_id = await converse(
                            connection, audio, transcript, "tools-prompt:7",
                            managed_delegation=True, event_handler=sample.ManagedToolHandler(),
                        )
        self.assertEqual(conversation_id, "conversation-offline")
        self.assertTrue(audio.started)
        self.assertTrue(audio.stopped)
        self.assertEqual(audio.played, [bytes(48)])
        transcript.append_agent.assert_called_once_with("The clock was checked.")
        self.assertNotIn("UNVALIDATED_BACKEND_TEXT", str(transcript.mock_calls))
        self.assertIn("[commentary] The clock was checked.", str(transcript.mock_calls))
        self.assertIn("Prompt agent delegation requested", str(transcript.mock_calls))

    async def check_delegation_notice(self, target):
        """Exercise the notice with the real SDK and no local tool handler."""
        received = []

        async def exchange(socket):
            await socket.send(json.dumps({
                "type": "session.started",
                "session": {
                    "id": "session-notice",
                    "audio": {"format": {"type": "audio/pcm", "rate": 24000}},
                },
            }))
            await socket.send(json.dumps({
                "type": "session.delegation.created",
                "offset_ms": 1000,
                "delegation": {"id": "delegation-notice", "target": target},
            }))
            await socket.send(json.dumps({
                "type": "session.closed",
                "reason": "client_request",
                "usage": {"seconds": 1},
            }))
            async for raw in socket:
                received.append(json.loads(raw))

        try:
            async with serve(exchange, "127.0.0.1", 0) as server:
                port = server.sockets[0].getsockname()[1]
                transcript = MagicMock()
                transcript.stop_requested = asyncio.Event()
                async with AsyncOpenAI(
                    api_key="offline-test-token",
                    base_url=f"http://127.0.0.1:{port}/v1",
                    max_retries=0,
                ) as client:
                    async with client.live.connect() as connection:
                        async with asyncio.timeout(10):
                            await converse(
                                connection, OfflineAudio(), transcript,
                                "plain-prompt:7", managed_delegation=True,
                            )
        finally:
            # A notification must never cause client commentary or prompt execution.
            self.assertFalse(any(
                command["type"] in {
                    "session.commentary.append",
                    "session.thinking.append",
                    "response.create",
                    "response.item.create",
                }
                for command in received
            ))
        return transcript

    async def test_original_managed_sample_accepts_service_owned_notice(self):
        transcript = await self.check_delegation_notice("foundry_managed_agent")
        self.assertIn("Prompt agent delegation requested", str(transcript.mock_calls))

    async def test_native_client_and_responses_targets_still_fail_without_fallback(self):
        for target in ("client", "responses"):
            with self.subTest(target=target):
                with self.assertRaisesRegex(DemoError, f"delegation target '{target}'"):
                    await self.check_delegation_notice(target)


if __name__ == "__main__":
    unittest.main()
