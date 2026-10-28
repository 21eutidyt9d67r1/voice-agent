import copy
import json
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

import yaml
from aiohttp.test_utils import TestClient, TestServer

from server import (ACTIVE, DEFAULT_TRANSCRIPTION_MODEL, LIVE_MODEL, MODELS, TRANSCRIPTION_MODELS, Settings, create_app,
                    model_definition, redact_settings, transcription_model)
from test_agent_creation import Client, Response


class ServiceClient(Client):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


class ModelTests(unittest.IsolatedAsyncioTestCase):
    def definition(self):
        return json.loads(Path(__file__).with_name("personalized-agent.json").read_text())

    def agent(self, model="gpt-5.4", version="1"):
        definition = self.definition()
        definition["model"] = model
        return {"versions": {"latest": {"version": version, "definition": definition,
                                       "metadata": {"sample": "foundry_voice_webrtc", "custom": "keep"}}}}

    def test_switching_models_preserves_prompt_tools_and_previous_definition(self):
        original = self.definition()
        snapshot = copy.deepcopy(original)
        native = model_definition(original, "azure-realtime")
        self.assertEqual(original, snapshot)
        self.assertEqual(native["audio"]["output"]["voice_type"], "azure-realtime-native")
        self.assertEqual(native["audio"]["output"]["voice"], "ava")
        restored = model_definition(native, "gpt-5.4")
        self.assertEqual(restored["audio"]["output"]["voice"], "en-US-Tyler:DragonHDLatestNeural")
        self.assertEqual(restored["audio"]["input"]["transcription"]["model"], DEFAULT_TRANSCRIPTION_MODEL)
        for model in MODELS:
            result = model_definition(original, model)
            self.assertEqual(result["instructions"], original["instructions"])
            self.assertEqual(result["greeting"], original["greeting"])
            self.assertEqual(result["tools"], original["tools"])
            self.assertEqual(result["audio"]["input"]["noise_reduction"], original["audio"]["input"]["noise_reduction"])
            self.assertEqual(transcription_model(result), DEFAULT_TRANSCRIPTION_MODEL)

    def test_transcription_catalog_default_and_overrides_match_the_ui(self):
        import re
        expected = {"azure-speech", "azure-speech-streaming", "azure-llm-speech", "mai-transcribe",
                    "mai-transcribe-2", "mai-transcribe-2-streaming", "gpt-live-transcribe",
                    "gpt-realtime-whisper", "gpt-transcribe", "gpt-4o-transcribe",
                    "gpt-4o-mini-transcribe", "gpt-4o-transcribe-diarize", "whisper-1"}
        self.assertEqual(TRANSCRIPTION_MODELS, expected)
        self.assertEqual(DEFAULT_TRANSCRIPTION_MODEL, "mai-transcribe-2")
        self.assertEqual(transcription_model(self.definition()), DEFAULT_TRANSCRIPTION_MODEL)
        html = Path(__file__).with_name("public").joinpath("index.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="agent-transcription-choice".*?</select>', html, re.S).group()
        self.assertEqual(set(re.findall(r'<option value="([^"]+)"', select)), expected)
        self.assertIn('<option value="mai-transcribe-2" selected>', select)
        original = self.definition()
        for choice in expected:
            changed = model_definition(original, original["model"], choice)
            self.assertEqual(transcription_model(changed), choice)
            self.assertEqual(changed["audio"]["input"]["transcription"]["language"], "en-US")
            self.assertEqual(changed["instructions"], original["instructions"])
            self.assertEqual(changed["audio"]["output"], original["audio"]["output"])
            for model in MODELS:
                self.assertEqual(transcription_model(model_definition(changed, model)), choice)

    def test_standard_voice_models_and_model_catalog_match_ui(self):
        import re
        html = Path(__file__).with_name("public").joinpath("index.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="agent-model-choice".*?</select>', html, re.S).group()
        self.assertEqual(set(re.findall(r'<option value="([^"]+)"', select)), MODELS | {LIVE_MODEL})
        original = self.definition()
        native = model_definition(original, "azure-realtime")
        for model in ("azure-realtime-flash-2026-10-14", "gpt-realtime-2.1-mini"):
            with self.subTest(model=model):
                self.assertIn(model, MODELS)
                changed = model_definition(original, model)
                self.assertEqual(changed["model"], model)
                self.assertEqual(changed["model_type"], "managed")
                self.assertEqual(changed["audio"]["output"], original["audio"]["output"])
                restored = model_definition(native, model)
                self.assertEqual(restored["audio"]["output"]["voice"], "en-US-Tyler:DragonHDLatestNeural")
                self.assertEqual(restored["audio"]["output"]["voice_type"], "azure-standard")

    async def test_standard_voice_models_can_be_saved_without_deleting_previous_versions(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        for model in ("azure-realtime-flash-2026-10-14", "gpt-realtime-2.1-mini"):
            with self.subTest(model=model):
                service = ServiceClient([Response(200, self.agent()), Response(200, self.agent(model, "2"))],
                                        [Response(201, {"version": "2"}), Response(204)])
                async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
                    config = await (await client.get("/api/config")).json()
                    self.assertIn(model, config["models"])
                    with patch("server.aiohttp.ClientSession", return_value=service):
                        response = await client.post("/api/agent/model",
                            headers={"Origin": str(client.make_url("")).rstrip("/")},
                            json={"model": model, "version": "1"})
                        result = await response.json()
                self.assertEqual(response.status, 200, result)
                self.assertEqual(result["model"], model)
                published = service.writes[0][1]["json"]
                self.assertEqual(published["definition"]["model"], model)
                self.assertEqual(published["definition"]["audio"]["output"]["voice_type"], "azure-standard")
                self.assertEqual(published["metadata"]["custom"], "keep")
                self.assertEqual(service.removals, [])

    async def test_transcription_only_versions_preserve_native_voice_and_other_settings(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        for choice in TRANSCRIPTION_MODELS:
            with self.subTest(choice=choice):
                agent = self.agent("azure-realtime")
                original = agent["versions"]["latest"]["definition"]
                original["audio"]["output"] = {"voice": "emma", "voice_type": "azure-realtime-native",
                                              "format": {"type": "audio/pcm", "rate": 24000}}
                original["audio"]["input"]["transcription"]["model"] = (
                    "azure-speech" if choice == "whisper-1" else "whisper-1")
                saved = copy.deepcopy(agent)
                saved["versions"]["latest"]["version"] = "2"
                saved["versions"]["latest"]["definition"]["audio"]["input"]["transcription"]["model"] = choice
                service = ServiceClient([Response(200, agent), Response(200, saved)],
                                        [Response(201, {"version": "2"}), Response(204)])
                async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
                    with patch("server.aiohttp.ClientSession", return_value=service):
                        response = await client.post("/api/agent/model",
                            headers={"Origin": str(client.make_url("")).rstrip("/")},
                            json={"model": "azure-realtime", "version": "1", "transcriptionModel": choice})
                        result = await response.json()
                self.assertEqual(response.status, 200, result)
                self.assertEqual(result["version"], "2")
                self.assertEqual(result["transcriptionModel"], choice)
                changed = service.writes[0][1]["json"]["definition"]
                expected = copy.deepcopy(original)
                expected["audio"]["input"]["transcription"]["model"] = choice
                self.assertEqual(changed, expected)
                self.assertEqual(service.writes[0][1]["json"]["metadata"]["custom"], "keep")
                self.assertEqual(service.removals, [])

    async def test_same_transcription_is_idempotent_and_invalid_choices_never_request_credentials(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        tokens = AsyncMock()
        async with TestClient(TestServer(create_app(cfg, tokens))) as client:
            origin = {"Origin": str(client.make_url("")).rstrip("/")}
            for choice in ("unknown", None, [], {}, 1, ""):
                response = await client.post("/api/agent/model", headers=origin,
                    json={"model": "gpt-5.4", "version": "1", "transcriptionModel": choice})
                self.assertEqual(response.status, 400)
            tokens.get_token.assert_not_awaited()
            agent = self.agent()
            service = ServiceClient([Response(200, agent), Response(200, agent)], [Response(204)])
            with patch("server.aiohttp.ClientSession", return_value=service):
                response = await client.post("/api/agent/model", headers=origin,
                    json={"model": "gpt-5.4", "version": "1", "transcriptionModel": DEFAULT_TRANSCRIPTION_MODEL})
            self.assertEqual(response.status, 200)
            self.assertFalse(any("/versions" in url for url, _ in service.writes))

    async def test_changed_readback_is_not_reported_as_a_successful_transcription_save(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        service = ServiceClient([Response(200, self.agent()), Response(200, self.agent(version="3"))],
                                [Response(201, {"version": "2"}), Response(204)])
        async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
            with patch("server.aiohttp.ClientSession", return_value=service):
                response = await client.post("/api/agent/model",
                    headers={"Origin": str(client.make_url("")).rstrip("/")},
                    json={"model": "gpt-5.4", "version": "1", "transcriptionModel": "azure-speech"})
                result = await response.json()
        self.assertEqual(response.status, 502)
        self.assertIn("could not be verified", result["error"])

    def test_explicitly_disabled_turn_detection_is_preserved(self):
        original = self.definition()
        original["audio"]["input"]["turn_detection"] = None
        self.assertIsNone(model_definition(original, "gpt-5.4")["audio"]["input"]["turn_detection"])

    async def test_save_new_model_version_then_enable_without_deleting(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        service = ServiceClient([Response(200, self.agent()), Response(200, self.agent("azure-realtime", "2"))],
                                [Response(201, {"version": "2"}), Response(204)])
        async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
            origin = {"Origin": str(client.make_url("")).rstrip("/")}
            with patch("server.aiohttp.ClientSession", return_value=service):
                response = await client.post("/api/agent/model", headers=origin,
                    json={"model": "azure-realtime", "version": "1"})
                result = await response.json()
        self.assertEqual(response.status, 200, result)
        self.assertEqual(result["version"], "2")
        self.assertEqual(result["model"], "azure-realtime")
        self.assertEqual(service.removals, [])
        self.assertEqual(service.writes[0][1]["json"]["metadata"]["custom"], "keep")
        definition = service.writes[0][1]["json"]["definition"]
        self.assertEqual(definition["audio"]["output"]["voice_type"], "azure-realtime-native")
        self.assertIn(":enable", service.writes[1][0])

    async def test_stale_version_and_same_model_do_not_publish_an_extra_version(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        for expected, version in ((409, "old"), (200, "1")):
            agent = self.agent()
            service = ServiceClient([Response(200, agent), Response(200, agent)], [Response(204)])
            async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
                with patch("server.aiohttp.ClientSession", return_value=service):
                    response = await client.post("/api/agent/model",
                        headers={"Origin": str(client.make_url("")).rstrip("/")},
                        json={"model": "gpt-5.4", "version": version})
                    self.assertEqual(response.status, expected)
            self.assertFalse(any("/versions" in url for url, _ in service.writes))

    async def test_invalid_requests_untrusted_origins_and_active_calls_are_blocked(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        tokens = AsyncMock()
        app = create_app(cfg, tokens)
        async with TestClient(TestServer(app)) as client:
            origin = {"Origin": str(client.make_url("")).rstrip("/")}
            for body in ({}, [], {"model": "unknown", "version": "1"},
                         {"model": "gpt-4.1", "version": "1"},
                         {"model": "gpt-5.4", "version": "1", "definition": {}}):
                response = await client.post("/api/agent/model", headers=origin, json=body)
                self.assertEqual(response.status, 400)
            response = await client.post("/api/agent/model", json={"model": "gpt-5.4", "version": "1"})
            self.assertEqual(response.status, 403)
            app[ACTIVE].active = True
            response = await client.post("/api/agent/model", headers=origin,
                                         json={"model": "gpt-5.4", "version": "1"})
            self.assertEqual(response.status, 409)
            tokens.get_token.assert_not_awaited()

    async def test_settings_yaml_uses_saved_version_and_redacts_credentials(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        latest = self.agent()["versions"]["latest"]
        latest["definition"]["tools"].append({"type": "mcp", "headers": {"Authorization": "do-not-export"}})
        async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
            with patch("server.lookup_configured_agent", AsyncMock(return_value=latest)):
                response = await client.get("/api/agent/settings")
                result = await response.json()
        self.assertEqual(response.status, 200)
        self.assertNotIn("do-not-export", result["yaml"])
        self.assertIn("instructions: |", result["yaml"])
        settings = yaml.safe_load(result["yaml"])
        self.assertEqual(result["transcriptionModel"], DEFAULT_TRANSCRIPTION_MODEL)
        self.assertEqual(settings["version"], "1")
        self.assertEqual(settings["definition"]["model"], "gpt-5.4")
        self.assertEqual(redact_settings({"api-key": "secret"}), {"api-key": "[redacted]"})
