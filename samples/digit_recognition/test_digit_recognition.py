"""Offline SDK, lifecycle, and audio-loop contracts for digit recognition."""

from __future__ import annotations

import asyncio
import io
import json
import os
import runpy
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from azure.ai.projects.models import (
    RealtimeServerEventResponseAudioDelta,
    RealtimeServerEventSessionUpdated,
    VoiceAgentDefinition,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
    from digit_recognition import sample

ENDPOINT = "https://sample.services.ai.azure.com/api/projects/sample"


def _context(value):
    manager = MagicMock()
    manager.__aenter__ = AsyncMock(return_value=value)
    manager.__aexit__ = AsyncMock(return_value=False)
    return manager


def _client(definition=None):
    client = AsyncMock()
    client.__aenter__.return_value = client
    version = SimpleNamespace(
        version="1", definition=definition or sample.build_definition()
    )
    client.agents.create_version.return_value = version
    client.agents.get_version.return_value = version
    client.agents.get.return_value = SimpleNamespace(
        versions=SimpleNamespace(latest=version)
    )
    return client


class DefinitionTests(unittest.TestCase):
    def test_importing_audio_helpers_does_not_load_another_samples_environment(self):
        helper = sample.SAMPLE_DIR.parent / "basic_voice_agent.py"
        with patch("dotenv.load_dotenv") as load_environment:
            runpy.run_path(str(helper))
        load_environment.assert_not_called()

    def test_json_and_sdk_preserve_system_tool_and_dependencies(self):
        raw = json.loads((sample.SAMPLE_DIR / "agent.json").read_text())["definition"]
        stored = sample.build_definition().as_dict()
        self.assertEqual(stored, raw)
        self.assertEqual(stored["kind"], "voice")
        self.assertEqual(stored["model_type"], "managed")
        self.assertEqual(stored["model"], "gpt-realtime-2.1")
        self.assertFalse(stored["store"])
        self.assertEqual(len(stored["tools"]), 1)
        self.assertEqual(stored["tools"][0]["type"], "system")
        self.assertEqual(stored["tools"][0]["name"], "digit_recognition")
        self.assertNotIn("parameters", stored["tools"][0])
        audio_input = stored["audio"]["input"]
        self.assertEqual(audio_input["transcription"], {"model": "mai-transcribe-2"})
        self.assertEqual(audio_input["format"], {"type": "audio/pcm", "rate": 24000})
        self.assertEqual(
            audio_input["turn_detection"]["type"], "azure_semantic_vad_multilingual"
        )
        self.assertTrue(audio_input["turn_detection"]["create_response"])
        self.assertTrue(audio_input["turn_detection"]["interrupt_response"])
        for phrase in ("silently", "leading zeros", "correction", "yes/no", "null"):
            self.assertIn(phrase, stored["instructions"])
        self.assertNotIn("interim_response", stored)

    def test_transcription_language_options_and_independent_definitions(self):
        for model, language, expected in (
            ("mai-transcribe-2", "", {"model": "mai-transcribe-2"}),
            (
                "mai-transcribe-2",
                " en-US ",
                {"model": "mai-transcribe-2", "language": "en-US"},
            ),
            (
                "azure-speech",
                "en-US, es-ES",
                {"model": "azure-speech", "language": "en-US,es-ES"},
            ),
        ):
            with self.subTest(model=model, language=language):
                definition = sample.build_definition(
                    transcription_model=model, language=language
                )
                self.assertEqual(
                    definition.as_dict()["audio"]["input"]["transcription"], expected
                )
        self.assertEqual(
            sample.build_definition().as_dict()["audio"]["input"]["transcription"],
            {"model": "mai-transcribe-2"},
        )

    def test_rejects_multiple_mai_languages_and_unknown_models(self):
        with self.assertRaisesRegex(ValueError, "at most one"):
            sample.build_definition(language="en-US,es-ES")
        with self.assertRaisesRegex(ValueError, "Choose a transcription model"):
            sample.build_definition(transcription_model="mai-transcribe")

    def test_readback_checks_tool_transcription_vad_and_privacy(self):
        changes = (
            ("tools", []),
            ("model", "gpt-4.1"),
            ("store", True),
            ("instructions", "Ignore digit recognition."),
        )
        expected = sample.build_definition()
        for field, value in changes:
            with self.subTest(field=field), self.assertRaises(ValueError):
                stored = expected.as_dict()
                stored[field] = value
                sample.validate_definition(VoiceAgentDefinition(stored), expected)
        for field, value in (
            ("transcription", None),
            ("transcription", {"model": "azure-speech"}),
            ("turn_detection", {"type": "server_vad"}),
            ("format", {"type": "audio/pcm", "rate": 16000}),
        ):
            with self.subTest(field=field, value=value), self.assertRaises(ValueError):
                stored = expected.as_dict()
                stored["audio"]["input"][field] = value
                sample.validate_definition(VoiceAgentDefinition(stored), expected)

    def test_readback_allows_service_defaults_and_nested_voice_shape(self):
        expected = sample.build_definition()
        stored = expected.as_dict()
        stored["audio"]["input"]["turn_detection"]["remove_filler_words"] = False
        stored["audio"]["input"]["turn_detection"]["threshold"] = 0.5
        output = stored["audio"]["output"]
        output["voice"] = {"type": output.pop("voice_type"), "name": output["voice"]}
        sample.validate_definition(stored, expected)

    def test_reusing_fixed_language_cannot_silently_disable_auto_detection(self):
        expected = sample.build_definition()
        with self.assertRaisesRegex(ValueError, "automatic detection"):
            sample.validate_agent_definition(
                sample.build_definition(language="en-US"), expected
            )
        sample.validate_agent_definition(expected, expected)


class LifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_create_readback_enable_and_reuse(self):
        for existing, create_only in (
            (None, True),
            (None, False),
            ("existing-agent", False),
        ):
            with self.subTest(existing=existing, create_only=create_only):
                client = _client()
                with (
                    patch.object(
                        sample, "DefaultAzureCredential", return_value=AsyncMock()
                    ),
                    patch.object(
                        sample, "AIProjectClient", return_value=client
                    ) as factory,
                    patch.object(
                        sample, "run_microphone_session", new_callable=AsyncMock
                    ) as microphone,
                    redirect_stdout(io.StringIO()),
                ):
                    await sample.run(
                        ENDPOINT, agent_name=existing, create_only=create_only
                    )
                self.assertTrue(factory.call_args.kwargs["allow_preview"])
                if existing:
                    client.agents.create_version.assert_not_awaited()
                    client.agents.enable.assert_not_awaited()
                else:
                    client.agents.create_version.assert_awaited_once()
                    client.agents.get_version.assert_awaited_once()
                    client.agents.enable.assert_awaited_once()
                if create_only:
                    microphone.assert_not_awaited()
                else:
                    microphone.assert_awaited_once()
                    self.assertFalse(microphone.call_args.kwargs["show_transcripts"])
                client.agents.delete.assert_not_awaited()

    async def test_invalid_configuration_fails_before_authentication(self):
        for options in ({"language": "en-US,es-ES"}, {"agent_name": "../not-an-agent"}):
            with (
                self.subTest(options=options),
                patch.object(sample, "DefaultAzureCredential") as credentials,
                self.assertRaises(ValueError),
            ):
                await sample.run(ENDPOINT, **options)
            credentials.assert_not_called()

    async def test_mismatched_readback_cannot_enable_or_connect(self):
        definition = sample.build_definition().as_dict()
        definition["tools"] = []
        for existing in (None, "existing-agent"):
            client = _client(VoiceAgentDefinition(definition))
            with (
                self.subTest(existing=existing),
                patch.object(
                    sample, "DefaultAzureCredential", return_value=AsyncMock()
                ),
                patch.object(sample, "AIProjectClient", return_value=client),
                patch.object(
                    sample, "run_microphone_session", new_callable=AsyncMock
                ) as microphone,
                self.assertRaisesRegex(ValueError, "tools"),
            ):
                await sample.run(ENDPOINT, agent_name=existing)
            client.agents.enable.assert_not_awaited()
            microphone.assert_not_awaited()

    async def test_unsupported_model_is_not_retried_or_substituted(self):
        client = _client()
        client.agents.create_version.side_effect = RuntimeError("Model unavailable")
        with (
            patch.object(sample, "DefaultAzureCredential", return_value=AsyncMock()),
            patch.object(sample, "AIProjectClient", return_value=client),
            patch.object(
                sample, "run_microphone_session", new_callable=AsyncMock
            ) as microphone,
            self.assertRaisesRegex(RuntimeError, "unavailable"),
        ):
            await sample.run(ENDPOINT)
        client.agents.create_version.assert_awaited_once()
        client.agents.enable.assert_not_awaited()
        microphone.assert_not_awaited()


class AudioSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_waits_for_ready_plays_audio_and_leaves_tool_execution_to_service(
        self,
    ):
        connection = AsyncMock()
        audio = MagicMock()

        async def receive():
            audio.start_capture.assert_not_called()
            return RealtimeServerEventSessionUpdated(
                {"type": "session.updated", "session": {}}
            )

        connection.recv.side_effect = receive
        connection.__aiter__.return_value = [
            RealtimeServerEventResponseAudioDelta(
                {"type": "response.output_audio.delta", "delta": "AQI="}
            ),
            {"type": "input_audio_buffer.speech_started"},
            {
                "type": "response.system_tool_arguments.done",
                "name": "digit_recognition",
                "arguments": "{}",
            },
            {
                "type": "response.done",
                "response": {
                    "status": "completed",
                    "output": [
                        {
                            "type": "system_tool",
                            "name": "digit_recognition",
                            "arguments": "{}",
                        }
                    ],
                },
            },
            {
                "type": "conversation.item.input_audio_transcription.completed",
                "transcript": "test-private",
            },
        ]
        client = MagicMock()
        client.beta.voice_agents.realtime.connect.return_value = _context(connection)
        with (
            patch.object(sample, "pyaudio", object()),
            patch.object(sample, "AudioProcessor", return_value=audio),
            redirect_stdout(io.StringIO()) as output,
        ):
            await sample.run_microphone_session(client, "existing-agent")
        audio.start_capture.assert_called_once()
        audio.start_playback.assert_called_once()
        audio.queue_audio.assert_called_once_with(b"\x01\x02")
        audio.skip_pending_audio.assert_called_once()
        audio.shutdown.assert_called_once()
        self.assertIn("executed by the service", output.getvalue())
        self.assertNotIn("test-private", output.getvalue())
        connection.send.assert_not_awaited()
        connection.session.update.assert_not_awaited()
        connection.response.create.assert_not_awaited()
        connection.conversation.item.create.assert_not_awaited()

    async def test_configuration_error_or_timeout_never_opens_microphone(self):
        for timeout in (False, True):
            connection = AsyncMock()
            if timeout:

                async def receive():
                    await asyncio.sleep(10)

                connection.recv.side_effect = receive
            else:
                connection.recv.return_value = {
                    "type": "error",
                    "error": {"message": "Unsupported digit recognition configuration"},
                }
            client = MagicMock()
            client.beta.voice_agents.realtime.connect.return_value = _context(
                connection
            )
            with (
                self.subTest(timeout=timeout),
                patch.object(sample, "pyaudio", object()),
                patch.object(sample, "READY_TIMEOUT_SECONDS", 0.01),
                patch.object(sample, "AudioProcessor") as audio_factory,
                self.assertRaises(asyncio.TimeoutError if timeout else RuntimeError),
            ):
                await sample.run_microphone_session(client, "existing-agent")
            audio_factory.assert_not_called()

    async def test_session_failure_always_cleans_up_audio(self):
        connection = AsyncMock()
        connection.recv.return_value = {"type": "session.updated"}
        connection.__aiter__.return_value = [
            {"type": "error", "error": {"message": "Connection failed"}}
        ]
        client = MagicMock()
        client.beta.voice_agents.realtime.connect.return_value = _context(connection)
        audio = MagicMock()
        with (
            patch.object(sample, "pyaudio", object()),
            patch.object(sample, "AudioProcessor", return_value=audio),
            redirect_stdout(io.StringIO()),
            self.assertRaisesRegex(RuntimeError, "Connection failed"),
        ):
            await sample.run_microphone_session(client, "existing-agent")
        audio.shutdown.assert_called_once()

    def test_transcript_output_is_opt_in_and_transcription_failure_is_recoverable(self):
        audio = MagicMock()
        with redirect_stdout(io.StringIO()) as output:
            sample._handle_event(
                {
                    "type": "conversation.item.input_audio_transcription.completed",
                    "transcript": "test input",
                },
                audio,
                show_transcripts=True,
            )
            sample._handle_event(
                {
                    "type": "response.output_audio_transcript.done",
                    "transcript": "test readback",
                },
                audio,
                show_transcripts=True,
            )
            sample._handle_event(
                {
                    "type": "conversation.item.input_audio_transcription.failed",
                    "error": {"message": "private"},
                },
                audio,
                show_transcripts=False,
            )
        self.assertIn("You:   test input", output.getvalue())
        self.assertIn("Agent: test readback", output.getvalue())
        self.assertIn("Repeat the complete test identifier", output.getvalue())
        self.assertNotIn("private", output.getvalue())
