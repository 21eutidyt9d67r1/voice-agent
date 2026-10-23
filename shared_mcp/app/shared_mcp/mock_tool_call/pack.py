from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from .server import register_tools
from .service import MockToolCallService


def register(mcp: FastMCP) -> None:
    register_tools(mcp, MockToolCallService())
