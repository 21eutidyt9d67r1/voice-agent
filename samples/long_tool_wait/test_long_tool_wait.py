"""Offline timing, protocol, interruption, and PCM ordering regressions."""

import argparse
import asyncio
import json
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from azure.ai.projects.models import RealtimeClientEventResponseCreate

from long_tool_wait import CANCEL_TOOL, MODELS, REMINDER, STATUS_TOOL, TOOL, Session, arguments, definition, lookup, reminder_response, seconds
from wait_audio import Playback


def connection():
    return SimpleNamespace(
        response=SimpleNamespace(create=AsyncMock()),
        conversation=SimpleNamespace(item=SimpleNamespace(create=AsyncMock())),
        send=AsyncMock(),
    )


def call(call_id="call-1", name=TOOL, raw='{"order_id":"DEMO-123"}'):
    return {"type": "function_call", "call_id": call_id, "name": name, "arguments": raw}


class ContractTests(unittest.TestCase):
    def test_both_models_use_voice_agents(self):
        for model in MODELS:
            with self.subTest(model=model):
                config = definition(model, "en-US-AvaNeural").as_dict()
                self.assertEqual(config["kind"], "voice")
                self.assertEqual(config["model"], model)
                self.assertEqual(config["model_type"], "managed")
                self.assertFalse(config["store"])
                self.assertEqual(config["tools"][0]["name"], TOOL)
                self.assertEqual([tool["name"] for tool in config["tools"][1:]], [CANCEL_TOOL, STATUS_TOOL])
                audio = config["audio"]
                self.assertEqual(audio["input"]["format"], {"type": "audio/pcm", "rate": 24000})
                self.assertEqual(audio["output"]["voice_type"], "azure-standard")
                self.assertEqual(
                    audio["input"]["transcription"]["model"],
                    "azure-speech" if model == "gpt-5.4" else "whisper-1",
                )
                self.assertFalse(audio["input"]["turn_detection"]["create_response"])
                self.assertFalse(audio["input"]["turn_detection"]["interrupt_response"])
        with self.assertRaises(ValueError):
            definition("other", "voice")

    def test_voice_agent_reminder_wire_contract(self):
        response = reminder_response("request-1")
        event = RealtimeClientEventResponseCreate(response=response).as_dict()
        self.assertEqual(event["type"], "response.create")
        config = event["response"]
        self.assertEqual(config["conversation"], "none")
        self.assertEqual(config["input"], [])
        self.assertEqual(config["tool_choice"], "none")
        self.assertEqual(config["output_modalities"], ["text", "audio"])
        self.assertNotIn("modalities", config)
        self.assertIsNone(config["interim_response"])
        self.assertEqual(config["metadata"], {"purpose": "tool_wait_reminder", "request": "request-1"})
        self.assertIn(REMINDER, config["instructions"])

    def test_argument_policy(self):
        self.assertEqual(arguments('{"order_id":"DEMO-123"}'), {"order_id": "DEMO-123"})
        for raw in ('{}', '[]', 'null', '{"order_id":"real"}', '{"order_id":"DEMO-123","extra":1}',
                    '{"order_id":"DEMO-123","order_id":"DEMO-123"}', "bad", "x" * 1025):
            with self.subTest(raw=raw[:40]), self.assertRaises(ValueError):
                arguments(raw)
        for value in ("nan", "inf", "-1", "121"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                seconds(value)

    def test_playback_orders_reminder_and_final_and_clears_partial_chunk(self):
        playback = Playback()
        playback.output(b"\x01\x00" * 3)
        playback.output(b"\x02\x00" * 2)
        self.assertEqual(playback.render(4), b"\x01\x00" * 3 + b"\x02\x00")
        playback.interrupt()
        self.assertEqual(playback.render(2), bytes(4))
        playback.output(b"\x03\x00")
        self.assertEqual(playback.render(2), b"\x03\x00\x00\x00")
        with self.assertRaises(RuntimeError):
            playback.output(b"x")
        with self.assertRaises(RuntimeError):
            playback.output(bytes(24000 * 2 * 120 + 2))


class SessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.conn = connection()
        self.audio = Playback()
        self.session = Session(self.conn, self.audio, delay=60, reminder_after=60)

    async def asyncTearDown(self):
        for task in self.session.tasks:
            task.cancel()
        await asyncio.gather(*self.session.tasks, return_exceptions=True)

    async def created(self, response_id="response-1"):
        active = self.session.active
        await self.session.handle({
            "type": "response.created",
            "response": {"id": response_id, "metadata": {"purpose": active.purpose, "request": active.token}},
        })

    async def start_call(self, arguments_event=True):
        await self.session.create_response()
        await self.created()
        if arguments_event:
            await self.session.handle({
                **call(), "type": "response.function_call_arguments.done", "response_id": "response-1",
            })

    async def done(self, response_id="response-1", calls=None, status="completed"):
        await self.session.handle({
            "type": "response.done",
            "response": {"id": response_id, "status": status, "output": calls or []},
        })

    async def tool_done(self, result=None):
        await self.session.handle({
            "type": "local.tool_done", "token": self.session.job.token,
            "result": result or {"ok": True, "simulated": True, "status": "shipped"},
        })

    async def reminder_due(self):
        await self.session.handle({"type": "local.reminder_due", "token": self.session.job.token})

    async def test_tool_starts_early_but_output_waits_for_calling_response_done(self):
        await self.start_call()
        self.assertIsNotNone(self.session.job.task)
        self.assertIsNone(self.session.job.timer)
        await self.tool_done()
        self.conn.conversation.item.create.assert_not_awaited()
        await self.done(calls=[call()])
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.conn.response.create.await_count, 2)
        self.assertEqual(self.session.reminders, 0)

    async def test_fast_tool_cancels_timer_and_sends_one_followup(self):
        await self.start_call()
        await self.done(calls=[call()])
        timer = self.session.job.timer
        token = self.session.job.token
        self.assertIsNotNone(timer)
        await self.tool_done()
        await asyncio.sleep(0)
        self.assertTrue(timer.cancelled())
        await self.session.handle({"type": "local.reminder_due", "token": token})
        self.assertEqual(self.session.reminders, 0)
        self.assertEqual(self.conn.response.create.await_count, 2)
        self.conn.conversation.item.create.assert_awaited_once()

    async def test_tool_finishing_during_reminder_waits_for_its_done(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.reminder_due()
        self.assertEqual(self.conn.response.create.await_count, 2)
        self.assertEqual(self.session.reminders, 1)
        await self.created("reminder-1")
        await self.tool_done()
        self.conn.conversation.item.create.assert_not_awaited()
        await self.done("reminder-1")
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.conn.response.create.await_count, 3)
        self.assertEqual(self.session.active.purpose, "tool_result")
        params = self.conn.response.create.call_args.kwargs["response"].as_dict()
        self.assertEqual(params["tools"], [])
        self.assertEqual(params["tool_choice"], "none")
        output = self.conn.conversation.item.create.call_args.kwargs["item"]
        self.assertEqual(output["call_id"], "call-1")
        self.assertTrue(json.loads(output["output"])["ok"])

    async def test_reminder_only_once_when_tool_outlasts_reminder(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.reminder_due()
        await self.created("reminder-1")
        await self.done("reminder-1")
        await self.reminder_due()
        self.assertEqual(self.session.reminders, 1)
        self.conn.conversation.item.create.assert_not_awaited()
        await self.tool_done()
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.conn.response.create.await_count, 3)

    async def test_speech_keeps_tool_running_and_answers_after_transcription(self):
        await self.start_call()
        await self.done(calls=[call()])
        job = self.session.job
        self.audio.output(bytes(4800))
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await asyncio.sleep(0)
        self.assertFalse(job.task.done())
        self.assertTrue(job.timer.cancelled())
        self.assertEqual(self.audio.queued_bytes, 0)
        self.conn.conversation.item.create.assert_not_awaited()
        await self.session.handle({"type": "input_audio_buffer.committed"})
        self.assertEqual(self.conn.response.create.await_count, 1)
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Why is it taking so long?",
        })
        self.assertEqual(self.conn.response.create.await_count, 2)
        params = self.conn.response.create.call_args.kwargs["response"].as_dict()
        self.assertEqual(params["conversation"], "none")
        self.assertEqual(params["tools"][0]["name"], CANCEL_TOOL)
        self.assertEqual(params["tools"][1]["name"], STATUS_TOOL)
        self.assertEqual(params["tool_choice"], "required")
        self.assertIn("Why is it taking so long?", params["input"][0]["content"][0]["text"])
        await self.created("caller-1")
        await self.done("caller-1", calls=[call("status-1", STATUS_TOOL, "{}")])
        await self.created("caller-answer-1")
        await self.done("caller-answer-1")
        self.assertIs(self.session.job, job)
        self.assertFalse(job.task.done())
        self.assertEqual(self.session.reminders, 0)
        await self.tool_done()
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.conn.response.create.await_count, 4)

    async def test_interruption_before_reminder_created_defers_targeted_cancel(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.reminder_due()
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        self.conn.send.assert_not_awaited()
        await self.created("reminder-1")
        self.assertEqual(self.conn.send.call_args.args[0]["response_id"], "reminder-1")
        self.conn.conversation.item.create.assert_not_awaited()
        await self.session.handle({"type": "input_audio_buffer.committed"})
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Stop checking.",
        })
        self.assertEqual(self.conn.response.create.await_count, 2)
        await self.done("reminder-1", status="cancelled")
        self.assertEqual(self.conn.response.create.await_count, 3)
        self.conn.conversation.item.create.assert_not_awaited()
        self.assertEqual(self.session.active.purpose, "caller_update")
        await self.session.handle({
            "type": "response.output_audio.delta", "response_id": "reminder-1", "delta": bytes(4800),
        })
        self.assertEqual(self.audio.queued_bytes, 0)

    async def test_incomplete_call_racing_interruption_is_returned_cancelled(self):
        await self.start_call(arguments_event=False)
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.done(calls=[call()], status="cancelled")
        await self.session.handle({"type": "input_audio_buffer.committed"})
        self.conn.conversation.item.create.assert_not_awaited()
        self.assertEqual(self.conn.response.create.await_count, 1)
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Never mind.",
        })
        result = json.loads(self.conn.conversation.item.create.call_args.kwargs["item"]["output"])
        self.assertTrue(result["cancelled"])
        self.assertEqual(self.conn.response.create.await_count, 2)

    async def test_ready_result_waits_for_caller_transcript_not_just_audio_commit(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.tool_done()
        await self.session.handle({"type": "input_audio_buffer.committed"})
        self.conn.conversation.item.create.assert_not_awaited()
        self.assertIsNone(self.session.active)
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Is it ready?",
        })
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.session.active.purpose, "tool_result")
        self.assertEqual(self.session.caller_texts, [])

    async def test_explicit_cancellation_uses_isolated_tool_output_then_resolves_original(self):
        await self.start_call()
        await self.done(calls=[call()])
        job = self.session.job
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.session.handle({"type": "input_audio_buffer.committed"})
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Cancel the lookup.",
        })
        await self.created("caller-1")
        await self.done("caller-1", calls=[call("cancel-1", CANCEL_TOOL, "{}")])
        await asyncio.sleep(0)
        self.assertTrue(job.task.cancelled())
        self.assertTrue(job.result["cancelled"])
        self.conn.conversation.item.create.assert_not_awaited()
        params = self.conn.response.create.call_args.kwargs["response"].as_dict()
        self.assertEqual(params["tool_choice"], "none")
        self.assertEqual(params["conversation"], "none")
        self.assertEqual(params["input"][-1]["type"], "function_call_output")
        self.assertEqual(params["input"][-1]["call_id"], "cancel-1")
        await self.created("confirmation-1")
        await self.done("confirmation-1")
        self.conn.conversation.item.create.assert_awaited_once()
        output = self.conn.conversation.item.create.call_args.kwargs["item"]
        self.assertEqual(output["call_id"], "call-1")
        self.assertTrue(json.loads(output["output"])["cancelled"])
        self.assertIsNone(self.session.job)
        self.assertIsNone(self.session.active)

    async def test_tool_result_waits_while_caller_update_generates(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.session.handle({"type": "input_audio_buffer.committed"})
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Can I wait here?",
        })
        await self.created("caller-1")
        await self.tool_done()
        self.conn.conversation.item.create.assert_not_awaited()
        await self.done("caller-1", calls=[call("status-1", STATUS_TOOL, "{}")])
        await self.created("caller-answer-1")
        await self.done("caller-answer-1")
        self.conn.conversation.item.create.assert_awaited_once()
        self.assertEqual(self.session.active.purpose, "tool_result")
        params = self.conn.response.create.call_args.kwargs["response"].as_dict()
        self.assertEqual(params["tools"], [])
        self.assertEqual(params["tool_choice"], "none")

    async def test_caller_cannot_claim_cancellation_without_executing_a_tool(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.session.handle({"type": "input_audio_buffer.committed"})
        await self.session.handle({
            "type": "conversation.item.input_audio_transcription.completed", "transcript": "Cancel the lookup.",
        })
        await self.created("caller-1")
        with self.assertRaisesRegex(RuntimeError, "required lookup decision"):
            await self.done("caller-1")
        self.assertIsNone(self.session.job.result)
        self.assertFalse(self.session.job.task.done())

    async def test_cancellation_cannot_claim_success_after_tool_task_finished(self):
        self.session.delay = 0
        await self.start_call()
        await self.done(calls=[call()])
        await self.session.job.task
        self.assertIsNone(self.session.job.result)
        result = self.session.caller_tool(call("cancel-1", CANCEL_TOOL, "{}"))
        self.assertFalse(result["ok"])
        self.assertIn("already finished", result["error"])
        status = self.session.caller_tool(call("status-1", STATUS_TOOL, "{}"))
        self.assertFalse(status["pending"])
        await self.session.handle(self.session.events.get_nowait())
        output = self.conn.conversation.item.create.call_args.kwargs["item"]
        self.assertTrue(json.loads(output["output"])["ok"])

    async def test_speech_during_tool_calling_response_preserves_started_lookup(self):
        await self.start_call()
        job = self.session.job
        await self.session.handle({"type": "input_audio_buffer.speech_started"})
        await self.done(calls=[call()], status="cancelled")
        self.assertIs(self.session.job, job)
        self.assertFalse(job.task.done())
        self.assertIsNone(job.result)
        self.assertIsNone(job.timer)

    async def test_unknown_or_parallel_tools_and_metadata_fail_explicitly(self):
        await self.session.create_response()
        with self.assertRaisesRegex(RuntimeError, "metadata"):
            await self.session.handle({"type": "response.created", "response": {"id": "bad", "metadata": {}}})
        await self.created()
        with self.assertRaisesRegex(RuntimeError, "Parallel"):
            await self.done(calls=[call(), call("call-2")])
        await self.done(calls=[call(name="unlock")])
        await self.session.handle(await self.session.events.get())
        result = json.loads(self.conn.conversation.item.create.call_args.kwargs["item"]["output"])
        self.assertFalse(result["ok"])
        self.assertIn("Unsupported", result["error"])

    async def test_only_correlated_cancel_error_is_tolerated(self):
        self.session.cancel_events.add("cancel-1")
        await self.session.handle({
            "type": "error", "error": {"code": "response_cancel_not_active", "event_id": "cancel-1"},
        })
        with self.assertRaises(RuntimeError):
            await self.session.handle({
                "type": "error", "error": {"code": "response_cancel_not_active", "event_id": "unknown"},
            })

    async def test_duplicate_argument_event_does_not_restart_tool(self):
        await self.start_call()
        task = self.session.job.task
        self.session.start_job(call())
        self.assertIs(self.session.job.task, task)
        with self.assertRaises(RuntimeError):
            self.session.start_job(call(raw='{"order_id":"different"}'))

    async def test_timeout_and_validation_return_explicit_failures(self):
        timeout = await lookup('{"order_id":"DEMO-123"}', 1, 0.001)
        self.assertFalse(timeout["ok"])
        self.assertIn("timed out", timeout["error"])
        invalid = await lookup("invalid", 0, 1)
        self.assertFalse(invalid["ok"])
        success = await lookup('{"order_id":"DEMO-123"}', 0, 1)
        self.assertTrue(success["ok"])
        await self.start_call()
        await self.done(calls=[call()])
        await self.tool_done(timeout)
        self.assertFalse(json.loads(self.conn.conversation.item.create.call_args.kwargs["item"]["output"])["ok"])

    async def test_run_disconnect_cleans_tool_and_timer(self):
        class Event(dict):
            def as_dict(self):
                return dict(self)

        async def receive():
            yield Event(type="session.updated")
            yield Event(type="local.disconnected")

        class Transport:
            response = self.conn.response
            conversation = self.conn.conversation
            send = self.conn.send

            def __aiter__(self):
                return receive()

        self.session.connection = Transport()
        self.session.audio = None
        await self.start_call()
        await self.done(calls=[call()])
        tasks = list(self.session.tasks)
        with self.assertRaisesRegex(RuntimeError, "disconnected"):
            await self.session.run()
        self.assertTrue(all(task.done() for task in tasks))

    async def test_timer_uses_configured_six_seconds_and_queues_event(self):
        from unittest.mock import patch

        await self.start_call()
        self.session.reminder_after = 6
        with patch("long_tool_wait.asyncio.sleep", new_callable=AsyncMock) as sleep:
            await self.session.wait_reminder(self.session.job)
        sleep.assert_awaited_once_with(6)
        event = self.session.events.get_nowait()
        self.assertEqual(event, {"type": "local.reminder_due", "token": self.session.job.token})
        self.conn.response.create.assert_awaited_once()

    async def test_reminder_waits_for_calling_response_done(self):
        await self.start_call()
        await self.reminder_due()
        self.assertEqual(self.session.reminders, 0)
        self.conn.response.create.assert_awaited_once()
        await self.done(calls=[call()])
        self.assertEqual(self.session.reminders, 0)
        await self.reminder_due()
        self.assertEqual(self.session.reminders, 1)

    async def test_failed_reminder_never_submits_success_shaped_output(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.reminder_due()
        await self.created("reminder-1")
        await self.tool_done()
        with self.assertRaisesRegex(RuntimeError, "Response failed"):
            await self.done("reminder-1", status="failed")
        self.conn.conversation.item.create.assert_not_awaited()

    async def test_audio_reminder_and_final_share_fifo(self):
        await self.start_call()
        await self.done(calls=[call()])
        await self.reminder_due()
        await self.created("reminder-1")
        await self.session.handle({
            "type": "response.output_audio.delta", "response_id": "reminder-1", "delta": b"\x01\x00" * 3,
        })
        await self.tool_done()
        await self.done("reminder-1")
        await self.created("final-1")
        await self.session.handle({
            "type": "response.output_audio.delta", "response_id": "final-1", "delta": b"\x02\x00" * 3,
        })
        await self.done("final-1")
        self.assertTrue(self.session.finished)
        self.assertEqual(self.audio.render(6), b"\x01\x00" * 3 + b"\x02\x00" * 3)


if __name__ == "__main__":
    unittest.main()
