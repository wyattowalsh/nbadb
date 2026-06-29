from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from time import perf_counter
from typing import TYPE_CHECKING

import duckdb

from nbadb.agent.context import SchemaContext
from nbadb.agent.safety import MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS, ReadOnlyGuard
from nbadb.chat.catalog import CatalogEntry, SemanticCatalog, default_catalog
from nbadb.chat.sql import QueryResponse

if TYPE_CHECKING:
    from pathlib import Path


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    route: str
    tables: tuple[str, ...]
    catalog_entry: str | None = None
    scd2_notes: tuple[str, ...] = ()


_PATTERNS: list[tuple[re.Pattern[str], QueryPlan]] = [
    (
        re.compile(r"who\s+led\s+(?:in\s+)?scoring", re.IGNORECASE),
        QueryPlan(
            sql="SELECT s.player_id, p.full_name, s.total_pts "
            "FROM agg_player_season s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
            "ORDER BY s.total_pts DESC",
            route="player_season_scoring",
            tables=("agg_player_season", "dim_player"),
            catalog_entry="player season scoring",
            scd2_notes=("dim_player is SCD2; use current rows when asking for current names.",),
        ),
    ),
    (
        re.compile(r"most\s+points", re.IGNORECASE),
        QueryPlan(
            sql="SELECT s.player_id, p.full_name, s.total_pts "
            "FROM agg_player_season s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
            "ORDER BY s.total_pts DESC",
            route="player_season_scoring",
            tables=("agg_player_season", "dim_player"),
            catalog_entry="player season scoring",
            scd2_notes=("dim_player is SCD2; use current rows when asking for current names.",),
        ),
    ),
    (
        re.compile(r"most\s+assists", re.IGNORECASE),
        QueryPlan(
            sql="SELECT s.player_id, p.full_name, s.total_ast "
            "FROM agg_player_season s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
            "ORDER BY s.total_ast DESC",
            route="player_season_assists",
            tables=("agg_player_season", "dim_player"),
            catalog_entry="player season assists",
        ),
    ),
    (
        re.compile(r"most\s+rebounds", re.IGNORECASE),
        QueryPlan(
            sql="SELECT s.player_id, p.full_name, s.total_reb "
            "FROM agg_player_season s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
            "ORDER BY s.total_reb DESC",
            route="player_season_rebounds",
            tables=("agg_player_season", "dim_player"),
            catalog_entry="player season rebounds",
        ),
    ),
    (
        re.compile(r"team\s+standings|standings", re.IGNORECASE),
        QueryPlan(
            sql="SELECT t.full_name, s.wins, s.losses, s.win_pct "
            "FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id "
            "ORDER BY s.wins DESC",
            route="team_standings",
            tables=("fact_standings", "dim_team"),
            catalog_entry="team standings",
        ),
    ),
    (
        re.compile(r"how\s+many\s+(?:games|records)", re.IGNORECASE),
        QueryPlan(
            sql="SELECT table_name, row_count FROM _pipeline_metadata ORDER BY row_count DESC",
            route="pipeline_inventory",
            tables=("_pipeline_metadata",),
            catalog_entry="pipeline inventory",
        ),
    ),
]

_MIN_ASK_LIMIT = 1


def _clamp_ask_limit(limit: int) -> int:
    return max(_MIN_ASK_LIMIT, min(limit, MAX_RESULT_ROWS))


def _sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


def _plan_from_entry(entry: CatalogEntry) -> QueryPlan:
    return QueryPlan(
        sql=entry.sql_template,
        route=entry.route,
        tables=entry.tables,
        catalog_entry=entry.name,
        scd2_notes=entry.scd2_notes(),
    )


class QueryAgent:
    def __init__(self, duckdb_path: Path, catalog: SemanticCatalog | None = None) -> None:
        self._path = duckdb_path
        self._guard = ReadOnlyGuard()
        self._catalog = catalog or default_catalog()
        self._context = SchemaContext(duckdb_path, catalog=self._catalog)

    def ask(self, question: str, limit: int = 10) -> str:
        return self.ask_result(question, limit=limit).render_text()

    def ask_result(self, question: str, limit: int = 10) -> QueryResponse:
        max_rows = _clamp_ask_limit(limit)
        plan = self._match_pattern(question)
        if plan is None:
            return QueryResponse(
                question=question,
                route="unsupported",
                schema_context=self._context.build_prompt_context(question=question),
                tables=self._catalog.table_hints(question),
                max_rows=max_rows,
            )
        error = self._guard.validate(plan.sql)
        if error:
            return QueryResponse(
                question=question,
                route=plan.route,
                sql=plan.sql,
                tables=plan.tables,
                error=f"Query blocked: {error}",
                max_rows=max_rows,
                metadata=self._response_metadata(plan, plan.sql),
            )
        sql = self._guard.wrap_with_limit(plan.sql, max_rows=max_rows)
        return self._execute(question=question, plan=plan, sql=sql, max_rows=max_rows)

    def _response_metadata(self, plan: QueryPlan, sql: str) -> dict[str, object]:
        metadata: dict[str, object] = {"sql_hash": _sql_hash(sql)}
        if plan.catalog_entry:
            metadata["catalog_entry"] = plan.catalog_entry
        if plan.scd2_notes:
            metadata["scd2_notes"] = list(plan.scd2_notes)
        return metadata

    def _match_pattern(self, question: str) -> QueryPlan | None:
        for pattern, plan in _PATTERNS:
            if pattern.search(question):
                return plan
        entry = self._catalog.match_route(question)
        if entry is not None:
            return _plan_from_entry(entry)
        return None

    def _execute(self, *, question: str, plan: QueryPlan, sql: str, max_rows: int) -> QueryResponse:
        started = perf_counter()
        metadata = self._response_metadata(plan, sql)
        try:
            with duckdb.connect(str(self._path), read_only=True) as conn:
                conn.execute("SET enable_external_access = false")
                conn.execute(f"SET statement_timeout='{int(QUERY_TIMEOUT_SECONDS)}s'")
                dry_run_error = self._guard.dry_run(conn, sql)
                if dry_run_error:
                    return QueryResponse(
                        question=question,
                        route=plan.route,
                        sql=sql,
                        tables=plan.tables,
                        error=dry_run_error,
                        max_rows=max_rows,
                        metadata=metadata,
                    )
                result = conn.execute(sql)
                columns = [desc[0] for desc in result.description]
                rows = result.fetchall()
                elapsed_ms = (perf_counter() - started) * 1000
                return QueryResponse(
                    question=question,
                    route=plan.route,
                    sql=sql,
                    columns=tuple(columns),
                    rows=tuple(tuple(row) for row in rows),
                    tables=plan.tables,
                    max_rows=max_rows,
                    elapsed_ms=elapsed_ms,
                    metadata=metadata,
                )
        except duckdb.Error:
            return QueryResponse(
                question=question,
                route=plan.route,
                sql=sql,
                tables=plan.tables,
                error="Query execution failed. Please try a different question.",
                max_rows=max_rows,
                metadata=metadata,
            )
