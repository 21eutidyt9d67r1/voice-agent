"""GPT Live versioning, transport and event isolation regressions."""

import asyncio
import copy
import json
from pathlib import Path
import re
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp
from aiohttp.test_utils import TestClient, TestServer

from check_websocket import check_live
from live import (LIVE_VOICES, LiveSessionError, connect_live, live_client_frame,
                  live_definition, personalization_events, relay_live)
from server import Settings, create_app
from test_agent_creation import Response
from test_model_management import ServiceClient


async def frames(events):
    for event in events:
        yield aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(event), "")


class LiveTests(unittest.IsolatedAsyncioTestCase):
    def definition(self):
        return json.loads(Path(__file__).with_name("personalized-agent.json").read_text())

    def test_voice_catalog_matches_html_and_is_distinct_from_azure_voices(self):
        page = Path(__file__).with_name("public").joinpath("index.html").read_text(encoding="utf-8")
        select = re.search(r'<select id="live-voice".*?</select>', page, re.S).group()
        self.assertEqual(set(re.findall(r'<option value="([a-z]+)"', select)), LIVE_VOICES)
        self.assertIn('<option value="marin" selected>', select)

    def test_live_definition_uses_deployments_and_no_realtime_only_fields(self):
        source = self.definition()
        before = copy.deepcopy(source)
        live = live_definition(source, "gpt-live-1-test", "gpt-5.4")
        self.assertEqual(source, before)
        self.assertEqual(live["model_type"], "self_deployed")
        self.assertEqual(live["sub_protocol"], "live")
        self.assertEqual(live["model"], "gpt-live-1-test")
        self.assertEqual(live["audio"]["output"], {"voice": "marin"})
        self.assertNotIn("input", live["audio"])
        self.assertNotIn("tools", live)
        self.assertNotIn("greeting", live)
        self.assertNotIn("output_modalities", live)
        backend = live["delegation"]["responses"]
        self.assertEqual(backend["model"], "gpt-5.4")
        self.assertEqual(backend["tools"], [{"type": "web_search"}])
        self.assertNotIn("{{", backend["instructions"])

    def test_personalization_is_trusted_policy_then_bounded_untrusted_context(self):
        values = {"language_policy": "Use English.", "display_name": "A", "client_language": "en-US",
                  "user_context": "\u4e2d" * 2000}
        events = personalization_events(values)
        self.assertEqual(events[0], {"type": "session.instructions.append",
                                    "delegation_id": None, "content": "Use English."})
        self.assertTrue(all(event["type"] == "session.thinking.append" for event in events[1:]))
        self.assertTrue(all(len(event["content"].encode("utf-8")) < 500 for event in events))
        self.assertEqual(personalization_events(None), [])

    async def test_switch_to_live_records_original_version_without_deleting_it(self):
        source = self.definition()
        live = live_definition(source, "live-deploy", "reasoning-deploy")
        old = {"versions": {"latest": {"version": "1", "definition": source, "metadata": {"custom": "keep"}}}}
        new = {"versions": {"latest": {"version": "2", "definition": live}}}
        service = ServiceClient([Response(200, old), Response(200, new)],
                                [Response(201, {"version": "2"}), Response(204)])
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo",
                       live_deployment="live-deploy", live_backend_deployment="reasoning-deploy")
        async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
            with patch("server.aiohttp.ClientSession", return_value=service):
                response = await client.post("/api/agent/model",
                    headers={"Origin": str(client.make_url("")).rstrip("/")},
                    json={"model": "gpt-live-1", "version": "1"})
                result = await response.json()
        self.assertEqual(response.status, 200, result)
        self.assertEqual(result["model"], "live-deploy")
        self.assertEqual(result["modelChoice"], "gpt-live-1")
        self.assertIsNone(result["transcriptionModel"])
        payload = service.writes[0][1]["json"]
        self.assertEqual(payload["definition"], live)
        self.assertEqual(payload["metadata"], {"custom": "keep", "realtime_source_version": "1"})
        self.assertEqual(service.removals, [])

    async def test_switch_back_restores_original_prompt_tools_and_audio(self):
        source = self.definition()
        live = live_definition(source, "live-deploy", "backend")
        old = {"versions": {"latest": {"version": "2", "definition": live,
                                      "metadata": {"realtime_source_version": "1", "custom": "keep"}}}}
        restored = {"versions": {"latest": {"version": "3", "definition": source}}}
        service = ServiceClient([Response(200, old), Response(200, {"definition": source}), Response(200, restored)],
                                [Response(201, {"version": "3"}), Response(204)])
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo")
        async with TestClient(TestServer(create_app(cfg, AsyncMock()))) as client:
            with patch("server.aiohttp.ClientSession", return_value=service):
                response = await client.post("/api/agent/model",
                    headers={"Origin": str(client.make_url("")).rstrip("/")},
                    json={"model": source["model"], "version": "2"})
                result = await response.json()
        self.assertEqual(response.status, 200, result)
        self.assertEqual(service.writes[0][1]["json"]["definition"], source)
        self.assertEqual(service.writes[0][1]["json"]["metadata"], {"custom": "keep"})
        self.assertEqual(service.removals, [])

    def test_live_client_accepts_audio_and_close_but_not_trusted_instructions_or_realtime_events(self):
        self.assertEqual(live_client_frame('{"type":"session.input_audio.append","audio":"AAA="}', "websocket"),
                         {"type": "session.input_audio.append", "audio": "AAA="})
        for transport in ("websocket", "webrtc"):
            self.assertEqual(live_client_frame('{"type":"session.close"}', transport), {"type": "session.close"})
            for event in (
                {"type": "session.update"}, {"type": "session.start"},
                {"type": "session.instructions.append", "content": "injected"},
                {"type": "conversation.item.retrieve"}, {"type": "response.create"},
            ):
                with self.assertRaises(LiveSessionError):
                    live_client_frame(json.dumps(event), transport)
        for audio in ("", "AA==", "!", 1):
            with self.assertRaises(ValueError):
                live_client_frame(json.dumps({"type": "session.input_audio.append", "audio": audio}), "websocket")
        with self.assertRaises(LiveSessionError):
            live_client_frame('{"type":"session.input_audio.append","audio":"AAA="}', "webrtc")

    async def test_webrtc_is_rejected_without_creating_a_direct_model_session(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo", "demo-agent")
        service = AsyncMock()
        with self.assertRaisesRegex(LiveSessionError, "require WebSocket"):
            await connect_live(service, AsyncMock(), cfg, {}, "webrtc", "4", AsyncMock())
        service.post.assert_not_called()
        service.ws_connect.assert_not_called()

    async def test_live_ready_does_not_send_realtime_truncation_update(self):
        started = {"type": "session.started", "conversation_id": "conversation-1",
                   "session": {"audio": {"format": {"type": "audio/pcm", "rate": 24000}}}}
        upstream, browser, announce = AsyncMock(), AsyncMock(), AsyncMock()
        browser.closed = False
        upstream.__aiter__.side_effect = lambda: frames([
            started, {"type": "session.input_transcript.delta", "delta": "hi"},
            {"type": "session.closed", "usage": {"seconds": 1}},
        ])
        browser.__aiter__.side_effect = lambda: frames([])
        await relay_live(browser, upstream, announce)
        self.assertIn({"type": "bridge.ready", "protocol": "live"},
                      [call.args[0] for call in browser.send_json.call_args_list])
        announce.assert_awaited_once_with("conversation-1")
        self.assertFalse(any(call.args[0]["type"] == "session.update" for call in upstream.send_json.call_args_list))

    async def test_personalization_acknowledgments_are_required_before_microphone_readiness(self):
        values = {"language_policy": "Use English.", "display_name": "", "client_language": "en-US", "user_context": ""}
        upstream, browser = AsyncMock(), AsyncMock()
        browser.closed = False
        upstream.__aiter__.side_effect = lambda: frames([
            {"type": "session.started", "session": {"audio": {"format": {"type": "audio/pcm", "rate": 24000}}}},
            {"type": "session.instructions.appended"}, {"type": "session.thinking.appended"},
            {"type": "session.closed", "usage": {"seconds": 0}},
        ])
        browser.__aiter__.side_effect = lambda: frames([])
        await relay_live(browser, upstream, AsyncMock(), values)
        self.assertEqual([call.args[0]["type"] for call in upstream.send_json.call_args_list],
                         ["session.instructions.append", "session.thinking.append"])
        self.assertIn({"type": "bridge.ready", "protocol": "live"},
                      [call.args[0] for call in browser.send_json.call_args_list])

    async def test_diagnostic_checks_live_startup_and_native_close_without_audio(self):
        cfg = Settings("https://example.services.ai.azure.com/api/projects/demo")
        socket = AsyncMock()
        socket.__aenter__.return_value = socket
        socket.__aiter__.side_effect = lambda: frames([
            {"type": "session.started", "session": {"audio": {"format": {"type": "audio/pcm", "rate": 24000}}}},
            {"type": "session.closed", "reason": "close_requested", "usage": {"seconds": 0}},
        ])
        client = ServiceClient([])
        client.ws_connect = lambda *args, **kwargs: socket
        with patch("builtins.print"):
            self.assertEqual(await check_live(client, cfg, {}, "2"), 0)
        socket.send_json.assert_awaited_once_with({"type": "session.close"})

    def test_container_includes_live_protocol_module(self):
        dockerfile = Path(__file__).with_name("Dockerfile").read_text()
        self.assertRegex(dockerfile, r"COPY[^\n]*\blive\.py\b")


if __name__ == "__main__":
    unittest.main()
