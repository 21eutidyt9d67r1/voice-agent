"""Fresh MCP discovery and one-request connection regressions; no external calls."""

import asyncio
import copy
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import demo_server
import template_portal

# A public-looking fixture URL is never contacted by these mocked tests.
SERVER_URL = "https://crm.example/mcp"
# Match the hosted mock's naming prefix so the existing tool-system catalog applies.
REQUIRED_TOOL = "mock_tool_call_salesforce_search"


def _definition() -> dict:
    return {
        "kind": "voice",
        "instructions": f"Call {REQUIRED_TOOL}.",
        "tools": [
            {
                "type": "mcp",
                "server_label": "mock_tool_call",
                "server_url": "https://mock.example/mcp",
                "allowed_tools": [REQUIRED_TOOL],
            }
        ],
    }


async def _request(path: str, body: dict) -> tuple[int, dict]:
    args = demo_server.parse_args(
        [
            "--project-endpoint",
            "https://test.services.ai.azure.com/api/projects/test",
            "--no-record-sessions",
        ]
    )
    async with TestClient(TestServer(demo_server.build_app(args))) as client:
        response = await client.post(path, json=body)
        return response.status, await response.json()


class TestToolConnection:
    def test_connect_mock_auto_map_uses_one_handshake(self) -> None:
        definition = _definition()
        original = copy.deepcopy(definition)
        with patch.object(template_portal, "mcp_handshake", return_value={"tools": ["SalesforceSearch"]}) as handshake:
            status, result = asyncio.run(
                _request(
                    "/api/tools/connect",
                    {
                        "definition": definition,
                        "group": "salesforce",
                        "server_url": SERVER_URL,
                    },
                )
            )
        assert status == 200
        assert result["connected"] is True
        assert result["tool_map"] == {REQUIRED_TOOL: "SalesforceSearch"}
        assert result["definition"]["tools"][0]["server_url"] == SERVER_URL
        assert REQUIRED_TOOL not in result["definition"]["instructions"]
        assert definition == original
        handshake.assert_called_once_with(SERVER_URL)

    def test_connect_mock_missing_match_does_not_change_definition(self) -> None:
        with patch.object(template_portal, "mcp_handshake", return_value={"tools": ["SearchContacts"]}) as handshake:
            status, result = asyncio.run(
                _request(
                    "/api/tools/connect",
                    {
                        "definition": _definition(),
                        "group": "salesforce",
                        "server_url": SERVER_URL,
                    },
                )
            )
        assert status == 200
        assert result["connected"] is False
        assert result["unmapped"] == [REQUIRED_TOOL]
        assert result["tools"] == ["SearchContacts"]
        assert "definition" not in result
        handshake.assert_called_once()

    @pytest.mark.parametrize("tool_map", [None, {}, {REQUIRED_TOOL: "NotListed"}])
    def test_connect_mock_invalid_explicit_mapping_is_not_auto_replaced(self, tool_map: object) -> None:
        with patch.object(template_portal, "mcp_handshake", return_value={"tools": ["salesforce_search"]}):
            status, result = asyncio.run(
                _request(
                    "/api/tools/connect",
                    {
                        "definition": _definition(),
                        "group": "salesforce",
                        "server_url": SERVER_URL,
                        "tool_map": tool_map,
                    },
                )
            )
        assert status == 400
        assert result["code"] == "http_400"
        assert "definition" not in result

    def test_connect_mock_manual_mapping_is_revalidated_against_fresh_catalog(self) -> None:
        with patch.object(template_portal, "mcp_handshake", return_value={"tools": ["SearchContacts"]}) as handshake:
            status, result = asyncio.run(
                _request(
                    "/api/tools/connect",
                    {
                        "definition": _definition(),
                        "group": "salesforce",
                        "server_url": SERVER_URL,
                        "tool_map": {REQUIRED_TOOL: "SearchContacts"},
                    },
                )
            )
        assert status == 200
        assert result["connected"] is True
        handshake.assert_called_once()

    def test_discover_mock_legacy_shape_is_preserved(self) -> None:
        with patch.object(template_portal, "mcp_handshake", return_value={"tools": ["salesforce_search"]}):
            status, result = asyncio.run(
                _request(
                    "/api/tools/discover",
                    {
                        "definition": _definition(),
                        "group": "salesforce",
                        "server_url": SERVER_URL,
                    },
                )
            )
        assert status == 200
        assert result["ok"] is True
        assert result["mapping"] == {REQUIRED_TOOL: "salesforce_search"}
        assert "definition" not in result

    def test_connect_mock_private_address_guard_is_not_bypassed(self) -> None:
        with patch.object(
            template_portal, "mcp_handshake", side_effect=template_portal.McpProbeError("private address")
        ):
            status, result = asyncio.run(
                _request(
                    "/api/tools/connect",
                    {
                        "definition": _definition(),
                        "group": "salesforce",
                        "server_url": "https://127.0.0.1/mcp",
                    },
                )
            )
        assert status == 400
        assert "private address" in result["error"]
