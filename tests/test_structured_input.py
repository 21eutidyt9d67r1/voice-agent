"""Structured-input contracts using the real Projects SDK and offline boundaries."""

from __future__ import annotations

import asyncio
import importlib
import io
import json
import os
import sys
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

from aiohttp import WSMessage, WSMsgType
from azure.ai.projects.aio import AIProjectClient
from azure.ai.projects.models import StructuredInputDefinition, VoiceAgentDefinition

from test_projects_sdk_samples import OfflineCredential, OfflineTransport


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "samples"))
with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
    sample = importlib.import_module("voice_agent_with_structured_input")

ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"
INPUTS = {"customer_name": "Ada", "case_id": "SAMPLE-1042"}


def definition():
    return sample.build_definition("gpt-realtime", "en-US-AvaNeural")


def event(kind, **fields):
    return {"type": kind, "event_id": f"event-{kind}", **fields}


def ready():
    return event("session.updated", session={"audio": definition().as_dict()["audio"]})


def args(**overrides):
    values = dict(
        endpoint=ENDPOINT, agent_name=None, model="gpt-realtime",
        voice="en-US-AvaNeural", create_only=False, text="What is my support case?",
        timeout=10, input_transport="query",
    )
    values.update(overrides)
    return Namespace(**values)


def socket_session(events):
    websocket = MagicMock()
    websocket.close_code = 1000
    websocket.send_str = AsyncMock()
    websocket.close = AsyncMock()
    websocket.receive = AsyncMock(side_effect=[
        *(WSMessage(WSMsgType.TEXT, json.dumps(value), "") for value in events),
        WSMessage(WSMsgType.CLOSE, 1000, ""),
    ])
    session = MagicMock()
    session.ws_connect = AsyncMock(return_value=websocket)
    session.close = AsyncMock()
    return websocket, session


class StructuredInputTests(unittest.TestCase):
    def test_definition_uses_typed_schemas_and_templates_not_runtime_values(self):
        value = definition()
        self.assertIsInstance(value, VoiceAgentDefinition)
        self.assertIsInstance(value.structured_inputs["customer_name"], StructuredInputDefinition)
        stored = value.as_dict()
        self.assertFalse(stored["store"])
        self.assertEqual(stored["structured_inputs"]["customer_name"]["schema"]["type"], "string")
        self.assertTrue(stored["structured_inputs"]["case_id"]["required"])
        self.assertEqual(stored["structured_inputs"]["preferred_language"]["default_value"], "English")
        for name in stored["structured_inputs"]:
            self.assertIn("{{" + name + "}}", stored["instructions"])
        for value in INPUTS.values():
            self.assertNotIn(value, json.dumps(stored))

    def test_example_leaves_optional_default_to_service(self):
        self.assertEqual(sample.load_inputs(sample.DEFAULT_INPUT_FILE), INPUTS)
        self.assertNotIn("preferred_language", sample.load_inputs(sample.DEFAULT_INPUT_FILE))

    def load(self, payload):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "inputs.json"
            path.write_bytes(payload)
            return sample.load_inputs(path)

    def test_unicode_and_optional_override(self):
        values = {**INPUTS, "customer_name": "你好", "preferred_language": "Spanish"}
        self.assertEqual(self.load(json.dumps(values, ensure_ascii=False).encode()), values)

    def test_invalid_inputs_fail_without_echoing_values(self):
        for payload in (
            b"[]", b"null", b"{", b'{"customer_name":NaN}', b"\xff",
            json.dumps({"customer_name": "private-value"}).encode(),
            json.dumps({**INPUTS, "unknown": "private-value"}).encode(),
            *(json.dumps({**INPUTS, "case_id": value}).encode()
              for value in ("", " ", None, 1042, True, [], {})),
        ):
            with self.subTest(payload=payload):
                with self.assertRaises(ValueError) as raised:
                    self.load(payload)
                self.assertNotIn("private-value", str(raised.exception))

    def test_oversized_file_rejected(self):
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            self.load(b" " * (sample.MAX_INPUT_BYTES + 1))

    def test_compatibility_header_is_ascii_json_without_query(self):
        values = {**INPUTS, "customer_name": "你好\nAda"}
        options = sample.connection_options(values, "header")
        self.assertNotIn("structured_inputs", options)
        encoded = options["extra_headers"]["x-ms-voice-structured-inputs"]
        self.assertTrue(encoded.isascii())
        self.assertNotIn("\n", encoded)
        self.assertEqual(json.loads(encoded), values)
        with self.assertRaises(ValueError):
            sample.connection_options(INPUTS, "invalid")
        with self.assertRaisesRegex(ValueError, "32 KiB"):
            sample.connection_options({**INPUTS, "customer_name": "你" * 6000}, "header")

    def test_existing_agent_definition_validation(self):
        sample.validate_definition(definition(), definition())
        for field, value in (
            ("instructions", "different prompt"), ("structured_inputs", {}),
            ("store", True), ("kind", "prompt"), ("audio", {}),
            ("greeting", {"type": "template", "text": "Hello"}),
            ("tools", [{"type": "function", "name": "lookup", "parameters": {}}]),
        ):
            with self.subTest(field=field):
                stored = definition().as_dict()
                stored[field] = value
                # VoiceAgentDefinition sets its discriminator, so test kind through
                # a plain mapping as the canonical helper also accepts wire JSON.
                with self.assertRaises(ValueError):
                    sample.validate_definition(stored, definition())

    def test_cli_rejects_invalid_modes_and_timeouts(self):
        for flags in (
            ["--text", ""], ["--text", "  "],
            ["--timeout", "0"], ["--timeout", "-1"],
            ["--timeout", "nan"], ["--timeout", "inf"],
            ["--create-only", "--text", "Hello"],
        ):
            with self.subTest(flags=flags), redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit):
                    sample.parse_args(["--endpoint", ENDPOINT, *flags])


class StructuredInputSDKTests(unittest.IsolatedAsyncioTestCase):
    async def connect(self, events, action, inputs=None, transport="query"):
        websocket, session = socket_session(events)
        credential = OfflineCredential()
        async with AIProjectClient(
            endpoint=ENDPOINT, credential=credential, allow_preview=True,
        ) as client:
            with patch("aiohttp.ClientSession", return_value=session):
                async with client.beta.voice_agents.realtime.connect(
                    agent_name="voice-structured-test",
                    **sample.connection_options(INPUTS if inputs is None else inputs, transport),
                ) as connection:
                    result = await action(connection)
        websocket.close.assert_awaited_once()
        session.close.assert_awaited_once()
        return result, websocket, session

    async def test_sdk_serializes_values_and_sends_only_user_text(self):
        async def action(connection):
            await sample.wait_until_ready(connection)
            return await sample.text_turn(connection, "What is my support case?")

        result, websocket, session = await self.connect([
            event("session.created", session={"id": "session-1"}),
            ready(),
            event("response.output_audio.delta", delta="AQACAA==",
                  response_id="reply-1", item_id="item-1", output_index=0, content_index=0),
            event("response.output_audio_transcript.done", transcript="Ada, your case is SAMPLE-1042."),
            event("response.done", response={"id": "reply-1", "status": "completed", "output": []}),
        ], action)
        self.assertIn("SAMPLE-1042", result)
        handshake = session.ws_connect.await_args
        self.assertEqual(
            handshake.args[0],
            ENDPOINT.replace("https://", "wss://") + "/agents/voice-structured-test/endpoint/protocols/voice",
        )
        self.assertEqual(json.loads(handshake.kwargs["params"]["structured_input"]), INPUTS)
        self.assertEqual(handshake.kwargs["headers"]["Foundry-Features"], "VoiceAgents=V1Preview")
        self.assertEqual(handshake.kwargs["protocols"], ("realtime",))
        self.assertNotIn("x-ms-voice-structured-inputs", handshake.kwargs["headers"])
        sent = [json.loads(call.args[0]) for call in websocket.send_str.await_args_list]
        self.assertEqual([value["type"] for value in sent], ["conversation.item.create", "response.create"])
        self.assertEqual(sent[0]["item"]["content"][0]["text"], "What is my support case?")
        self.assertNotIn("instructions", sent[1])

    async def test_unicode_values_round_trip_in_sdk_query(self):
        values = {**INPUTS, "customer_name": "你好", "preferred_language": "Spanish"}
        _, _, session = await self.connect(
            [ready()], sample.wait_until_ready, inputs=values,
        )
        self.assertEqual(
            json.loads(session.ws_connect.await_args.kwargs["params"]["structured_input"]),
            values,
        )

    async def test_explicit_header_mode_uses_sdk_without_query_parameter(self):
        _, _, session = await self.connect(
            [ready()], sample.wait_until_ready, transport="header",
        )
        options = session.ws_connect.await_args.kwargs
        self.assertNotIn("structured_input", options["params"])
        self.assertEqual(
            json.loads(options["headers"]["x-ms-voice-structured-inputs"]), INPUTS,
        )
        self.assertEqual(options["headers"]["Authorization"], "Bearer offline-test-token")
        self.assertEqual(options["protocols"], ("realtime",))

    async def test_text_output_without_audio_transcript(self):
        async def action(connection):
            return await sample.text_turn(connection, "Hello")
        result, _, _ = await self.connect([
            event("response.output_text.done", text="Hello Ada."),
            event("response.done", response={"id": "reply-1", "status": "completed", "output": []}),
        ], action)
        self.assertEqual(result, "Hello Ada.")

    async def test_failed_or_empty_responses_are_not_success(self):
        for status in ("failed", "incomplete", "cancelled", "completed"):
            with self.subTest(status=status):
                async def action(connection):
                    with self.assertRaises(RuntimeError):
                        await sample.text_turn(connection, "Hello")
                await self.connect([
                    event("response.done", response={"id": "reply-1", "status": status, "output": []}),
                ], action)

    async def test_service_errors_do_not_echo_private_context(self):
        for kind in ("error", "conversation.item.input_audio_transcription.failed"):
            with self.subTest(kind=kind):
                async def action(connection):
                    with self.assertRaisesRegex(RuntimeError, "invalid_input") as raised:
                        await sample.wait_until_ready(connection)
                    self.assertNotIn("private-value", str(raised.exception))
                await self.connect([
                    event(kind, error={"code": "invalid_input", "message": "private-value"}),
                ], action)

    async def test_closed_connection_does_not_succeed(self):
        async def action(connection):
            with self.assertRaises(ConnectionResetError):
                await sample.wait_until_ready(connection)
        await self.connect([], action)

    async def test_effective_audio_rejected_before_device_access(self):
        for change in ("rate", "channels", "echo"):
            with self.subTest(change=change):
                value = ready()
                audio = value["session"]["audio"]
                if change == "echo":
                    audio["input"]["echo_cancellation"] = {"reference_source": "client"}
                else:
                    audio["input"]["format"][change] = 48000 if change == "rate" else 2
                async def action(connection):
                    with self.assertRaises(RuntimeError), patch.object(sample, "AudioProcessor") as devices:
                        await sample.wait_until_ready(connection)
                    devices.assert_not_called()
                await self.connect([value], action)

    async def test_microphone_dispatch_and_cleanup(self):
        processor = MagicMock()
        async def action(connection):
            await sample.wait_until_ready(connection)
            with self.assertRaises(ConnectionResetError):
                await sample.microphone_chat(connection)
        with (
            patch.object(sample, "AudioProcessor", return_value=processor),
            patch.object(sample, "pyaudio", object()),
            redirect_stdout(io.StringIO()),
        ):
            await self.connect([
                ready(),
                event("input_audio_buffer.speech_started", audio_start_ms=0, item_id="user-1"),
                event("response.output_audio.delta", delta="AQACAA==",
                      response_id="reply-1", item_id="item-1", output_index=0, content_index=0),
                event("response.done", response={"id": "reply-1", "status": "cancelled", "output": []}),
            ], action)
        processor.start_capture.assert_called_once()
        processor.start_playback.assert_called_once()
        processor.skip_pending_audio.assert_called_once()
        processor.queue_audio.assert_called_once_with(b"\x01\x00\x02\x00")
        processor.shutdown.assert_called_once()

    async def test_microphone_cleanup_on_capture_failure(self):
        processor = MagicMock()
        processor.start_capture.side_effect = RuntimeError("No microphone")
        async def action(connection):
            with self.assertRaisesRegex(RuntimeError, "No microphone"):
                await sample.microphone_chat(connection)
        with (
            patch.object(sample, "AudioProcessor", return_value=processor),
            patch.object(sample, "pyaudio", object()),
        ):
            await self.connect([], action)
        processor.shutdown.assert_called_once()

    async def test_create_readback_enable_and_reuse_with_real_sdk(self):
        for existing in (None, "voice-structured-test"):
            with self.subTest(existing=existing):
                stored = definition().as_dict()
                version = {
                    "object": "agent.version", "id": "version-id", "version": "1",
                    "name": existing or "voice-structured-test", "definition": stored,
                }
                def respond(request):
                    path = urlparse(request.url).path
                    if request.method == "POST" and path.endswith("/versions"):
                        self.assertIn("VoiceAgents=V1Preview", request.headers.get("Foundry-Features", ""))
                        body = json.loads(request.content)
                        self.assertEqual(body["definition"], stored)
                        self.assertNotIn("Ada", request.content)
                        return 200, {**version, "name": path.split("/")[-2]}
                    if request.method == "GET" and path.endswith("/versions/1"):
                        return 200, version
                    if request.method == "POST" and path.endswith(":enable"):
                        return 204, {}
                    if request.method == "GET" and path.endswith("/" + str(existing)):
                        return 200, {"name": existing, "versions": {"latest": version}}
                    self.fail(f"Unexpected management request: {request.method} {path}")

                transport = OfflineTransport(respond)
                client = AIProjectClient(
                    endpoint=ENDPOINT, credential=OfflineCredential(),
                    allow_preview=True, transport=transport,
                )
                with (
                    patch.object(sample, "DefaultAzureCredential", return_value=OfflineCredential()),
                    patch.object(sample, "AIProjectClient", return_value=client),
                    redirect_stdout(io.StringIO()),
                ):
                    await sample.run(args(agent_name=existing, create_only=True, text=None), INPUTS)
                self.assertEqual(
                    [request.method for request in transport.requests],
                    ["GET"] if existing else ["POST", "GET", "POST"],
                )

    async def test_run_passes_session_values_without_updating_existing_agent(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.agents.get.return_value = Namespace(
            versions=Namespace(latest=Namespace(version="1", definition=definition())),
        )
        connection_manager = MagicMock()
        client.beta.voice_agents.realtime.connect = MagicMock(return_value=connection_manager)
        with (
            patch.object(sample, "DefaultAzureCredential", return_value=OfflineCredential()),
            patch.object(sample, "AIProjectClient", return_value=client),
            patch.object(sample, "wait_until_ready", new_callable=AsyncMock),
            patch.object(sample, "text_turn", new_callable=AsyncMock, return_value="Ada, SAMPLE-1042."),
            redirect_stdout(io.StringIO()),
        ):
            await sample.run(args(agent_name="voice-structured-test"), INPUTS)
        client.beta.voice_agents.realtime.connect.assert_called_once_with(
            agent_name="voice-structured-test", structured_inputs=INPUTS,
        )
        client.agents.create_version.assert_not_awaited()
        client.agents.enable.assert_not_awaited()

    async def test_invalid_endpoint_rejected_before_auth(self):
        with patch.object(sample, "DefaultAzureCredential") as credential:
            with self.assertRaises(ValueError):
                await sample.run(args(endpoint="http://localhost:8000"), INPUTS)
        credential.assert_not_called()

    async def test_missing_pyaudio_rejected_before_agent_creation(self):
        with (
            patch.object(sample, "pyaudio", None),
            patch.object(sample, "DefaultAzureCredential") as credential,
        ):
            with self.assertRaisesRegex(RuntimeError, "Install pyaudio"):
                await sample.run(args(text=None), INPUTS)
        credential.assert_not_called()


if __name__ == "__main__":
    unittest.main()
