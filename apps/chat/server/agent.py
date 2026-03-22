"""Agent assembly — creates the deepagents NBA data analytics agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models.chat_models import BaseChatModel
    from langgraph.graph.state import CompiledStateGraph

    from apps.chat.server.config import ChatSettings

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


async def create_nba_agent(settings: ChatSettings) -> CompiledStateGraph:
    """Create a deepagents NBA data analytics agent."""
    from deepagents import create_deep_agent
    from deepagents.backends.local import LocalShellBackend

    from apps.chat.server.db import ensure_database, get_schema_context
    from apps.chat.server.mcp_client import setup_mcp_tools
    from apps.chat.server.prompts import build_system_prompt
    from apps.chat.server.providers import create_chat_model
    from apps.chat.server.tools.web_fetch import web_fetch
    from apps.chat.server.tools.web_search import web_search

    # Ensure database exists (downloads from Kaggle on first run)
    db_path = ensure_database(settings.duckdb_path)

    # Build components
    model: BaseChatModel = create_chat_model(settings)
    schema_context = get_schema_context(db_path)
    system_prompt = build_system_prompt(schema_context)

    # Load MCP tools (DuckDB SQL server + user-configured MCP servers)
    mcp_tools = await setup_mcp_tools(settings)

    # Local tools (web search and fetch)
    local_tools = [web_search, web_fetch]

    # Create the deep agent
    return create_deep_agent(
        model=model,
        tools=[*local_tools, *mcp_tools],
        skills=[str(SKILLS_DIR)],
        backend=LocalShellBackend(root_dir=db_path.parent),
        system_prompt=system_prompt,
    )
