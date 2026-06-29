from __future__ import annotations

import sys
from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

_REPO_ROOT = Path(__file__).resolve().parents[3]


async def _tool_names(script_name: str) -> set[str]:
    params = StdioServerParameters(
        command=sys.executable,
        args=[str(_REPO_ROOT / "chat" / "mcp_servers" / script_name)],
        cwd=_REPO_ROOT,
    )
    async with (
        stdio_client(params) as (read_stream, write_stream),
        ClientSession(read_stream, write_stream) as session,
    ):
        await session.initialize()
        result = await session.list_tools()
        return {tool.name for tool in result.tools}


@pytest.mark.asyncio
async def test_catalog_mcp_server_exposes_catalog_tool() -> None:
    assert await _tool_names("catalog.py") == {"search_catalog"}


@pytest.mark.asyncio
async def test_memory_mcp_server_exposes_memory_tools() -> None:
    assert await _tool_names("memory.py") == {
        "forget_memory",
        "list_preferences",
        "remember_preference",
        "save_trajectory",
        "search_trajectories",
    }
