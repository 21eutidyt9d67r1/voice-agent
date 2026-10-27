"""Opt-in real MCP discovery; never call business tools or publish an Agent."""

import asyncio
import logging
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

import pytest
from aiohttp.test_utils import TestClient, TestServer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
import demo_server
import template_portal

# Explicit opt-in prevents external calls during the normal unit suite.
pytestmark = pytest.mark.skipif(os.getenv("TOOL_CONNECT_LIVE_TESTS") != "1", reason="Set TOOL_CONNECT_LIVE_TESTS=1.")
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _ProbeResult:
    status: int
    connected: bool
    handshakes: int
    elapsed_seconds: float


async def _connect_live(url: str) -> _ProbeResult:
    args = demo_server.parse_args(
        [
            "--project-endpoint",
            "https://test.services.ai.azure.com/api/projects/test",
            "--no-record-sessions",
        ]
    )
    definition = {
        "kind": "voice",
        "tools": [
            {
                "type": "mcp",
                "server_label": "mock_tool_call",
                "server_url": "https://mock.example/mcp",
                "allowed_tools": ["mock_tool_call_salesforce_search"],
            }
        ],
    }
    started = time.perf_counter()
    with patch.object(template_portal, "mcp_handshake", wraps=template_portal.mcp_handshake) as handshake:
        async with TestClient(TestServer(demo_server.build_app(args))) as client:
            response = await client.post(
                "/api/tools/connect",
                json={
                    "definition": definition,
                    "group": "salesforce",
                    "server_url": url,
                },
            )
            payload = await response.json()
            return _ProbeResult(
                response.status, payload.get("connected") is True, handshake.call_count, time.perf_counter() - started
            )


class TestToolConnectLive:
    def test_auto_connect_performs_one_real_handshake(self) -> None:
        result = asyncio.run(_connect_live(os.environ["VOICE_TOOL_TEST_URL"]))
        assert result.status == 200
        assert result.connected
        assert result.handshakes == 1
        logger.info("Live one-request connection completed in %.3fs", result.elapsed_seconds)
