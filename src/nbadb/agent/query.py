from __future__ import annotations

import re
from typing import TYPE_CHECKING

import duckdb

from nbadb.agent.context import SchemaContext
from nbadb.agent.safety import QUERY_TIMEOUT_SECONDS, ReadOnlyGuard

if TYPE_CHECKING:
    from pathlib import Path


_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(r"who\s+led\s+(?:in\s+)?scoring", re.IGNORECASE),
        "SELECT s.player_id, p.full_name, s.total_pts "
        "FROM agg_player_season s "
        "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
        "ORDER BY s.total_pts DESC LIMIT 10",
    ),
    (
        re.compile(r"most\s+points", re.IGNORECASE),
        "SELECT s.player_id, p.full_name, s.total_pts "
        "FROM agg_player_season s "
        "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
        "ORDER BY s.total_pts DESC LIMIT 10",
    ),
    (
        re.compile(r"most\s+assists", re.IGNORECASE),
        "SELECT s.player_id, p.full_name, s.total_ast "
        "FROM agg_player_season s "
        "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
        "ORDER BY s.total_ast DESC LIMIT 10",
    ),
    (
        re.compile(r"most\s+rebounds", re.IGNORECASE),
        "SELECT s.player_id, p.full_name, s.total_reb "
        "FROM agg_player_season s "
        "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
        "ORDER BY s.total_reb DESC LIMIT 10",
    ),
    (
        re.compile(r"team\s+standings|standings", re.IGNORECASE),
        "SELECT t.full_name, s.wins, s.losses, s.win_pct "
        "FROM fact_standings s "
        "JOIN dim_team t ON s.team_id = t.team_id "
        "ORDER BY s.wins DESC",
    ),
    (
        re.compile(r"how\s+many\s+(?:games|records)", re.IGNORECASE),
        "SELECT table_name, row_count FROM _pipeline_metadata "
        "ORDER BY row_count DESC",
    ),
]


class QueryAgent:
    def __init__(self, duckdb_path: Path) -> None:
        self._path = duckdb_path
        self._guard = ReadOnlyGuard()
        self._context = SchemaContext(duckdb_path)

    def ask(self, question: str) -> str:
        sql = self._match_pattern(question)
        if sql is None:
            schema_info = self._context.build_prompt_context()
            return (
                "I couldn't match your question to a known pattern.\n\n"
                "You can write DuckDB SQL directly. Here is the schema:\n\n"
                f"{schema_info}"
            )
        error = self._guard.validate(sql)
        if error:
            return f"Query blocked: {error}"
        sql = self._guard.wrap_with_limit(sql)
        return self._execute(sql)

    def _match_pattern(self, question: str) -> str | None:
        for pattern, sql_template in _PATTERNS:
            if pattern.search(question):
                return sql_template
        return None

    def _execute(self, sql: str) -> str:
        try:
            with duckdb.connect(str(self._path), read_only=True) as conn:
                conn.execute(
                    f"SET statement_timeout='{int(QUERY_TIMEOUT_SECONDS)}s'"
                )
                result = conn.execute(sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
                if not rows:
                    return "No results found."
                header = " | ".join(columns)
                separator = "-+-".join("-" * len(c) for c in columns)
                lines = [header, separator]
                for row in rows:
                    lines.append(" | ".join(str(v) for v in row))
                return "\n".join(lines)
        except duckdb.Error as exc:
            return f"Query error: {exc}"
