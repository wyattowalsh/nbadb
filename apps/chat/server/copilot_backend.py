"""Copilot SDK backend — uses github-copilot-sdk as the agent runtime.

When provider=copilot, this module replaces deepagents entirely.
The Copilot CLI handles the agent loop, tool calling, and context management.
Our NBA tools are registered as Copilot tools via @define_tool.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import subprocess
import sys
import tempfile
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
) -> CopilotAgentWrapper:
    """Create a Copilot SDK agent with NBA tools registered."""
    from copilot import CopilotClient

    client = CopilotClient()
    await client.start()

    tools = _build_tools(db_path)

    return CopilotAgentWrapper(
        client=client,
        tools=tools,
        system_prompt=system_prompt,
        model=settings.model,
    )


def _build_tools(db_path: Path) -> list:
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

            result = conn.execute(safe_query).fetchall()
            columns = [desc[0] for desc in conn.description]

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
                "numpy (np), plotly (px/go), duckdb. "
                "Pre-defined: conn (DuckDB), query(sql), "
                "mc (metric_calculator). "
                "For charts: print(fig.to_json()). "
                "For tables: print(df.to_json(orient='split'))."
            ),
        )

    from server._preamble import build_preamble

    preamble = build_preamble(
        db_path=str(db_path),
        skills_dir=str(skills_dir),
    )

    @define_tool(
        description=(
            "Execute Python code with access to the NBA database and visualization libraries."
        ),
    )
    def run_python(params: RunPythonParams) -> str:
        # Check for dangerous patterns
        _blocked = [
            "subprocess",
            "os.system",
            "os.popen",
            "os.exec",
            "__import__('os')",
            "importlib",
            "shutil.rmtree",
            "open('/etc",
            "open('/proc",
            "open('/sys",
        ]
        for pattern in _blocked:
            if pattern in params.code:
                return json.dumps({"error": f"Blocked: dangerous pattern '{pattern}'"})

        full_code = preamble + "\n" + params.code
        script_path = None
        try:
            with tempfile.NamedTemporaryFile(
                suffix=".py",
                mode="w",
                delete=False,
            ) as f:
                f.write(full_code)
                script_path = f.name

            # Scrub sensitive environment variables from sandbox
            clean_env = {
                k: v
                for k, v in os.environ.items()
                if not any(
                    s in k.upper()
                    for s in (
                        "API_KEY",
                        "SECRET",
                        "TOKEN",
                        "PASSWORD",
                        "LANGCHAIN_API",
                        "LANGFUSE",
                        "COPILOT",
                    )
                )
            }

            result = subprocess.run(
                [sys.executable, script_path],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=str(db_path.parent),
                env=clean_env,
                start_new_session=True,
            )

            stdout = result.stdout.strip()
            stderr = result.stderr.strip()

            if result.returncode != 0:
                return json.dumps(
                    {
                        "error": stderr or "Script failed",
                        "stdout": stdout,
                    }
                )

            if stdout:
                last_line = stdout.rstrip().rsplit("\n", 1)[-1]
                try:
                    parsed = json.loads(last_line)
                    if isinstance(parsed, dict):
                        # Matplotlib base64 PNG
                        if "image_base64" in parsed and "format" in parsed:
                            return last_line  # Return raw for Chainlit rendering
                        if "data" in parsed and "layout" in parsed:
                            return last_line
                        if "columns" in parsed and "data" in parsed:
                            return json.dumps(
                                {
                                    "columns": parsed["columns"],
                                    "rows": parsed["data"],
                                    "row_count": len(parsed["data"]),
                                }
                            )
                except (json.JSONDecodeError, KeyError):
                    pass

            return json.dumps({"stdout": stdout, "stderr": stderr})

        except subprocess.TimeoutExpired:
            return json.dumps(
                {
                    "error": "Script timed out after 60 seconds",
                }
            )
        finally:
            if script_path:
                with contextlib.suppress(OSError):
                    os.unlink(script_path)

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
        from copilot.session import PermissionHandler

        queue: asyncio.Queue = asyncio.Queue()

        # Create or reuse session
        if self._session is None:
            self._session = await self._client.create_session(
                on_permission_request=PermissionHandler.approve_all,
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
