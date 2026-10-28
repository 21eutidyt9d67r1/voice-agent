"""Offline session configuration and retained-item retrieval protocol checks."""

import copy
import json
import unittest
from unittest.mock import AsyncMock, patch

import aiohttp

from server import (FLASH_MODEL, SessionConfiguration, SessionConfigurationError, TRUNCATED_ITEM_INCLUDE,
                    forward_browser, forward_upstream, truncation_update, validate_client_frame)


def saved_session(stable):
    vad = {"type": "azure_semantic_vad", "threshold": 0.6, "create_response": True,
           "interrupt_response": False, "auto_truncate": False,
           "appended_text_after_truncation": " [Interrupted]"}
    session = {"id": "session_one", "include": ["existing.selector"], "instructions": "Saved instructions",
               "model": "saved-model", "voice": "saved-voice"}
    if stable:
        session.update(type="realtime", audio={"input": {"turn_detection": vad,
                       "format": {"type": "audio/pcm", "rate": 24000}}, "output": {"voice": "saved-voice"}})
    else:
        session["turn_detection"] = vad
    return session


async def frames(events):
    for event in events:
        yield aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(event), "")


class ConfigurationTests(unittest.IsolatedAsyncioTestCase):
    async def test_flash_disables_truncation_and_removes_retained_selector_for_both_shapes(self):
        for stable in (True, False):
            with self.subTest(stable=stable):
                original = saved_session(stable)
                original["model"] = FLASH_MODEL
                original["include"] += [TRUNCATED_ITEM_INCLUDE, TRUNCATED_ITEM_INCLUDE]
                original_vad = original["audio"]["input"]["turn_detection"] if stable else original["turn_detection"]
                original_vad["auto_truncate"] = True
                untouched = copy.deepcopy(original)
                config, upstream = SessionConfiguration(), AsyncMock()
                self.assertFalse(await config.observe({"type": "session.updated", "session": original}, upstream))
                update = upstream.send_json.call_args.args[0]["session"]
                vad = update["audio"]["input"]["turn_detection"] if stable else update["turn_detection"]
                self.assertEqual(vad, {**original_vad, "auto_truncate": False, "interrupt_response": True})
                self.assertEqual(update["include"], ["existing.selector"])
                self.assertEqual(original, untouched)
                ack = {"id": original["id"], **copy.deepcopy(update)}
                for bad in ("auto_truncate", "interrupt_response", "include", "id"):
                    invalid = copy.deepcopy(ack)
                    invalid_vad = invalid["audio"]["input"]["turn_detection"] if stable else invalid["turn_detection"]
                    if bad == "auto_truncate":
                        invalid_vad["auto_truncate"] = True
                    elif bad == "interrupt_response":
                        invalid_vad["interrupt_response"] = False
                    elif bad == "include":
                        invalid["include"].append(TRUNCATED_ITEM_INCLUDE)
                    else:
                        invalid["id"] = "another-session"
                    with self.assertRaises(SessionConfigurationError):
                        await config.observe({"type": "session.updated", "session": invalid}, upstream)
                    self.assertFalse(config.ready)
                self.assertTrue(await config.observe({"type": "session.updated", "session": ack}, upstream))
                self.assertFalse(await config.observe({"type": "session.updated", "session": ack}, upstream))

    async def test_flash_ready_after_disable_ack_for_both_transports(self):
        for transport in ("websocket", "webrtc"):
            original = saved_session(transport == "websocket")
            original["model"] = "azure-realtime-flash-1"
            config, upstream, browser = SessionConfiguration(), AsyncMock(), AsyncMock()
            upstream.__aiter__.side_effect = lambda: frames([
                {"type": "session.updated", "session": original},
                {"type": "session.updated", "session": {**original, **truncation_update(original)["session"]}},
            ])
            await forward_upstream(upstream, browser, transport, config)
            self.assertTrue(config.ready)
            browser.send_json.assert_awaited_once_with({"type": "bridge.ready"})

    async def test_saved_settings_preserved_and_ack_required_for_both_shapes(self):
        for stable in (True, False):
            with self.subTest(stable=stable):
                original = saved_session(stable)
                untouched = copy.deepcopy(original)
                config, upstream = SessionConfiguration(), AsyncMock()
                self.assertFalse(await config.observe({"type": "session.created", "session": original}, upstream))
                upstream.send_json.assert_not_awaited()
                self.assertFalse(await config.observe({"type": "session.updated", "session": original}, upstream))
                self.assertFalse(config.ready)
                self.assertEqual(original, untouched)
                update = upstream.send_json.call_args.args[0]
                expected_keys = {"type", "audio", "include"} if stable else {"turn_detection", "include"}
                self.assertEqual(set(update["session"]), expected_keys)
                self.assertEqual(update["session"]["include"], ["existing.selector", TRUNCATED_ITEM_INCLUDE])
                vad = update["session"]["audio"]["input"]["turn_detection"] if stable else update["session"]["turn_detection"]
                original_vad = original["audio"]["input"]["turn_detection"] if stable else original["turn_detection"]
                self.assertEqual(vad, {**original_vad, "auto_truncate": True, "interrupt_response": True})
                ack = {"type": "session.updated", "session": {**original, **update["session"]}}
                self.assertTrue(await config.observe(ack, upstream))
                self.assertTrue(config.ready)
                self.assertFalse(await config.observe(ack, upstream))
                upstream.send_json.assert_awaited_once()

    async def test_missing_flags_selectors_and_wrong_session_cannot_ack(self):
        for stable in (True, False):
            for missing in ("auto_truncate", "interrupt_response", "include", "existing", "id"):
                config, upstream = SessionConfiguration(), AsyncMock()
                original = saved_session(stable)
                await config.observe({"type": "session.updated", "session": original}, upstream)
                ack = {"id": original["id"], **copy.deepcopy(config.update["session"])}
                vad = ack["audio"]["input"]["turn_detection"] if stable else ack["turn_detection"]
                if missing in vad:
                    vad[missing] = False
                elif missing == "existing":
                    ack["include"] = [TRUNCATED_ITEM_INCLUDE]
                else:
                    ack.pop(missing)
                with self.subTest(stable=stable, missing=missing), self.assertRaises(SessionConfigurationError):
                    await config.observe({"type": "session.updated", "session": ack}, upstream)
                self.assertFalse(config.ready)

    def test_include_union_and_invalid_vad(self):
        for stable in (True, False):
            session = saved_session(stable)
            session["include"] = [TRUNCATED_ITEM_INCLUDE, "existing.selector", TRUNCATED_ITEM_INCLUDE]
            self.assertEqual(truncation_update(session)["session"]["include"],
                             [TRUNCATED_ITEM_INCLUDE, "existing.selector"])
            for vad in (None, {}, {"type": "server_vad", "create_response": False}):
                invalid = {"audio": {"input": {"turn_detection": vad}}} if stable else {"turn_detection": vad}
                with self.assertRaises(SessionConfigurationError):
                    truncation_update(invalid)
            session["include"] = "not a list"
            with self.assertRaises(SessionConfigurationError):
                truncation_update(session)

    async def test_unset_initial_include_accepts_null_but_ack_still_requires_selector(self):
        for stable in (True, False):
            for initial in (None, []):
                original = saved_session(stable)
                original["include"] = initial
                config, upstream = SessionConfiguration(), AsyncMock()
                await config.observe({"type": "session.updated", "session": original}, upstream)
                self.assertEqual(config.update["session"]["include"], [TRUNCATED_ITEM_INCLUDE])
                self.assertEqual(original["include"], initial)
                ack = {"id": original["id"], **copy.deepcopy(config.update["session"])}
                for invalid in (None, [], "not a list"):
                    with self.subTest(stable=stable, initial=initial, ack=invalid):
                        with self.assertRaises(SessionConfigurationError):
                            await config.observe({"type": "session.updated", "session": {**ack, "include": invalid}}, upstream)
                        self.assertFalse(config.ready)
                self.assertTrue(await config.observe({"type": "session.updated", "session": ack}, upstream))
                self.assertTrue(config.ready)

    async def test_bridge_ready_only_after_ack_and_preserves_transport_audio_filtering(self):
        for transport in ("websocket", "webrtc"):
            original = saved_session(transport == "websocket")
            config = SessionConfiguration()
            upstream = AsyncMock()
            upstream.__aiter__.side_effect = lambda: frames([
                {"type": "session.created", "session": original},
                {"type": "session.updated", "session": original},
                {"type": "session.updated", "session": {**original, **truncation_update(original)["session"]}},
                {"type": "response.output_audio.delta", "delta": "AAA="},
                {"type": "conversation.item.truncated", "item_id": "assistant_1"},
            ])
            browser = AsyncMock()
            await forward_upstream(upstream, browser, transport, config)
            browser.send_json.assert_awaited_once_with({"type": "bridge.ready"})
            forwarded = [json.loads(call.args[0])["type"] for call in browser.send_str.call_args_list]
            self.assertEqual(forwarded[:3], ["session.created", "session.updated", "session.updated"])
            self.assertEqual("response.output_audio.delta" in forwarded, transport == "websocket")
            self.assertEqual(forwarded[-1], "conversation.item.truncated")

    async def test_configuration_timeout_is_explicit(self):
        class Deadline:
            async def __aenter__(self):
                raise TimeoutError()

            async def __aexit__(self, *args):
                pass

        with patch("server.asyncio.timeout", return_value=Deadline()):
            with self.assertRaisesRegex(SessionConfigurationError, "Timed out"):
                await forward_upstream(AsyncMock(), AsyncMock(), "websocket", SessionConfiguration())

    async def test_input_before_ack_rejected_but_sdp_and_retrieval_allowed(self):
        text = {"type": "conversation.item.create", "item": {"type": "message", "role": "user",
                "content": [{"type": "input_text", "text": "Hello"}]}}
        offer = {"type": "rtc.call.sdp.create", "sdp_offer": "v=0\r\n"}
        retrieve = {"type": "conversation.item.retrieve", "item_id": "assistant_1", "event_id": "lookup_1"}
        for transport in ("websocket", "webrtc"):
            prefix = [offer] if transport == "webrtc" else []
            upstream = AsyncMock()
            with self.assertRaises(SessionConfigurationError):
                await forward_browser(frames(prefix + [text]), upstream, transport, SessionConfiguration())
            upstream = AsyncMock()
            await forward_browser(frames([retrieve] + prefix), upstream, transport, SessionConfiguration())
            self.assertEqual(upstream.send_json.await_count, len(prefix) + 1)
        with self.assertRaises(SessionConfigurationError):
            await forward_browser(frames([{"type": "input_audio_buffer.append", "audio": "AAA="}]),
                                  AsyncMock(), "websocket", SessionConfiguration())

    def test_retrieval_is_validated_and_configuration_is_not_browser_controlled(self):
        for transport in ("websocket", "webrtc"):
            frame = {"type": "conversation.item.retrieve", "item_id": "item_" + "x" * 60, "event_id": "retrieve_1"}
            self.assertEqual(validate_client_frame(json.dumps({**frame, "extra": "ignored"}), True, transport), frame)
            for field in ("item_id", "event_id"):
                for value in (None, "", "bad id", "x" * 257, 123):
                    with self.assertRaises(ValueError):
                        validate_client_frame(json.dumps({**frame, field: value}), True, transport)
            with self.assertRaises(ValueError):
                validate_client_frame(json.dumps({"type": "session.update", "session": {"include": []}}), True, transport)


if __name__ == "__main__":
    unittest.main()
