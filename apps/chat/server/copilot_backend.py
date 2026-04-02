"""Copilot SDK backend — uses github-copilot-sdk as the agent runtime.

When provider=copilot, this module replaces deepagents entirely.
The Copilot CLI handles the agent loop, tool calling, and context management.
Our NBA tools are registered as Copilot tools via @define_tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, ToolMessage

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from server.config import ChatSettings


async def create_copilot_agent(
    settings: ChatSettings,
    system_prompt: str,
    db_path: Path,
    session_id: str,
) -> CopilotAgentWrapper:
    """Create a Copilot SDK agent with NBA tools registered."""
    from copilot import CopilotClient

    client = CopilotClient()
    await client.start()

    tools = _build_tools(db_path, session_id=session_id)

    return CopilotAgentWrapper(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=settings.model,
    )


def _build_tools(db_path: Path, session_id: str) -> list:
    """Build Copilot tools for NBA data analytics."""
    from copilot import define_tool
    from pydantic import BaseModel, Field

    skills_dir = (
        Path(__file__).resolve().parent.parent / "skills" / "nba-data-analytics" / "scripts"
    )

    # -- run_sql ---------------------------------------------------------------

    class RunSqlParams(BaseModel):
        query: str = Field(description="DuckDB SQL query to execute")

    @define_tool(
        description=(
            "Execute a read-only SQL query against the NBA DuckDB database. "
            "Returns JSON with columns, rows, and row_count."
        ),
    )
    def run_sql(params: RunSqlParams) -> str:
        import duckdb
        from server._safety import ReadOnlyGuard

        guard = ReadOnlyGuard()
        error = guard.validate(params.query)
        if error:
            return json.dumps({"error": f"Query blocked: {error}"})
        safe_query = guard.wrap_with_limit(params.query, max_rows=1000)

        with duckdb.connect(str(db_path), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            with contextlib.suppress(duckdb.CatalogException):
                conn.execute("SET statement_timeout = '30s'")

            cursor = conn.execute(safe_query)
            columns = [desc[0] for desc in cursor.description]
            result = cursor.fetchall()

        return json.dumps(
            {
                "columns": columns,
                "rows": [list(row) for row in result],
                "row_count": len(result),
                "sql": params.query,
            },
            default=str,
        )

    # -- list_tables -----------------------------------------------------------

    @define_tool(description="List all tables in the NBA database.")
    def list_tables() -> str:
        import duckdb as _db

        with _db.connect(str(db_path), read_only=True) as conn:
            rows = conn.execute(
                "SELECT DISTINCT table_name FROM information_schema.columns "
                "WHERE table_schema = 'main' ORDER BY table_name"
            ).fetchall()
        tables = [r[0] for r in rows]
        return json.dumps({"tables": tables, "count": len(tables)})

    # -- describe_table --------------------------------------------------------

    class DescribeTableParams(BaseModel):
        table_name: str = Field(description="Name of the table to describe")

    @define_tool(description="Get column names and types for a database table.")
    def describe_table(params: DescribeTableParams) -> str:
        import duckdb as _db

        with _db.connect(str(db_path), read_only=True) as conn:
            rows = conn.execute(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'main' AND table_name = ? "
                "ORDER BY ordinal_position",
                [params.table_name],
            ).fetchall()
        return json.dumps(
            {
                "table": params.table_name,
                "columns": [{"name": c[0], "type": c[1]} for c in rows],
            },
        )

    # -- run_python ------------------------------------------------------------

    class RunPythonParams(BaseModel):
        code: str = Field(
            description=(
                "Python code to execute. Pre-imported: pandas (pd), "
                "numpy (np), plotly (px/go). "
                "Pre-defined: conn (safe DuckDB helper), query(sql), "
                "mc (metric_calculator). "
                "For charts: print(fig.to_json()). "
                "For tables: print(df.to_json(orient='split'))."
            ),
        )

    from server._preamble import build_preamble
    from server._sandbox_exec import check_code_safety, run_sandboxed

    preamble = build_preamble(
        db_path=str(db_path),
        skills_dir=str(skills_dir),
        session_dir=str(Path("~/.nbadb/session").expanduser() / session_id),
    )

    @define_tool(
        description=(
            "Execute Python code with access to the NBA database and visualization libraries."
        ),
    )
    def run_python(params: RunPythonParams) -> str:
        safety_error = check_code_safety(params.code)
        if safety_error:
            return json.dumps({"error": safety_error})

        full_code = preamble + "\n" + params.code
        result = run_sandboxed(full_code, cwd=db_path.parent)

        if "_raw" in result:
            return result["_raw"]

        return json.dumps(result)

    return [run_sql, list_tables, describe_table, run_python]


class CopilotAgentWrapper:
    """Adapts CopilotClient to the astream() interface used by chainlit_app.py.

    Yields (LangChain message, metadata) tuples so the Chainlit rendering
    pipeline works identically for both deepagents and Copilot backends.
    """

    def __init__(
        self,
        client: Any,
        tools: list,
        system_prompt: str,
        model: str,
    ) -> None:
        self._client = client
        self._tools = tools
        self._system_prompt = system_prompt
        self._model = model
        self._session: Any = None

    async def astream(
        self,
        inputs: dict,
        *,
        stream_mode: str | None = None,
        config: dict | None = None,
    ) -> AsyncIterator[tuple[AIMessage | ToolMessage, dict]]:
        """Stream agent events as (message, metadata) tuples."""
        queue: asyncio.Queue = asyncio.Queue()

        # Create or reuse session
        if self._session is None:
            _allowed_tools = frozenset({"run_sql", "list_tables", "describe_table", "run_python"})

            def _scoped_permission_handler(request: Any) -> bool:
                tool_name = getattr(request, "name", None) or getattr(request, "tool_name", None)
                return tool_name in _allowed_tools

            self._session = await self._client.create_session(
                on_permission_request=_scoped_permission_handler,
                model=self._model,
                streaming=True,
                tools=self._tools,
                system_prompt_append=self._system_prompt,
            )

        session = self._session

        # Subscribe to events
        def _on_event(event: Any) -> None:
            queue.put_nowait(event)

        unsubscribe = session.on(_on_event)

        try:
            prompt = inputs["messages"][-1].content
            await session.send(prompt)

            while True:
                event = await asyncio.wait_for(queue.get(), timeout=120)
                event_type = str(event.type)

                if "message_delta" in event_type:
                    delta = getattr(event.data, "delta_content", "")
                    if delta:
                        yield (AIMessage(content=delta), {})

                elif "tool" in event_type and "result" in event_type:
                    # Tool execution completed — yield as ToolMessage for Chainlit rendering
                    tool_name = getattr(event.data, "name", "tool")
                    tool_result = getattr(event.data, "result", str(event.data))
                    if isinstance(tool_result, dict):
                        tool_result = json.dumps(tool_result, default=str)
                    elif not isinstance(tool_result, str):
                        tool_result = str(tool_result)
                    yield (
                        ToolMessage(
                            content=tool_result,
                            tool_call_id=f"copilot-{id(event)}",
                            name=tool_name,
                        ),
                        {"input": getattr(event.data, "arguments", "")},
                    )

                elif "message" in event_type and "delta" not in event_type:
                    # Final complete message — skip if we already streamed
                    pass

                elif "idle" in event_type:
                    break

                elif "error" in event_type:
                    error_msg = getattr(event.data, "message", str(event))
                    yield (
                        AIMessage(content=f"**Error:** {error_msg}"),
                        {},
                    )
                    break

        except TimeoutError:
            yield (
                AIMessage(content="**Error:** Request timed out."),
                {},
            )
        finally:
            unsubscribe()

    async def cleanup(self) -> None:
        """Clean up the Copilot client."""
        if self._session:
            await self._session.disconnect()
            self._session = None
        await self._client.stop()
