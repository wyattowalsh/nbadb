"""DuckDB SQL MCP server — provides run_sql, list_tables, describe_table tools."""

from __future__ import annotations

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

# Import shared modules from the chat app's server directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "server"))
from _safety import ReadOnlyGuard  # noqa: E402
from _sql_exec import describe_single_table, execute_safe_sql, list_all_tables  # noqa: E402

_guard = ReadOnlyGuard()


# --- MCP Tools ----------------------------------------------------------------


@mcp.tool()
def run_sql(query: str) -> str:
    """Execute a read-only DuckDB SQL query against the NBA database.

    Returns JSON with columns and rows.
    """
    return json.dumps(execute_safe_sql(DUCKDB_PATH, query, _guard), default=str)


@mcp.tool()
def list_tables() -> str:
    """List all user tables in the NBA database."""
    try:
        return json.dumps(list_all_tables(DUCKDB_PATH))
    except duckdb.Error as exc:
        return json.dumps({"error": f"Failed to list tables: {type(exc).__name__}"})


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Get column names and types for a specific table."""
    try:
        return json.dumps(describe_single_table(DUCKDB_PATH, table_name))
    except duckdb.Error as exc:
        return json.dumps({"error": f"Failed to describe table: {type(exc).__name__}"})


if __name__ == "__main__":
    mcp.run(transport="stdio")
