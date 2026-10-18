"""Offline contract coverage for the voice-first Data Zone sample."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from azure.ai.projects.models import PromptAgentDefinition, VoiceAgentDefinition

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "samples"))
with patch.dict(os.environ, {"PYTHON_DOTENV_DISABLED": "1"}):
    import realtime_datazone_voice_agent as sample


class DatazoneSampleTests(unittest.IsolatedAsyncioTestCase):
    def test_definition(self):
        with patch.dict(os.environ, {"AZURE_VOICE_AGENTS_MODEL": "gpt-4.1"}):
            definition = sample.build_definition()
        sample.validate_definition(definition)
        stored = definition.as_dict()
        self.assertEqual(stored["model"], "gpt-realtime-2.1-datazone")
        self.assertEqual(stored["kind"], "voice")
        self.assertEqual(stored["model_type"], "managed")
        self.assertEqual(stored["instructions"], sample.INSTRUCTIONS)
        self.assertEqual(stored["audio"]["output"]["voice"], "en-US-Ava:DragonHDLatestNeural")
        self.assertEqual(stored["audio"]["output"]["voice_type"], "azure-standard")
        self.assertTrue(stored["store"])

    def test_azure_realtime_native_voice(self):
        definition = sample.build_definition("azure-realtime")
        sample.validate_definition(definition, "azure-realtime")
        stored = definition.as_dict()
        self.assertEqual(stored["model"], "azure-realtime")
        self.assertEqual(
            stored["audio"]["output"]["voice"],
            "ava",
        )
        self.assertEqual(stored["audio"]["output"]["voice_type"], "azure-realtime-native")
        with self.assertRaises(ValueError):
            sample.validate_definition(definition)
        stored["audio"]["output"]["voice"] = {
            "type": "azure-standard", "name": "en-US-AvaNeural"
        }
        with self.assertRaisesRegex(ValueError, "voice_type=azure-realtime-native"):
            sample.validate_definition(VoiceAgentDefinition(stored), "azure-realtime")

    def test_azure_realtime_readback_voice_shapes(self):
        for voice in (
            {"voice": "ava", "voice_type": "azure-realtime-native"},
            {"voice": {"type": "azure-realtime-native", "name": "ava"}},
            {"voice": {"type": "azure-realtime-native", "name": "ava", "temperature": 0.8}},
        ):
            with self.subTest(voice=voice):
                stored = sample.build_definition("azure-realtime").as_dict()
                stored["audio"]["output"] = {
                    "format": {"type": "audio/pcm", "rate": 24000}, **voice,
                }
                sample.validate_definition(VoiceAgentDefinition(stored), "azure-realtime")

    def test_rejects_invalid_native_voice(self):
        for voice in (
            {"voice": "ava", "voice_type": "azure-standard"},
            {"voice": "emma", "voice_type": "azure-realtime-native"},
            {"voice": "ava"},
        ):
            with self.subTest(voice=voice):
                stored = sample.build_definition("azure-realtime").as_dict()
                stored["audio"]["output"] = {
                    "format": {"type": "audio/pcm", "rate": 24000}, **voice,
                }
                with self.assertRaisesRegex(ValueError, "voice_type=azure-realtime-native"):
                    sample.validate_definition(VoiceAgentDefinition(stored), "azure-realtime")

    def test_rejects_unknown_model(self):
        for model in ("gpt-4.1", "gpt-realtime"):
            with self.subTest(model=model), self.assertRaises(ValueError):
                sample.build_definition(model)
            with self.subTest(model=model), self.assertRaises(ValueError):
                sample.validate_definition(sample.build_definition(), model)

    def test_south_india_gpt_realtime_regional_definition(self):
        definition = sample.build_definition("gpt-realtime-regional")
        sample.validate_definition(definition, "gpt-realtime-regional")
        stored = definition.as_dict()
        self.assertEqual(stored["model"], "gpt-realtime-regional")
        self.assertEqual(stored["model_type"], "managed")
        self.assertEqual(stored["audio"]["output"]["voice"], "en-IN-Diya:DragonHDLatestNeural")
        self.assertEqual(stored["audio"]["output"]["voice_type"], "azure-standard")
        with self.assertRaises(ValueError):
            sample.validate_definition(definition)
        stored["model"] = "gpt-realtime"
        with self.assertRaises(ValueError):
            sample.validate_definition(VoiceAgentDefinition(stored), "gpt-realtime-regional")

    def test_rejects_incompatible_agents(self):
        for field, value in (
            ("model", "gpt-realtime-2.1"),
            ("model_type", "self-deployed"),
            ("kind", "prompt"),
            ("output_modalities", ["text"]),
            ("audio", {}),
        ):
            with self.subTest(field=field):
                stored = sample.build_definition().as_dict()
                stored[field] = value
                definition = (
                    PromptAgentDefinition(model=stored["model"])
                    if field == "kind"
                    else VoiceAgentDefinition(stored)
                )
                with self.assertRaises(ValueError):
                    sample.validate_definition(definition)
        stored = sample.build_definition().as_dict()
        stored["audio"]["input"]["turn_detection"]["interrupt_response"] = False
        with self.assertRaises(ValueError):
            sample.validate_definition(VoiceAgentDefinition(stored))

    async def test_lifecycle(self):
        for existing, create_only in ((None, True), (None, False), ("existing-agent", False)):
            with self.subTest(existing=existing, create_only=create_only):
                client = AsyncMock()
                client.__aenter__.return_value = client
                version = SimpleNamespace(version="1", definition=sample.build_definition())
                client.agents.create_version.return_value = version
                client.agents.get_version.return_value = version
                client.agents.get.return_value = SimpleNamespace(
                    versions=SimpleNamespace(latest=version)
                )
                with (
                    patch.object(sample, "DefaultAzureCredential", return_value=AsyncMock()),
                    patch.object(sample, "AIProjectClient", return_value=client),
                    patch.object(sample, "run_microphone_session", new_callable=AsyncMock) as microphone,
                    redirect_stdout(io.StringIO()) as output,
                ):
                    microphone.return_value = "conversation-1"
                    await sample.run(
                        "https://sample.services.ai.azure.com/api/projects/sample",
                        existing, create_only,
                    )
                self.assertIn("gpt-realtime-2.1-datazone", output.getvalue())
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

    async def test_unsupported_model_is_not_retried(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        client.agents.create_version.side_effect = RuntimeError("Model not supported in this region")
        with (
            patch.object(sample, "DefaultAzureCredential", return_value=AsyncMock()),
            patch.object(sample, "AIProjectClient", return_value=client),
            patch.object(sample, "run_microphone_session", new_callable=AsyncMock) as microphone,
        ):
            with self.assertRaisesRegex(RuntimeError, "not supported"):
                await sample.run(
                    "https://sample.services.ai.azure.com/api/projects/sample", None, True
                )
        client.agents.create_version.assert_awaited_once()
        client.agents.enable.assert_not_awaited()
        microphone.assert_not_awaited()

    async def test_azure_realtime_publication(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        version = SimpleNamespace(
            version="1", definition=sample.build_definition("azure-realtime")
        )
        client.agents.create_version.return_value = version
        client.agents.get_version.return_value = version
        with (
            patch.object(sample, "DefaultAzureCredential", return_value=AsyncMock()),
            patch.object(sample, "AIProjectClient", return_value=client),
            patch.object(sample, "run_microphone_session", new_callable=AsyncMock) as microphone,
            redirect_stdout(io.StringIO()) as output,
        ):
            await sample.run(
                "https://japan.services.ai.azure.com/api/projects/sample",
                None, True, "azure-realtime",
            )
        published = client.agents.create_version.call_args.kwargs["definition"].as_dict()
        self.assertEqual(published["model"], "azure-realtime")
        self.assertEqual(published["audio"]["output"]["voice"], "ava")
        self.assertEqual(published["audio"]["output"]["voice_type"], "azure-realtime-native")
        self.assertIn("Japan East (japaneast)", output.getvalue())
        self.assertNotIn("NOTICE:", output.getvalue())
        client.agents.enable.assert_awaited_once()
        microphone.assert_not_awaited()

    async def test_south_india_regional_publication(self):
        client = AsyncMock()
        client.__aenter__.return_value = client
        version = SimpleNamespace(
            version="1", definition=sample.build_definition("gpt-realtime-regional")
        )
        client.agents.create_version.return_value = version
        client.agents.get_version.return_value = version
        with (
            patch.object(sample, "DefaultAzureCredential", return_value=AsyncMock()),
            patch.object(sample, "AIProjectClient", return_value=client),
            patch.object(sample, "run_microphone_session", new_callable=AsyncMock) as microphone,
            redirect_stdout(io.StringIO()) as output,
        ):
            await sample.run(
                "https://india.services.ai.azure.com/api/projects/sample",
                None, True, "gpt-realtime-regional",
            )
        published = client.agents.create_version.call_args.kwargs["definition"].as_dict()
        self.assertEqual(published["model"], "gpt-realtime-regional")
        self.assertIn("South India (southindia)", output.getvalue())
        client.agents.enable.assert_awaited_once()
        microphone.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
