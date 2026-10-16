"""Offline validation of browser text events for both voice transports."""

import json
import unittest

import aiohttp

from server import forward_browser, validate_client_frame


def text_frame(text="Hello", **fields):
    return {"type": "conversation.item.create", "item": {
        "id": "msg_123", "type": "message", "role": "user",
        "content": [{"type": "input_text", "text": text}], **fields,
    }}


class TextInputTests(unittest.TestCase):
    def validate(self, frame, transport):
        return validate_client_frame(json.dumps(frame), True, transport)

    def test_text_and_response_for_both_transports(self):
        for transport in ("websocket", "webrtc"):
            with self.subTest(transport=transport):
                for text in ("Hello", "x" * 4000, "Hello \u4e16\u754c"):
                    frame = text_frame(text)
                    self.assertEqual(self.validate(frame, transport), frame)
                self.assertEqual(self.validate({"type": "response.create"}, transport),
                                 {"type": "response.create"})
                response = {"type": "response.create", "response": {"output_modalities": ["text"]}}
                key = "modalities" if transport == "webrtc" else "output_modalities"
                self.assertEqual(self.validate(response, transport),
                                 {"type": "response.create", "response": {key: ["text"]}})

    def test_invalid_text_and_configuration_are_rejected(self):
        invalid = [
            text_frame(""), text_frame(" \n "), text_frame("x" * 4001),
            text_frame(None), text_frame(123),
            text_frame(role="system"), text_frame(type="function_call"),
            text_frame(id="bad id"), text_frame(id="x" * 33),
            text_frame(id="msg_12345678-1234-1234-1234-123456789abc"),
            text_frame(content=[]), text_frame(content=[None]),
            text_frame(content=[{"type": "input_audio", "text": "Hello"}]),
            text_frame(content=[{"type": "input_text", "text": "Hi"}] * 2),
            {"type": "conversation.item.create", "item": None},
            {"type": "response.create", "response": {"instructions": "override"}},
            {"type": "response.create", "response": {"output_modalities": ["audio"]}},
            {"type": "response.create", "response": {"output_modalities": ["text"], "instructions": "override"}},
            {"type": "session.update", "session": {}},
        ]
        for transport in ("websocket", "webrtc"):
            for frame in invalid:
                with self.subTest(transport=transport, frame=frame):
                    with self.assertRaises(ValueError):
                        self.validate(frame, transport)

    def test_item_id_length_boundary(self):
        for transport in ("websocket", "webrtc"):
            for length in (1, 32):
                frame = text_frame(id="a" * length)
                self.assertEqual(self.validate(frame, transport), frame)
            for length in (0, 33, 40):
                with self.subTest(transport=transport, length=length):
                    with self.assertRaises(ValueError):
                        self.validate(text_frame(id="a" * length), transport)

    def test_text_payload_is_sanitized(self):
        for transport in ("websocket", "webrtc"):
            frame = text_frame(instructions="override")
            frame["previous_item_id"] = "other"
            frame["item"]["content"][0]["extra"] = "ignored"
            self.assertEqual(self.validate(frame, transport), text_frame())

    def test_webrtc_still_requires_one_sdp_offer_first(self):
        offer = {"type": "rtc.call.sdp.create", "sdp_offer": "v=0\r\n"}
        self.assertEqual(validate_client_frame(json.dumps(offer), False, "webrtc"), offer)
        for frame in (text_frame(), {"type": "response.create"}):
            with self.assertRaises(ValueError):
                validate_client_frame(json.dumps(frame), False, "webrtc")
        with self.assertRaises(ValueError):
            self.validate(offer, "webrtc")

    def test_websocket_audio_still_supported(self):
        frame = {"type": "input_audio_buffer.append", "audio": "AAA="}
        self.assertEqual(self.validate(frame, "websocket"), frame)
        with self.assertRaises(ValueError):
            self.validate(frame, "webrtc")


class TextRelayTests(unittest.IsolatedAsyncioTestCase):
    async def test_both_transports_forward_text_and_request_in_order(self):
        for transport in ("websocket", "webrtc"):
            frames = []
            if transport == "webrtc":
                frames.append({"type": "rtc.call.sdp.create", "sdp_offer": "v=0\r\n"})
            frames.extend([text_frame(), {"type": "response.create", "response": {"output_modalities": ["text"]}}])

            async def browser():
                for frame in frames:
                    yield aiohttp.WSMessage(aiohttp.WSMsgType.TEXT, json.dumps(frame), "")

            class Upstream:
                def __init__(self):
                    self.sent = []

                async def send_json(self, frame):
                    self.sent.append(frame)

            upstream = Upstream()
            await forward_browser(browser(), upstream, transport)
            expected = frames[:-1] + [{"type": "response.create", "response": {
                "modalities" if transport == "webrtc" else "output_modalities": ["text"],
            }}]
            self.assertEqual(upstream.sent, expected)


if __name__ == "__main__":
    unittest.main()
