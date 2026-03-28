"""Agent assembly — creates the deepagents NBA data analytics agent."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from langchain_core.language_models.chat_models import BaseChatModel
    from server.config import ChatSettings

SKILLS_DIR = Path(__file__).resolve().parent.parent / "skills"


class NbaAgentWrapper:
    """Thin wrapper that holds both the LangGraph agent and the MCP client.

    Ensures ``cleanup()`` is available for all backend paths (deepagents
    and copilot), preventing MCP subprocess leaks across settings updates
    and session ends.
    """

    def __init__(self, agent: Any, mcp_client: Any | None = None) -> None:
        self._agent = agent
        self._mcp_client = mcp_client

    async def astream(
        self,
        inputs: dict,
        *,
        stream_mode: str | None = None,
        config: dict | None = None,
    ) -> AsyncIterator:
        """Proxy to the underlying agent's astream, forwarding all kwargs."""
        kwargs: dict[str, Any] = {}
        if stream_mode is not None:
            kwargs["stream_mode"] = stream_mode
        if config is not None:
            kwargs["config"] = config
        async for event in self._agent.astream(inputs, **kwargs):
            yield event

    async def cleanup(self) -> None:
        """Shut down MCP subprocesses and backend resources."""
        # Copilot wrapper has its own cleanup
        if hasattr(self._agent, "cleanup"):
            await self._agent.cleanup()
        # Close MCP client (MultiServerMCPClient context manager)
        if self._mcp_client is not None:
            await self._mcp_client.__aexit__(None, None, None)
            self._mcp_client = None


async def create_nba_agent(
    settings: ChatSettings,
    profile: str | None = None,
    session_id: str = "default",
) -> NbaAgentWrapper:
    """Create an NBA data analytics agent.

    When provider=copilot, uses the GitHub Copilot SDK as the agent runtime.
    Otherwise, uses deepagents (LangChain) with MCP tools.
    """
    from server.db import ensure_database, get_schema_context
    from server.prompts import build_system_prompt

    db_path = ensure_database(settings.duckdb_path)
    schema_context = get_schema_context(db_path)
    system_prompt = build_system_prompt(schema_context, profile=profile)

    if settings.provider == "copilot":
        return await _create_copilot_agent(settings, system_prompt, db_path, session_id=session_id)

    return await _create_deepagents_agent(
        settings,
        system_prompt,
        db_path,
        session_id=session_id,
    )


async def _create_copilot_agent(
    settings: ChatSettings,
    system_prompt: str,
    db_path: Path,
    session_id: str,
) -> NbaAgentWrapper:
    """Create agent using the GitHub Copilot SDK runtime."""
    from server.copilot_backend import create_copilot_agent

    agent = await create_copilot_agent(settings, system_prompt, db_path, session_id=session_id)
    return NbaAgentWrapper(agent)


async def _create_deepagents_agent(
    settings: ChatSettings,
    system_prompt: str,
    db_path: Path,
    session_id: str,
) -> NbaAgentWrapper:
    """Create agent using deepagents (LangChain)."""
    from deepagents import create_deep_agent
    from deepagents.backends.local import LocalShellBackend
    from server.mcp_client import setup_mcp_tools
    from server.providers import create_chat_model
    from server.tools.web_fetch import web_fetch
    from server.tools.web_search import web_search

    model: BaseChatModel = create_chat_model(settings)
    mcp_tools, mcp_client = await setup_mcp_tools(settings, session_id=session_id)

    local_tools = [web_search, web_fetch]

    agent = create_deep_agent(
        model=model,
        tools=[*local_tools, *mcp_tools],
        skills=[str(SKILLS_DIR)],
        backend=LocalShellBackend(root_dir=db_path.parent),
        system_prompt=system_prompt,
    )

    return NbaAgentWrapper(agent, mcp_client)
