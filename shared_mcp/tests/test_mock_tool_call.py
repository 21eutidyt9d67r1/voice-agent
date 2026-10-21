from __future__ import annotations

import asyncio
import json
import socket
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
if APP.is_dir() and str(APP) not in sys.path:
    sys.path.insert(0, str(APP))

from mcp.server.fastmcp import FastMCP  # noqa: E402
from mcp.server.fastmcp.exceptions import ToolError  # noqa: E402

from shared_mcp.mock_tool_call import pack  # noqa: E402
from shared_mcp.mock_tool_call.server import register_tools  # noqa: E402
from shared_mcp.mock_tool_call.service import MockToolCallService  # noqa: E402
from shared_mcp.mock_tool_call.store import (  # noqa: E402
    MemoryStateStore,
    RedisStateStore,
    store_from_environment,
)

# Tuesday 2026-10-20 10:00 Pacific.
NOW = datetime(2026, 10, 20, 17, 0, tzinfo=timezone.utc)


def build(store: Any = None) -> FastMCP:
    mcp = FastMCP("mock-tool-call")
    register_tools(mcp, MockToolCallService(store or MemoryStateStore(), clock=lambda: NOW))
    return mcp


def call(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    result = asyncio.run(mcp.call_tool(name, arguments))
    if isinstance(result, tuple):
        content, structured = result
        if structured is not None:
            text = json.loads(content[0].text)
            assert text == structured, (text, structured)
            return structured
        return json.loads(content[0].text)
    if isinstance(result, dict):
        return result
    return json.loads(result[0].text)


def tools(mcp: FastMCP) -> dict[str, Any]:
    return {tool.name: tool for tool in asyncio.run(mcp.list_tools())}


class FakeRedis:
    def __init__(self) -> None:
        self.values: dict[str, Any] = {}
        self.sets: dict[str, set[str]] = {}
        self.ttl: dict[str, int] = {}

    def get(self, key: str) -> Any:
        return self.values.get(key)

    def set(self, key: str, value: Any, ex: int | None = None, nx: bool = False) -> bool:
        if nx and key in self.values:
            return False
        self.values[key] = str(value)
        if ex:
            self.ttl[key] = ex
        return True

    def sadd(self, key: str, member: str) -> None:
        self.sets.setdefault(key, set()).add(member)

    def smembers(self, key: str) -> set[str]:
        return set(self.sets.get(key, set()))

    def expire(self, key: str, seconds: int) -> None:
        self.ttl[key] = seconds

    def incr(self, key: str) -> int:
        self.values[key] = str(int(self.values.get(key, 0)) + 1)
        return int(self.values[key])


class EchoContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mcp = build()

    def test_inventory_uses_the_pack_prefix(self) -> None:
        names = set(tools(self.mcp))
        self.assertIn("mock_tool_call_echo", names)
        self.assertTrue(all(name.startswith("mock_tool_call_") for name in names))

    def test_echo_input_and_output_schema(self) -> None:
        echo = tools(self.mcp)["mock_tool_call_echo"]
        schema = echo.inputSchema
        self.assertEqual(set(schema["required"]), {"request_id", "text"})
        self.assertEqual(schema["properties"]["request_id"]["minLength"], 1)
        self.assertEqual(schema["properties"]["request_id"]["maxLength"], 128)
        self.assertEqual(schema["properties"]["text"]["maxLength"], 4096)
        self.assertEqual(schema["properties"]["mode"]["enum"], ["success", "business_error"])
        self.assertEqual(schema["properties"]["mode"]["default"], "success")
        output = echo.outputSchema
        self.assertIsNotNone(output)
        self.assertEqual(
            set(output["required"]),
            {"mock", "tool", "request_id", "status", "data", "error"},
        )

    def test_success_and_business_error_shapes(self) -> None:
        arguments = {"request_id": "mock-demo-001", "text": "hello shared mcp", "mode": "success"}
        self.assertEqual(
            call(self.mcp, "mock_tool_call_echo", arguments),
            {
                "mock": True,
                "tool": "mock_tool_call_echo",
                "request_id": "mock-demo-001",
                "status": "succeeded",
                "data": {"text": "hello shared mcp"},
                "error": None,
            },
        )
        self.assertEqual(
            call(self.mcp, "mock_tool_call_echo", {**arguments, "mode": "business_error"}),
            {
                "mock": True,
                "tool": "mock_tool_call_echo",
                "request_id": "mock-demo-001",
                "status": "failed",
                "data": None,
                "error": {
                    "code": "MOCK_BUSINESS_ERROR",
                    "message": "Synthetic business failure requested by the caller.",
                },
            },
        )

    def test_invalid_input_is_rejected(self) -> None:
        invalid = [
            {"text": "x"},
            {"request_id": "a", "text": "x", "mode": "other"},
            {"request_id": "   ", "text": "x"},
            {"request_id": "a" * 129, "text": "x"},
            {"request_id": "a", "text": "x" * 4097},
        ]
        for arguments in invalid:
            with self.subTest(arguments=list(arguments)):
                with self.assertRaises(ToolError):
                    call(self.mcp, "mock_tool_call_echo", arguments)

    def test_echo_is_deterministic_across_instances(self) -> None:
        arguments = {"request_id": "r-1", "text": "same"}
        first = call(self.mcp, "mock_tool_call_echo", arguments)
        self.assertEqual(first, call(self.mcp, "mock_tool_call_echo", arguments))
        self.assertEqual(first, call(build(), "mock_tool_call_echo", arguments))

    def test_registration_needs_no_network_and_defaults_to_memory(self) -> None:
        with patch.object(socket, "create_connection", side_effect=AssertionError("network")), patch.dict(
            "os.environ", {}, clear=True,
        ):
            mcp = FastMCP("mock-tool-call")
            pack.register(mcp)
            self.assertIn("mock_tool_call_echo", tools(mcp))
            call(mcp, "mock_tool_call_echo", {"request_id": "n", "text": "t"})


class BusinessToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mcp = build()

    def test_every_business_result_is_marked_mock(self) -> None:
        result = call(self.mcp, "mock_tool_call_salesforce_search", {"email": "jrogers@burlington.com"})
        self.assertTrue(result["mock"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"][0]["Name"], "Jack Rogers")
        self.assertEqual(result["records"][0]["Account"]["Name"], "Burlington Textiles Corp of America")

    def test_calendar_find_book_list_update_cancel(self) -> None:
        found = call(self.mcp, "mock_tool_call_find_meeting_times", {
            "meetingDuration": "PT30M",
            "startDateTime": "2026-10-22T09:00:00",
            "endDateTime": "2026-10-22T17:00:00",
            "timeZone": "Pacific Standard Time",
            "maxCandidates": 3,
        })
        slots = found["meetingTimeSuggestions"]
        self.assertEqual(len(slots), 3)
        self.assertEqual(list(slots[0]["meetingTimeSlot"]), ["end", "start"])
        self.assertEqual(slots[0]["meetingTimeSlot"]["start"]["timeZone"], "UTC")
        created = call(self.mcp, "mock_tool_call_create_event", {
            "subject": "Initial consultation with Dana Test",
            "startDateTime": "2026-10-22T09:00:00",
            "endDateTime": "2026-10-22T10:00:00",
            "timeZone": "Pacific Standard Time",
            "attendeeEmails": ["dana.test20261020@example.com"],
            "isOnlineMeeting": True,
        })
        self.assertTrue(created["ok"])
        self.assertIn("joinUrl", created["onlineMeeting"])
        again = call(self.mcp, "mock_tool_call_find_meeting_times", {
            "meetingDuration": "PT30M",
            "startDateTime": "2026-10-22T09:00:00",
            "endDateTime": "2026-10-22T10:00:00",
            "timeZone": "Pacific Standard Time",
        })
        self.assertEqual(again["meetingTimeSuggestions"], [])
        listed = call(self.mcp, "mock_tool_call_list_calendar_view", {
            "startDateTime": "2026-10-22T00:00:00",
            "endDateTime": "2026-10-22T23:59:00",
            "timeZone": "Pacific Standard Time",
            "subject": "Dana Test",
        })
        self.assertEqual([event["id"] for event in listed["value"]], [created["id"], "mock-evt-seed-1"])
        moved = call(self.mcp, "mock_tool_call_update_event", {
            "eventId": created["id"],
            "startDateTime": "2026-10-23T11:00:00",
            "endDateTime": "2026-10-23T12:00:00",
            "timeZone": "Pacific Standard Time",
        })
        self.assertEqual(moved["start"]["dateTime"], "2026-10-23T11:00:00.0000000")
        cancelled = call(self.mcp, "mock_tool_call_cancel_event", {"eventId": "mock-evt-seed-1"})
        self.assertTrue(cancelled["cancelled"])
        twice = call(self.mcp, "mock_tool_call_cancel_event", {"eventId": "mock-evt-seed-1"})
        self.assertFalse(twice["ok"])
        self.assertEqual(twice["error"]["code"], "EVENT_CANCELLED")

    def test_seed_event_is_next_thursday(self) -> None:
        listed = call(self.mcp, "mock_tool_call_list_calendar_view", {
            "startDateTime": "2026-10-22T00:00:00",
            "endDateTime": "2026-10-22T23:59:00",
            "timeZone": "Pacific Standard Time",
            "subject": "dana test",
        })
        self.assertEqual(listed["value"][0]["start"]["dateTime"], "2026-10-22T10:00:00.0000000")
        self.assertEqual(listed["value"][0]["dayOfWeek"], "Thursday")

    def test_unknown_time_zone_is_a_business_failure(self) -> None:
        result = call(self.mcp, "mock_tool_call_find_meeting_times", {
            "meetingDuration": "PT30M",
            "startDateTime": "2026-10-22T09:00:00",
            "endDateTime": "2026-10-22T17:00:00",
            "timeZone": "Mars Standard Time",
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "UNKNOWN_TIME_ZONE")

    def test_zendesk_search_comment_and_create(self) -> None:
        found = call(self.mcp, "mock_tool_call_zendesk_search", {"query": "VPN says authentication failed"})
        self.assertEqual(found["results"][0]["id"], 360002)
        commented = call(self.mcp, "mock_tool_call_zendesk_add_comment", {"ticket_id": "3", "comment": "Still 401"})
        self.assertEqual((commented["ticket_id"], commented["status"]), (3, "open"))
        missing = call(self.mcp, "mock_tool_call_zendesk_add_comment", {"ticket_id": "999", "comment": "x"})
        self.assertEqual(missing["error"]["code"], "TICKET_NOT_FOUND")
        created = call(self.mcp, "mock_tool_call_zendesk_create_ticket", {
            "subject": "Escalation", "description": "Nothing worked", "priority": "high",
        })
        self.assertEqual((created["ticket_id"], created["status"], created["priority"]), (1001, "new", "high"))
        lookup = call(self.mcp, "mock_tool_call_zendesk_search", {"query": "1001", "type": "tickets"})
        self.assertEqual(lookup["results"][0]["title"], "Escalation")

    def test_sms_success_and_failure(self) -> None:
        sent = call(self.mcp, "mock_tool_call_twilio_send_message", {"to": "+1 978 627 7446", "body": "Hi"})
        self.assertEqual(sent["status"], "queued")
        self.assertTrue(sent["message_sid"].startswith("SMMOCK"))
        failed = call(self.mcp, "mock_tool_call_twilio_send_message", {"to": "+15005550001", "body": "Hi"})
        self.assertFalse(failed["ok"])
        self.assertEqual(failed["error"]["code"], "21211")
        with self.assertRaises(ToolError):
            call(self.mcp, "mock_tool_call_twilio_send_message", {"to": "+19786277446", "body": "x" * 301})

    def test_lead_presence_mail_and_order(self) -> None:
        lead = call(self.mcp, "mock_tool_call_salesforce_create_lead", {"last_name": "Test", "company": "Fabrikam"})
        self.assertEqual(lead["lead_id"], "00QMOCK000000001")
        presence = call(self.mcp, "mock_tool_call_get_user_presence", {"userEmail": "meganb@contoso.com"})
        self.assertEqual(presence["availability"], "Busy")
        mail = call(self.mcp, "mock_tool_call_send_email_with_attachments", {
            "to": "meganb@contoso.com", "subject": "Phone message from Dana", "body": "Call back",
        })
        self.assertEqual(mail["status"], "sent")
        order = call(self.mcp, "mock_tool_call_order_lookup", {"order_number": "10045"})
        self.assertEqual(order["order"]["status"], "in_transit")
        self.assertEqual(order["order"]["estimated_delivery"], {"earliest": "2026-10-20", "latest": "2026-10-22"})

    def test_hotel_flow(self) -> None:
        available = call(self.mcp, "mock_tool_call_hotel_check_availability", {
            "check_in": "2026-10-23", "check_out": "2026-10-25", "guests": 2,
        })
        rooms = {room["room_type"]: room for room in available["rooms"]}
        self.assertEqual(rooms["Classic King"]["total_before_taxes"], 458)
        self.assertFalse(rooms["Junior Suite"]["available"])
        booked = call(self.mcp, "mock_tool_call_hotel_create_reservation", {
            "first_name": "Dana", "last_name": "Test", "email": "dana.test20261020@example.com",
            "room_type": "Classic King", "check_in": "2026-10-23", "check_out": "2026-10-25", "guests": 2,
        })
        self.assertEqual(booked["confirmation_number"], "M00001")
        found = call(self.mcp, "mock_tool_call_hotel_get_reservation", {"confirmation_number": "a1b2c3", "last_name": "test"})
        self.assertEqual(found["reservation"]["room_type"], "Classic King")
        cancelled = call(self.mcp, "mock_tool_call_hotel_cancel_reservation", {"confirmation_number": "A1B2C3", "last_name": "Test"})
        self.assertEqual((cancelled["status"], cancelled["cancellation_fee"]), ("cancelled", 0))

    def test_coaching_and_research_records(self) -> None:
        quiz = call(self.mcp, "mock_tool_call_quiz_record_result", {
            "quiz_name": "Security awareness basics", "score": 8, "total": 10, "passing_score": 7,
        })
        self.assertTrue(quiz["passed"])
        session = call(self.mcp, "mock_tool_call_training_record_session", {
            "scenario": "Angry customer", "communication": 4, "objection_handling": 3,
            "empathy": 5, "resolution": 3, "key_takeaway": "Name the next step.",
        })
        self.assertEqual(session["record_id"], "TS-1001")
        refused = call(self.mcp, "mock_tool_call_research_save_interview_notes", {
            "consent_given": False, "summary": "Plans in a spreadsheet.",
        })
        self.assertEqual(refused["error"]["code"], "CONSENT_REQUIRED")


class StateStoreTests(unittest.TestCase):
    def test_redis_store_uses_its_own_prefix_and_ttl(self) -> None:
        client = FakeRedis()
        store = RedisStateStore(client, key_prefix="test:noauth", ttl_seconds=3600)
        mcp = build(store)
        call(mcp, "mock_tool_call_zendesk_create_ticket", {"subject": "S", "description": "D"})
        self.assertTrue(all(key.startswith("test:noauth:mock-tool-call:") for key in client.values))
        self.assertTrue(all(value == 3600 for value in client.ttl.values()))
        self.assertIn("1001", client.smembers("test:noauth:mock-tool-call:ticket:index"))
        other = build(RedisStateStore(client, key_prefix="test:noauth", ttl_seconds=3600))
        shared = call(other, "mock_tool_call_zendesk_add_comment", {"ticket_id": "1001", "comment": "seen"})
        self.assertTrue(shared["ok"])

    def test_environment_selects_redis_lazily_and_fails_closed(self) -> None:
        self.assertIsInstance(store_from_environment({}), MemoryStateStore)
        lazy = store_from_environment({"NOAUTH_MCP_REDIS_URL": "rediss://redis.example:6380/0"})
        self.assertEqual(type(lazy).__name__, "LazyRedisStateStore")
        with self.assertRaisesRegex(ValueError, "REDIS_URL is required"):
            store_from_environment({"NOAUTH_MCP_REQUIRE_SHARED_STATE": "true"})


if __name__ == "__main__":
    unittest.main()
