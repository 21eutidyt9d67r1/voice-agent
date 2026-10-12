"""Offline protocol checks; these do not establish live update support."""

import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock

sys.path.insert(0, str(
    Path(__file__).resolve().parents[1] / "samples" / "voice_live_to_voice_agent"
))
import dynamic_instructions as sample


def completed(text):
    return {
        "type": "response.done",
        "response": {
            "status": "completed",
            "output": [{"type": "message", "content": [{"type": "text", "text": text}]}],
        },
    }


class DynamicInstructionsTests(unittest.IsolatedAsyncioTestCase):
    def test_template_inputs_and_no_real_device_actions(self):
        agent = sample.definition("template").as_dict()
        self.assertEqual(set(agent["structured_inputs"]), set(sample.CONTEXT))
        for name, value in agent["structured_inputs"].items():
            self.assertIn("{{" + name + "}}", agent["instructions"])
            self.assertTrue(value["required"])
            self.assertEqual(value["schema"], {"type": "string"})
        self.assertEqual(agent["tools"], [])
        self.assertEqual(agent["output_modalities"], ["text"])
        self.assertFalse(agent["store"])
        self.assertFalse(agent["audio"]["input"]["turn_detection"]["create_response"])

    async def test_template_does_not_update_session(self):
        connection = AsyncMock()
        connection.recv.side_effect = [
            {"type": "session.updated", "session": {"id": "session-1"}},
            completed("INITIAL_CONTEXT dehumidifier-001; 75 is invalid."),
        ]
        await sample.demonstrate(connection, "template")
        self.assertEqual(connection.send.await_count, 1)
        item = connection.send.call_args.args[0]["item"]
        self.assertEqual(len(item["id"]), 32)
        connection.response.create.assert_awaited_once()

    async def test_start_initializes_before_first_turn(self):
        connection = AsyncMock()
        connection.recv.side_effect = [
            {"type": "session.updated", "session": {"id": "session-1"}},
            {"type": "session.updated", "session": {
                "id": "session-1", "instructions": sample.render_initial_instructions(),
            }},
            completed("INITIAL_CONTEXT dehumidifier-001; 75 is invalid."),
        ]
        await sample.demonstrate(connection, "start")
        events = [call.args[0] for call in connection.send.await_args_list]
        self.assertEqual(events[0]["type"], "session.update")
        self.assertEqual(events[0]["session"]["type"], "realtime")
        self.assertEqual(events[1]["type"], "conversation.item.create")
        agent = sample.definition("start").as_dict()
        self.assertNotIn("structured_inputs", agent)
        self.assertNotIn("{{", events[0]["session"]["instructions"])

    async def test_update_acknowledgment_and_behavior(self):
        connection = AsyncMock()
        async def receive():
            if connection.response.create.await_count == 0:
                return {"type": "session.updated", "session": {"id": "session-1"}}
            if connection.send.await_count == 1:
                return completed("INITIAL_CONTEXT initial answer.")
            if connection.send.await_count == 2:
                return {
                    "type": "session.updated",
                    "session": {
                        "id": "session-1",
                        "instructions": connection.send.call_args.args[0]["session"]["instructions"],
                    },
                }
            return completed("UPDATED_CONTEXT Morgan; dehumidifier-001; 75 is invalid.")
        connection.recv.side_effect = receive
        await sample.demonstrate(connection, "update")
        self.assertEqual(connection.send.await_args_list[1].args[0]["type"], "session.update")
        self.assertEqual(connection.response.create.await_count, 2)

    async def test_update_rejection_is_not_success(self):
        connection = AsyncMock()
        connection.recv.side_effect = [
            {"type": "session.updated", "session": {"id": "session-1"}},
            completed("INITIAL_CONTEXT initial answer."),
            {"type": "error", "error": {"message": "instructions cannot be updated"}},
        ]
        with self.assertRaisesRegex(RuntimeError, "instructions cannot be updated"):
            await sample.demonstrate(connection, "update")
        self.assertEqual(connection.response.create.await_count, 1)

    async def test_unchanged_instructions_are_rejected(self):
        connection = AsyncMock()
        connection.recv.side_effect = [
            {"type": "session.updated", "session": {"id": "session-1"}},
            completed("INITIAL_CONTEXT initial answer."),
            {"type": "session.updated", "session": {"id": "session-1", "instructions": "old"}},
        ]
        with self.assertRaisesRegex(RuntimeError, "exact replacement"):
            await sample.demonstrate(connection, "update")

    async def test_old_behavior_is_rejected(self):
        connection = AsyncMock()
        connection.recv.return_value = completed("INITIAL_CONTEXT still using old instructions.")
        with self.assertRaisesRegex(RuntimeError, "did not verify"):
            await sample.ask(connection, sample.QUESTION, "UPDATED_CONTEXT")

    async def test_different_session_is_rejected(self):
        connection = AsyncMock()
        connection.recv.return_value = {
            "type": "session.updated",
            "session": {"id": "another-session", "instructions": "replacement"},
        }
        with self.assertRaisesRegex(RuntimeError, "original session ID"):
            await sample.replace_instructions(connection, "replacement", "session-1")


if __name__ == "__main__":
    unittest.main()
