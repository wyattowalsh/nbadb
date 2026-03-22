"""Agent assembly — creates the deepagents NBA data analytics agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph
    from server.config import ChatSettings

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"

_mcp_client = None  # held to prevent subprocess GC


async def create_nba_agent(
    settings: ChatSettings,
) -> CompiledStateGraph:
    """Create an NBA data analytics agent.

    When provider=copilot, uses the GitHub Copilot SDK as the agent runtime.
    Otherwise, uses deepagents (LangChain) with MCP tools.
    """
    from server.db import ensure_database, get_schema_context
    from server.prompts import build_system_prompt

    # Ensure database exists (downloads from Kaggle on first run)
    db_path = ensure_database(settings.duckdb_path)
    schema_context = get_schema_context(db_path)
    system_prompt = build_system_prompt(schema_context)

    if settings.provider == "copilot":
        return await _create_copilot_agent(settings, system_prompt, db_path)

    return await _create_deepagents_agent(settings, system_prompt, db_path)


async def _create_copilot_agent(
    settings: ChatSettings,
    system_prompt: str,
    db_path: Path,
) -> CompiledStateGraph:
    """Create agent using the GitHub Copilot SDK runtime."""
    from server.copilot_backend import create_copilot_agent

    return await create_copilot_agent(settings, system_prompt, db_path)  # type: ignore[return-value]


async def _create_deepagents_agent(
    settings: ChatSettings,
    system_prompt: str,
    db_path: Path,
) -> CompiledStateGraph:
    """Create agent using deepagents (LangChain)."""
    from deepagents import create_deep_agent
    from deepagents.backends.local import LocalShellBackend
    from server.mcp_client import setup_mcp_tools
    from server.providers import create_chat_model
    from server.tools.web_fetch import web_fetch
    from server.tools.web_search import web_search

    model: BaseChatModel = create_chat_model(settings)
    mcp_tools, mcp_client = await setup_mcp_tools(settings)

    global _mcp_client
    _mcp_client = mcp_client

    local_tools = [web_search, web_fetch]

    return create_deep_agent(
        model=model,
        tools=[*local_tools, *mcp_tools],
        skills=[str(SKILLS_DIR)],
        backend=LocalShellBackend(root_dir=db_path.parent),
        system_prompt=system_prompt,
    )
