"""Offline event, callback, and raw WebSocket integration tests; no Azure or audio devices."""

import asyncio
import contextlib
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import AsyncMock, Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from control_events import CallControlEvents, TOOL_NAME, agent_definition, offline_demo, validate_request
from websocket_call_control import converse, headers, project_endpoint, session_url, verify_agent


def request(**changes):
    return {"target": "human_support", "reason": "User explicitly requested a person", **changes}


def envelope(kind, *, delegation="d", response="r", **values):
    if kind in {"response.created", "response.completed", "response.cancelled", "response.failed", "response.incomplete"}:
        event = {"type": kind, "response": {"id": response}, **values}
    else:
        event = {"type": kind, "response_id": response, **values}
    return {"type": "response.event", "delegation_id": delegation, "event": event}


def call(call_id="c", name=TOOL_NAME, arguments=None, **extra):
    return {"type": "function_call", "name": name, "call_id": call_id,
            "arguments": json.dumps(request()) if arguments is None else arguments, **extra}


def batch(handler, calls=None, *, delegation="d", response="r", terminal="response.completed"):
    handler.observe(envelope("response.created", delegation=delegation, response=response))
    for item in calls if calls is not None else [call()]:
        handler.observe(envelope("response.output_item.done", delegation=delegation, response=response, item=item))
    handler.observe(envelope(terminal, delegation=delegation, response=response))


class ConfigurationTests(unittest.TestCase):
    def test_definition_declares_only_transfer_and_platform_owned_ending(self):
        definition = agent_definition(" live ", " backend ")
        self.assertEqual(definition["sub_protocol"], "live")
        self.assertEqual(definition["system_tools"], [{"name": "end_conversation"}])
        self.assertFalse(definition["store"])
        tool = definition["delegation"]["responses"]["tools"][0]
        self.assertEqual(tool["name"], TOOL_NAME)
        self.assertEqual(set(tool["parameters"]["properties"]), {"target", "reason"})
        self.assertEqual(len(definition["delegation"]["responses"]["tools"]), 1)
        self.assertTrue(tool["strict"])
        schema = tool["parameters"]
        self.assertEqual(set(schema["properties"]), set(schema["required"]))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(definition["delegation"]["responses"]["model"], "backend")

    def test_payload_validation_rejects_untrusted_structure_destinations_and_limits(self):
        valid = request()
        self.assertEqual(validate_request(json.dumps(valid)), valid)
        for value in (
            [], {}, request(target="sip:arbitrary@example.test"), request(reason=" "),
            request(reason="x" * 513), request(reason=42), request(summary="Not accepted by this sample"),
            request(caller_context="Not accepted"), request(completed_actions=[]),
            {**valid, "conversation_id": "model-chosen"},
        ):
            with self.subTest(value=value), self.assertRaises((ValueError, TypeError)):
                validate_request(json.dumps(value))
        for raw in ('{"target":"human_support","target":"voice_specialist"}', "not-json", "x" * 16385):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                validate_request(raw)

    def test_endpoint_rejects_token_destination_overrides_and_escapes_agent_name(self):
        endpoint = "https://resource.services.ai.azure.com/api/projects/demo"
        self.assertEqual(session_url(endpoint, "a/b?x=1"),
            "wss://resource.services.ai.azure.com/api/projects/demo/agents/a%2Fb%3Fx%3D1/endpoint/protocols/voice/live/sessions")
        for value in ("http://localhost/api/projects/demo", endpoint + "?secret=x", endpoint + "/agents",
                      "https://other.example/api/projects/demo", endpoint.replace("resource.", "user:pass@resource.")):
            with self.subTest(value=value), self.assertRaises(ValueError):
                project_endpoint(value)

    def test_saved_agent_requires_native_live_delegation_tools_and_version(self):
        agent = {"versions": {"latest": {"version": "7", "definition": agent_definition("live", "backend")}}}
        self.assertEqual(verify_agent(agent), "7")
        for field in ("sub_protocol", "system_tools", "delegation"):
            copied = json.loads(json.dumps(agent))
            copied["versions"]["latest"]["definition"].pop(field)
            with self.subTest(field=field), self.assertRaises(ValueError):
                verify_agent(copied)


class EventTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.send = AsyncMock()
        self.callback = AsyncMock(return_value={"status": "queued", "transfer_id": "job-1"})
        self.handler = CallControlEvents(self.send, self.callback)
        self.handler.start()

    async def asyncTearDown(self):
        await self.handler.close()

    async def test_complete_function_waits_for_terminal_then_returns_exact_correlation_once(self):
        self.handler.observe(envelope("response.created"))
        item = call(caller={"id": "original"})
        self.handler.observe(envelope("response.output_item.done", item=item))
        self.handler.observe(envelope("response.output_item.done", item=item))
        self.callback.assert_not_called()
        completed = envelope("response.completed")
        completed["event"]["response"]["output"] = []
        self.handler.observe(completed)
        await self.handler.queue.join()
        self.callback.assert_awaited_once_with(request(), "c")
        commands = [entry.args[0] for entry in self.send.await_args_list]
        self.assertEqual([entry["type"] for entry in commands], ["response.item.create", "response.create"])
        self.assertEqual(commands[0]["item"]["call_id"], "c")
        self.assertEqual(commands[0]["item"]["caller"], {"id": "original"})
        self.assertEqual(json.loads(commands[0]["item"]["output"])["status"], "queued")
        self.handler.observe(envelope("response.completed"))
        self.callback.assert_awaited_once()

    async def test_failed_cancelled_and_incomplete_batches_never_execute(self):
        for index, terminal in enumerate(("response.failed", "response.incomplete", "response.cancelled")):
            batch(self.handler, [call(str(index))], response=f"r{index}", terminal=terminal)
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.send.assert_not_called()

    async def test_non_success_status_in_completion_never_executes(self):
        self.handler.observe(envelope("response.created"))
        self.handler.observe(envelope("response.output_item.done", item=call()))
        completion = envelope("response.completed")
        completion["event"]["response"]["status"] = "failed"
        self.handler.observe(completion)
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.send.assert_not_called()

    async def test_parallel_transfer_and_unknown_function_are_rejected_without_callback(self):
        batch(self.handler, [call(), call("other", "lookup")])
        await self.handler.queue.join()
        self.callback.assert_not_called()
        commands = [item.args[0] for item in self.send.await_args_list]
        self.assertEqual(len(commands), 3)
        self.assertIn("transfer_must_be_called_alone", commands[0]["item"]["output"])
        self.assertIn("unsupported_function", commands[1]["item"]["output"])

    async def test_invalid_args_and_server_mcp_are_not_executed(self):
        batch(self.handler, [call(arguments=json.dumps(request(target="unlisted")))])
        batch(self.handler, [{"type": "mcp_call", "id": "server-owned", "status": "completed"}], response="r2")
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.assertEqual(self.send.await_count, 2)
        self.assertIn("invalid_arguments", self.send.await_args_list[0].args[0]["item"]["output"])

    async def test_callback_failure_is_uncertain_sanitized_and_not_retried(self):
        self.callback.side_effect = RuntimeError("credential=private-token")
        batch(self.handler)
        await self.handler.queue.join()
        self.callback.assert_awaited_once()
        result = self.send.await_args_list[0].args[0]["item"]["output"]
        self.assertIn("outcome_unknown", result)
        self.assertNotIn("private", result)

    async def test_callback_does_not_block_reader_and_close_cancels_pending_work(self):
        entered = asyncio.Event()
        release = asyncio.Event()

        async def callback(*_):
            entered.set()
            await release.wait()
            return {"status": "completed"}

        self.handler.callback = callback
        batch(self.handler)
        await entered.wait()
        # A newer response is still observed while the integration waits; it is not replayed.
        batch(self.handler, [], delegation="new-d", response="new-r")
        await self.handler.close()
        self.send.assert_not_called()

    async def test_reused_call_id_is_rejected_even_across_incomplete_batches(self):
        self.handler.observe(envelope("response.created"))
        self.handler.observe(envelope("response.output_item.done", item=call()))
        self.handler.observe(envelope("response.created", delegation="d2", response="r2"))
        with self.assertRaises(ValueError):
            self.handler.observe(envelope("response.output_item.done", delegation="d2", response="r2", item=call()))

    async def test_mismatched_response_does_not_dispatch_or_continue(self):
        self.handler.observe(envelope("response.created"))
        self.handler.observe(envelope("response.output_item.done", item=call()))
        self.handler.observe(envelope("response.completed", response="different"))
        self.callback.assert_not_called()
        self.send.assert_not_called()

    async def test_changed_done_item_rejects_before_side_effect(self):
        self.handler.observe(envelope("response.created"))
        self.handler.observe(envelope("response.output_item.done", item=call()))
        with self.assertRaises(ValueError):
            self.handler.observe(envelope("response.output_item.done", item=call(arguments=json.dumps(request(target="voice_specialist")))))
        self.callback.assert_not_called()

    async def test_native_end_item_is_observed_without_client_execution_or_tool_result(self):
        batch(self.handler, [{"type": "system_tool", "name": "end_conversation", "call_id": "end-1", "status": "completed"}])
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.send.assert_not_called()

    async def test_transfer_with_system_ending_does_not_execute(self):
        batch(self.handler, [call(), {"type": "system_tool", "name": "end_conversation", "call_id": "end-1"}])
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.assertIn("transfer_must_be_called_alone", self.send.await_args_list[0].args[0]["item"]["output"])

    async def test_non_transfer_function_never_executes(self):
        batch(self.handler, [call(name="request_handover")])
        await self.handler.queue.join()
        self.callback.assert_not_called()
        self.assertIn("unsupported_function", self.send.await_args_list[0].args[0]["item"]["output"])

    async def test_offline_demo_has_real_event_envelopes_and_no_claimed_transfer(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            await offline_demo()
        rows = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]["agent_emits"]["type"], "response.event")
        commands = [row["client_sends"] for row in rows if "client_sends" in row]
        self.assertEqual(commands[-1], {"type": "response.create"})
        self.assertIn("not_executed", commands[0]["item"]["output"])
        self.assertEqual(rows[-2]["agent_emits"]["type"], "session.end_conversation.completed")
        self.assertEqual(rows[-1]["agent_emits"]["type"], "session.closed")

    async def test_headers_refresh_token_for_each_new_request(self):
        credential = Mock(get_token=AsyncMock(side_effect=[Mock(token="one"), Mock(token="two")]))
        self.assertEqual((await headers(credential))["Authorization"], "Bearer one")
        self.assertEqual((await headers(credential))["Authorization"], "Bearer two")
        credential.get_token.assert_awaited_with("https://ai.azure.com/.default")


class LoopbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_websocket_guidance_transfer_result_audio_and_ending(self):
        from aiohttp import ClientSession, web

        audio_received = asyncio.Event()
        callback_started = asyncio.Event()
        server_done = asyncio.get_running_loop().create_future()
        commands = []

        class FakeAudio:
            def start(self):
                commands.append("audio.start")

            def play(self, pcm):
                self.pcm = pcm
                audio_received.set()

            async def frames(self, stop):
                yield b"\x00" * 960
                await stop.wait()

            def stop_microphone(self):
                pass

            async def drain(self):
                commands.append("audio.drain")

        async def callback(context, call_id):
            self.assertEqual(context, request())
            self.assertEqual(call_id, "c")
            callback_started.set()
            await audio_received.wait()  # A blocked callback must not stop inbound audio.
            return {"status": "queued", "transfer_id": "job-1"}

        async def server(http_request):
            ws = web.WebSocketResponse()
            await ws.prepare(http_request)
            try:
                await ws.send_json({"type": "session.started", "session": {"id": "live-1",
                                   "audio": {"format": {"type": "audio/pcm", "rate": 24000}}}})
                guidance = await ws.receive_json()
                self.assertEqual(guidance, {"type": "session.instructions.append", "delegation_id": None,
                                            "content": "Ask for the preferred destination."})
                self.assertNotIn("audio.start", commands)
                await ws.send_json({"type": "session.instructions.appended"})
                self.assertEqual((await ws.receive_json())["type"], "session.input_audio.append")
                for event in (envelope("response.created"), envelope("response.output_item.done", item=call()),
                              envelope("response.completed")):
                    await ws.send_json(event)
                await callback_started.wait()
                await ws.send_json({"type": "session.output_audio.delta", "delta": "AAA="})
                result = await ws.receive_json()
                commands.append(result)
                self.assertEqual(result["item"]["call_id"], "c")
                self.assertEqual(json.loads(result["item"]["output"])["status"], "queued")
                commands.append(await ws.receive_json())
                await ws.send_json({"type": "session.end_conversation.completed", "id": "ending-1"})
                await ws.send_json({"type": "session.closed", "reason": "close_requested"})
                server_done.set_result(None)
            except BaseException as error:
                if not server_done.done():
                    server_done.set_exception(error)
            finally:
                await ws.close()
            return ws

        app = web.Application()
        app.router.add_get("/live", server)
        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, "127.0.0.1", 0)
        await site.start()
        port = site._server.sockets[0].getsockname()[1]
        audio = FakeAudio()
        try:
            async with ClientSession() as client:
                async with client.ws_connect(f"http://127.0.0.1:{port}/live") as ws:
                    with contextlib.redirect_stdout(io.StringIO()):
                        await converse(ws, audio, guidance="Ask for the preferred destination.", callback=callback)
            await server_done
            self.assertEqual(audio.pcm, b"\x00\x00")
            self.assertEqual(commands[-2:], [{"type": "response.create"}, "audio.drain"])
        finally:
            await runner.cleanup()


if __name__ == "__main__":
    unittest.main()
