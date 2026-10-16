"""Offline parity, lifecycle, and audio-loop contracts for the migration demo."""

import asyncio
import base64
import copy
import io
import json
import sys
import threading
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from azure.ai.projects.models import RealtimeServerEventResponseDone, VoiceAgentDefinition
from azure.ai.voicelive.models import ServerEventResponseDone, ServerEventSessionUpdated

sys.path.insert(0, str(
    Path(__file__).resolve().parents[1] / "samples" / "voice_live_to_voice_agent"
))
import migration_common as common
import migration_audio as local_audio
import voice_agent as agent
import voice_live as live


def manager(value):
    result = MagicMock()
    result.__aenter__ = AsyncMock(return_value=value)
    result.__aexit__ = AsyncMock(return_value=False)
    return result


class MigrationTests(unittest.IsolatedAsyncioTestCase):
    def test_uses_folder_local_audio(self):
        self.assertIs(common.Audio, local_audio.Audio)
        self.assertEqual(common.RATE, local_audio.RATE)

    def test_local_audio_playback_and_padding(self):
        audio = local_audio.Audio()
        audio.play(b"\x01\x02")
        output = bytearray(4)
        audio._speaker(output, 2, None, None)
        self.assertEqual(output, b"\x01\x02\0\0")
        self.assertEqual(audio.output, b"")

    def test_local_audio_rejects_invalid_pcm_and_unbounded_playback(self):
        audio = local_audio.Audio()
        with self.assertRaisesRegex(local_audio.AudioError, "incomplete PCM16"):
            audio.play(b"\0")
        audio.output = bytearray(local_audio.RATE * 2 * 30)
        with self.assertRaisesRegex(local_audio.AudioError, "backlog"):
            audio.play(b"\0\0")

    async def test_local_audio_capture_and_overflow(self):
        audio = local_audio.Audio()
        stop = asyncio.Event()
        audio._microphone(b"\x01\x02", 1, None, None)
        frames = audio.frames(stop)
        self.assertEqual(await anext(frames), b"\x01\x02")
        stop.set()
        with self.assertRaises(StopAsyncIteration):
            await anext(frames)
        for _ in range(101):
            audio._microphone(b"\0\0", 1, None, None)
        with self.assertRaisesRegex(local_audio.AudioError, "backlog"):
            await anext(audio.frames(asyncio.Event()))

    def test_local_audio_device_failure_and_partial_start_cleanup(self):
        sd = MagicMock()
        sd.PortAudioError = RuntimeError
        sd.check_input_settings.side_effect = ValueError("no microphone")
        with patch.dict(sys.modules, {"sounddevice": sd}):
            with self.assertRaisesRegex(local_audio.AudioError, "Audio device unavailable"):
                with local_audio.Audio():
                    pass
            sd.check_input_settings.side_effect = None
            sd.RawInputStream.side_effect = RuntimeError("device disconnected")
            with self.assertRaisesRegex(RuntimeError, "device disconnected"):
                with local_audio.Audio() as audio:
                    audio.start()
        sd.RawOutputStream.return_value.abort.assert_called_once()
        sd.RawOutputStream.return_value.close.assert_called_once()

    def test_full_settings_parity(self):
        direct = live.build_session().as_dict()
        saved = agent.build_definition().as_dict()
        self.assertEqual(saved["model"], common.MODEL)
        self.assertEqual(saved["model_type"], "managed")
        self.assertEqual(saved["kind"], "voice")
        self.assertFalse(saved["store"])
        self.assertEqual(direct["instructions"], saved["instructions"])
        self.assertEqual(direct["modalities"], saved["output_modalities"])
        input_config = saved["audio"]["input"]
        for source, target in (
            ("input_audio_transcription", "transcription"),
            ("input_audio_noise_reduction", "noise_reduction"),
            ("turn_detection", "turn_detection"),
        ):
            self.assertEqual(direct[source], input_config[target])
        self.assertEqual(direct["input_audio_format"], "pcm16")
        self.assertEqual(direct["output_audio_format"], "pcm16")
        self.assertEqual(direct["input_audio_sampling_rate"], 24000)
        for config in saved["audio"].values():
            self.assertEqual(config["format"], {"type": "audio/pcm", "rate": 24000})
        self.assertEqual(direct["voice"], {
            "name": saved["audio"]["output"]["voice"],
            "type": saved["audio"]["output"]["voice_type"],
        })
        self.assertEqual(direct["input_audio_transcription"]["model"], "azure-speech")
        self.assertEqual(direct["voice"]["name"], "en-US-Ava:DragonHDLatestNeural")
        self.assertTrue(direct["turn_detection"]["interrupt_response"])
        self.assertTrue(direct["turn_detection"]["create_response"])
        self.assertEqual(direct["tools"], saved["tools"])
        self.assertEqual(direct["tools"], common.TOOLS)
        self.assertEqual(direct["tool_choice"], saved["tool_choice"])
        self.assertEqual(direct["tool_choice"], "auto")

    def test_local_function_validates_arguments(self):
        self.assertEqual(common.execute_function("add_numbers", '{"a":2,"b":3}'), {"sum": 5})
        self.assertEqual(common.execute_function("add_numbers", '{"a":-2.5,"b":3}'), {"sum": 0.5})
        for arguments in (
            "", "null", "[]", '{"a":2}', '{"a":2,"b":3,"extra":4}',
            '{"a":true,"b":3}', '{"a":"2","b":3}', '{"a":NaN,"b":3}',
            '{"a":Infinity,"b":3}', '{"a":1e308,"b":1e308}',
        ):
            with self.subTest(arguments=arguments), self.assertRaises(ValueError):
                common.execute_function("add_numbers", arguments)
        with self.assertRaisesRegex(ValueError, "Unsupported local function"):
            common.execute_function("delete_files", "{}")

    async def test_both_sdks_use_identical_local_function_flow(self):
        event_data = {"type": "response.done", "response": {
            "id": "response1", "status": "completed", "output": [
                {"type": "function_call", "id": "item1", "call_id": "call1",
                 "name": "add_numbers", "arguments": '{"a":2,"b":3}'},
                {"type": "function_call", "id": "item2", "call_id": "call2",
                 "name": "add_numbers", "arguments": '{"a":-1,"b":4}'},
            ],
        }}
        for event_type in (ServerEventResponseDone, RealtimeServerEventResponseDone):
            with self.subTest(sdk=event_type.__name__):
                sequence = []

                async def send(event):
                    self.assertEqual(event["type"], "conversation.item.create")
                    sequence.append(("output", dict(event["item"])))

                async def create_response():
                    sequence.append(("response",))

                connection = SimpleNamespace(
                    send=AsyncMock(side_effect=send),
                    response=SimpleNamespace(create=AsyncMock(side_effect=create_response)),
                )
                calls = set()
                event = event_type(copy.deepcopy(event_data))
                with redirect_stdout(io.StringIO()):
                    await common.handle_functions(event, connection, calls)
                    await common.handle_functions(event, connection, calls)
                self.assertEqual([entry[0] for entry in sequence], ["output", "output", "response"])
                self.assertEqual([entry[1]["call_id"] for entry in sequence[:-1]], ["call1", "call2"])
                self.assertEqual([json.loads(entry[1]["output"]) for entry in sequence[:-1]],
                                 [{"sum": 5}, {"sum": 3}])
                self.assertTrue(all(entry[1]["type"] == "function_call_output" for entry in sequence[:-1]))
                connection.response.create.assert_awaited_once_with()

    async def test_functions_wait_for_completed_response(self):
        connection = MagicMock()
        connection.send = AsyncMock()
        connection.response.create = AsyncMock()
        for event in (
            {"type": "response.function_call_arguments.done", "name": "add_numbers",
             "call_id": "call1", "arguments": '{"a":2,"b":3}'},
            {"type": "response.done", "response": {"status": "cancelled", "output": [
                {"type": "function_call", "call_id": "call1", "name": "add_numbers",
                 "arguments": '{"a":2,"b":3}'},
            ]}},
            {"type": "response.done", "response": {"status": "completed", "output": [
                {"type": "message", "role": "assistant", "content": []},
            ]}},
        ):
            await common.handle_functions(event, connection, set())
        connection.send.assert_not_awaited()
        connection.response.create.assert_not_awaited()

    async def test_invalid_tool_call_and_submission_failure_surface(self):
        connection = MagicMock()
        connection.send = AsyncMock()
        connection.response.create = AsyncMock()
        for call in (
            {"type": "function_call", "name": "add_numbers", "arguments": '{"a":2,"b":3}'},
            {"type": "function_call", "call_id": "call1", "name": "unknown", "arguments": "{}"},
            {"type": "function_call", "call_id": "call1", "name": "add_numbers", "arguments": {}},
        ):
            with self.subTest(call=call), self.assertRaises(ValueError):
                await common.handle_functions({"type": "response.done", "response": {
                    "status": "completed", "output": [call],
                }}, connection, set())
        connection.response.create.assert_not_awaited()
        connection.send.side_effect = ConnectionResetError("lost transport")
        with redirect_stdout(io.StringIO()), self.assertRaises(ConnectionResetError):
            await common.handle_functions({"type": "response.done", "response": {
                "status": "completed", "output": [{
                    "type": "function_call", "call_id": "call1", "name": "add_numbers",
                    "arguments": '{"a":2,"b":3}',
                }],
            }}, connection, set())
        connection.response.create.assert_not_awaited()

    async def test_conversation_loop_executes_tool_and_keeps_receiving(self):
        events = iter([
            {"type": "session.updated"},
            {"type": "response.done", "response": {"status": "completed", "output": [{
                "type": "function_call", "call_id": "call1", "name": "add_numbers",
                "arguments": '{"a":12.5,"b":7.5}',
            }]}},
            {"type": "response.output_audio_transcript.done", "transcript": "The sum is 20."},
        ])
        audio = MagicMock()

        async def frames(stop):
            yield b"\0\0"
            await stop.wait()

        audio.frames = frames
        context = MagicMock()
        context.__enter__.return_value = audio
        connection = SimpleNamespace(
            input_audio_buffer=SimpleNamespace(append=AsyncMock()),
            send=AsyncMock(),
            response=SimpleNamespace(create=AsyncMock()),
        )

        async def recv():
            try:
                return next(events)
            except StopIteration:
                connection.response.create.assert_awaited_once_with()
                raise ConnectionResetError("test finished")

        connection.recv = recv
        printed = io.StringIO()
        with (
            patch.object(common, "Audio", return_value=context),
            redirect_stdout(printed),
            self.assertRaisesRegex(ConnectionResetError, "test finished"),
        ):
            await common.talk(connection)
        output = connection.send.call_args.args[0]["item"]
        self.assertEqual(output["call_id"], "call1")
        self.assertEqual(json.loads(output["output"]), {"sum": 20.0})
        self.assertIn("Local function: add_numbers", printed.getvalue())
        self.assertIn("Assistant: The sum is 20.", printed.getvalue())
        context.__exit__.assert_called_once()

    def test_builders_do_not_mutate_shared_settings(self):
        direct = live.build_session().as_dict()
        direct["voice"]["name"] = "different"
        saved = agent.build_definition().as_dict()
        saved["audio"]["input"]["turn_detection"]["threshold"] = 0.9
        self.assertEqual(live.build_session().as_dict()["voice"], common.VOICE)
        self.assertEqual(
            agent.build_definition().as_dict()["audio"]["input"]["turn_detection"],
            common.TURN_DETECTION,
        )

    def test_readback_rejects_every_changed_setting(self):
        expected = agent.build_definition()
        leaves = []

        def visit(value, path=()):
            if isinstance(value, dict):
                for key, child in value.items():
                    visit(child, (*path, key))
            else:
                leaves.append(path)

        visit(expected.as_dict())
        for path in leaves:
            with self.subTest(path=path):
                changed = copy.deepcopy(expected.as_dict())
                parent = changed
                for key in path[:-1]:
                    parent = parent[key]
                parent[path[-1]] = "mismatch"
                with self.assertRaisesRegex(ValueError, "Stored setting differs"):
                    common.validate_definition(changed, expected)

    def test_readback_allows_normalized_voice_and_service_defaults(self):
        saved = agent.build_definition().as_dict()
        saved["audio"]["output"]["voice"] = {
            **common.VOICE, "temperature": 0.8,
        }
        saved["audio"]["output"].pop("voice_type")
        saved["audio"]["input"]["turn_detection"]["remove_filler_words"] = False
        saved["tools"][0]["response_scheduling"] = "when_idle"
        common.validate_definition(VoiceAgentDefinition(saved), agent.build_definition())

    def test_readback_rejects_changed_tool_schema(self):
        for key, value in (("name", "other"), ("parameters", {})):
            saved = agent.build_definition().as_dict()
            saved["tools"][0][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, "Stored setting differs"):
                common.validate_definition(saved, agent.build_definition())

    async def test_direct_connect_configures_session(self):
        connection = SimpleNamespace(session=SimpleNamespace(update=AsyncMock()))
        with (
            patch.object(live, "DefaultAzureCredential", return_value=manager(object())),
            patch.object(live, "connect", return_value=manager(connection)) as connect,
            patch.object(live, "talk", new_callable=AsyncMock) as talk,
        ):
            await live.run("https://example.services.ai.azure.com/")
        self.assertEqual(connect.call_args.kwargs["model"], common.MODEL)
        self.assertEqual(connect.call_args.kwargs["api_version"], "2026-04-10")
        self.assertEqual(
            connection.session.update.call_args.kwargs["session"].as_dict(),
            live.build_session().as_dict(),
        )
        talk.assert_awaited_once_with(connection)

    async def test_direct_rejects_project_endpoint(self):
        with self.assertRaisesRegex(ValueError, "resource root"):
            await live.run("https://example.services.ai.azure.com/api/projects/demo")

    async def test_agent_create_reuse_and_create_only(self):
        for existing, create_only in ((None, False), (None, True), ("existing", False)):
            with self.subTest(existing=existing, create_only=create_only):
                version = SimpleNamespace(version="1", definition=agent.build_definition())
                connection = SimpleNamespace(session=SimpleNamespace(update=AsyncMock()))
                client = SimpleNamespace(
                    agents=SimpleNamespace(
                        create_version=AsyncMock(return_value=version),
                        get_version=AsyncMock(return_value=version),
                        get=AsyncMock(return_value=SimpleNamespace(
                            versions=SimpleNamespace(latest=version),
                        )),
                        enable=AsyncMock(),
                    ),
                    beta=SimpleNamespace(voice_agents=SimpleNamespace(
                        realtime=SimpleNamespace(connect=MagicMock(return_value=manager(connection))),
                    )),
                )
                with (
                    patch.object(agent, "DefaultAzureCredential", return_value=manager(object())),
                    patch.object(agent, "AIProjectClient", return_value=manager(client)),
                    patch.object(agent, "talk", new_callable=AsyncMock) as talk,
                    redirect_stdout(io.StringIO()),
                ):
                    await agent.run(
                        "https://example.services.ai.azure.com/api/projects/demo",
                        existing, create_only,
                    )
                if existing:
                    client.agents.create_version.assert_not_awaited()
                    client.agents.get_version.assert_not_awaited()
                else:
                    client.agents.create_version.assert_awaited_once()
                    client.agents.get_version.assert_awaited_once()
                if create_only:
                    client.agents.enable.assert_not_awaited()
                    talk.assert_not_awaited()
                    client.beta.voice_agents.realtime.connect.assert_not_called()
                else:
                    client.agents.enable.assert_awaited_once()
                    talk.assert_awaited_once_with(connection)
                connection.session.update.assert_not_awaited()

    async def test_agent_readback_mismatch_prevents_enable_and_connect(self):
        definition = agent.build_definition().as_dict()
        definition["audio"]["output"]["voice"] = "different"
        client = MagicMock()
        client.agents.get = AsyncMock(return_value=SimpleNamespace(
            versions=SimpleNamespace(latest=SimpleNamespace(definition=definition)),
        ))
        client.agents.enable = AsyncMock()
        with (
            patch.object(agent, "DefaultAzureCredential", return_value=manager(object())),
            patch.object(agent, "AIProjectClient", return_value=manager(client)),
            self.assertRaises(ValueError),
        ):
            await agent.run(
                "https://example.services.ai.azure.com/api/projects/demo", "existing", False,
            )
        client.agents.enable.assert_not_awaited()
        client.beta.voice_agents.realtime.connect.assert_not_called()

    def test_audio_events_and_barge_in(self):
        audio = MagicMock()
        audio.lock = threading.Lock()
        audio.output = bytearray(b"queued")
        pcm = b"\0\0" * 240
        for kind in ("response.audio.delta", "response.output_audio.delta"):
            common.handle_event({"type": kind, "delta": base64.b64encode(pcm).decode()}, audio)
        self.assertEqual(audio.play.call_count, 2)
        audio.play.assert_called_with(pcm)
        common.handle_event({"type": "input_audio_buffer.speech_started"}, audio)
        self.assertEqual(audio.output, b"")

    def test_service_errors_are_not_hidden(self):
        for event in (
            {"type": "error", "error": {"message": "denied"}},
            {"type": "conversation.item.input_audio_transcription.failed", "error": {"message": "stt failed"}},
            {"type": "response.done", "response": {"status": "failed"}},
            {"type": "response.done", "response": {"status": "incomplete"}},
        ):
            with self.subTest(event=event), self.assertRaises(RuntimeError):
                common.handle_event(event)
        common.handle_event({"type": "response.done", "response": {"status": "cancelled"}})

    async def test_readiness_error_never_opens_audio(self):
        connection = SimpleNamespace(recv=AsyncMock(return_value={
            "type": "error", "error": {"message": "denied"},
        }))
        with patch.object(common, "Audio") as audio, self.assertRaisesRegex(RuntimeError, "denied"):
            await common.talk(connection)
        audio.assert_not_called()

    async def test_typed_sdk_event_is_a_mapping(self):
        event = ServerEventSessionUpdated({"type": "session.updated", "session": {"id": "s"}})
        self.assertEqual(event.get("type"), "session.updated")
        common.handle_event(event)

    async def test_transport_failure_cancels_sender_and_closes_audio(self):
        sent = asyncio.Event()
        stopped = asyncio.Event()

        async def frames(stop):
            try:
                yield b"\0\0"
                await asyncio.Event().wait()
            finally:
                stopped.set()

        audio = MagicMock()
        audio.frames = frames
        calls = 0

        async def recv():
            nonlocal calls
            calls += 1
            if calls == 1:
                return {"type": "session.created"}
            if calls == 2:
                audio.start.assert_not_called()
                return {"type": "session.updated"}
            await sent.wait()
            raise ConnectionResetError("lost transport")

        async def append(*, audio):
            self.assertEqual(audio, base64.b64encode(b"\0\0").decode())
            sent.set()

        connection = SimpleNamespace(
            recv=recv, input_audio_buffer=SimpleNamespace(append=append),
        )
        context = MagicMock()
        context.__enter__.return_value = audio
        with (
            patch.object(common, "Audio", return_value=context),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(ConnectionResetError, "lost transport"),
        ):
            await common.talk(connection)
        audio.start.assert_called_once()
        self.assertTrue(stopped.is_set())
        context.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
