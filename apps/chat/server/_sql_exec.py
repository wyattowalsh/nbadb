"""Shared SQL execution logic for MCP servers and Copilot backend.

Provides safe SQL execution, table listing, and schema description.
Both ``mcp_servers/sql.py`` and ``server/copilot_backend.py`` delegate
to this module so that query execution policy lives in a single place.
"""

from __future__ import annotations

import contextlib
from typing import TYPE_CHECKING

import duckdb

if TYPE_CHECKING:
    from pathlib import Path


def execute_safe_sql(
    db_path: Path,
    query: str,
    guard,
    *,
    max_rows: int = 1000,
) -> dict:
    """Validate, wrap, and execute a SQL query.

    Returns a dict with ``columns``, ``rows``, ``row_count``, ``sql``
    on success, or ``{"error": "..."}`` on failure.
    """
    error = guard.validate(query)
    if error:
        return {"error": f"Query blocked: {error}"}

    safe_sql = guard.wrap_with_limit(query, max_rows=max_rows)
    try:
        with duckdb.connect(str(db_path), read_only=True) as conn:
            conn.execute("SET enable_external_access = false")
            with contextlib.suppress(duckdb.CatalogException):
                conn.execute("SET statement_timeout = '30s'")
            result = conn.execute(safe_sql)
            columns = [desc[0] for desc in result.description]
            rows = result.fetchall()
            return {
                "columns": columns,
                "rows": [list(row) for row in rows],
                "row_count": len(rows),
                "sql": query,
            }
    except duckdb.Error as exc:
        return {"error": f"Query failed: {type(exc).__name__}"}


def list_all_tables(db_path: Path) -> list[str]:
    """Return a sorted list of table names in the main schema."""
    with duckdb.connect(str(db_path), read_only=True) as conn:
        conn.execute("SET enable_external_access = false")
        rows = conn.execute(
            "SELECT DISTINCT table_name FROM information_schema.columns "
            "WHERE table_schema = 'main' ORDER BY table_name"
        ).fetchall()
        return [r[0] for r in rows]


def describe_single_table(db_path: Path, table_name: str) -> list[dict]:
    """Return column metadata for a table.

    Each entry has ``name`` and ``type`` keys.
    """
    with duckdb.connect(str(db_path), read_only=True) as conn:
        conn.execute("SET enable_external_access = false")
        rows = conn.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'main' AND table_name = ? "
            "ORDER BY ordinal_position",
            [table_name],
        ).fetchall()
        return [{"name": c[0], "type": c[1]} for c in rows]
