from __future__ import annotations

import contextlib
import json
import sys
from pathlib import Path

import duckdb
from mcp.server.fastmcp import FastMCP

from nbadb.agent.context import SchemaContext
from nbadb.agent.safety import ReadOnlyGuard

# DuckDB path from CLI arg or default
DUCKDB_PATH = (
    Path(sys.argv[1]) if len(sys.argv) > 1 else Path("~/.nbadb/data/nba.duckdb").expanduser()
)

mcp = FastMCP("nbadb-sql")
_guard = ReadOnlyGuard()


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
    ctx = SchemaContext(DUCKDB_PATH)
    return json.dumps(ctx.get_tables())


@mcp.tool()
def describe_table(table_name: str) -> str:
    """Get column names and types for a specific table."""
    ctx = SchemaContext(DUCKDB_PATH)
    cols = ctx.get_columns(table_name)
    return json.dumps([{"name": name, "type": dtype} for name, dtype in cols])


if __name__ == "__main__":
    mcp.run(transport="stdio")
