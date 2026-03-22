"""DuckDB SQL MCP server — provides run_sql, list_tables, describe_table tools."""

from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import duckdb
from mcp.server.fastmcp import FastMCP

# DuckDB path from CLI arg or default
DUCKDB_PATH = (
    Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/.nbadb/data/nba.duckdb").expanduser()
)

mcp = FastMCP("nbadb-sql")

# Import ReadOnlyGuard from the chat app's shared copy
# (avoids importing full nbadb which has heavy deps)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from _safety import ReadOnlyGuard  # noqa: E402

_guard = ReadOnlyGuard()


# --- MCP Tools ----------------------------------------------------------------


@mcp.tool()
def run_sql(query: str) -> str:
    """Execute a read-only DuckDB SQL query against the NBA database.

    Returns JSON with columns and rows.
    """
    error = _guard.validate(query)
    if error:
        return json.dumps({"error": f"Query blocked: {error}"})

    safe_sql = _guard.wrap_with_limit(query, max_rows=1000)
    try:
        with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            with contextlib.suppress(duckdb.CatalogException):
                conn.execute("SET statement_timeout = '30s'")
            result = conn.execute(safe_sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return json.dumps(
                {
                    "columns": columns,
                    "rows": [list(row) for row in rows],
                    "row_count": len(rows),
                    "sql": safe_sql,
                },
                default=str,
            )
    except duckdb.Error as exc:
        return json.dumps({"error": f"Query failed: {type(exc).__name__}"})


@mcp.tool()
def list_tables() -> str:
    """List all user tables in the NBA database."""
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
    return json.dumps([r[0] for r in rows])


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Get column names and types for a specific table."""
    with duckdb.connect(str(DUCKDB_PATH), read_only=True) as conn:
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [table_name],
        ).fetchall()
    return json.dumps([{"name": name, "type": dtype} for name, dtype in rows])


if __name__ == "__main__":
    mcp.run(transport="stdio")
