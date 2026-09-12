from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from time import perf_counter
from typing import TYPE_CHECKING, Literal

import duckdb

from nbadb.agent.context import SchemaContext
from nbadb.agent.entity import resolve_entities
from nbadb.agent.safety import MAX_RESULT_ROWS, ReadOnlyGuard
from nbadb.agent.season_bind import (
    default_season_bind,
    parse_season_bind,
    resolve_season_bind,
    validate_season_year,
)
from nbadb.chat.catalog import CatalogEntry, SemanticCatalog, default_catalog
from nbadb.chat.catalog.apply_bind import apply_season_bind
from nbadb.chat.catalog.entity_meta import (
    RouteEntityMeta,
    apply_entity_bind,
    entity_meta_for,
    question_has_entity_intent,
)
from nbadb.chat.catalog.route_meta import (
    WarehouseSeasonProbe,
    season_meta_for,
)
from nbadb.chat.sql import QueryResponse

if TYPE_CHECKING:
    from pathlib import Path

NeedsReason = Literal[
    "invalid_season_year",
    "unsupported_season_year",
    "unsupported_season_type",
    "missing_season_year",
    "ambiguous_entity",
    "unresolved_entity",
]


@dataclass(frozen=True)
class QueryPlan:
    sql: str
    route: str
    tables: tuple[str, ...]
    catalog_entry: str | None = None
    scd2_notes: tuple[str, ...] = ()
    season_year: str | None = None
    season_type: str | None = None
    season_source: str | None = None
    warnings: tuple[str, ...] = ()
    needs_reason: NeedsReason | None = None
    parameters: tuple[object, ...] = ()
    entity_ids: tuple[int, ...] = ()
    entity_names: tuple[str, ...] = ()


@dataclass(frozen=True)
class _WarehouseSeasonLookup:
    season_year: str | None
    warning: str | None = None


_MIN_ASK_LIMIT = 1


def _clamp_ask_limit(limit: int) -> int:
    return max(_MIN_ASK_LIMIT, min(limit, MAX_RESULT_ROWS))


def _sql_hash(sql: str) -> str:
    return hashlib.sha256(sql.encode()).hexdigest()[:16]


_NEEDS_PARAM_MESSAGES: dict[NeedsReason, str] = {
    "invalid_season_year": "Specify a valid season year like 2024-25.",
    "unsupported_season_year": "This question route does not support a season year.",
    "unsupported_season_type": "This question route does not support a season type.",
    "missing_season_year": ("Specify a season year like 2024-25 (or ask for this/last season)."),
    "ambiguous_entity": "Specify one unambiguous player or team name.",
    "unresolved_entity": "Specify a player or team name present in this warehouse.",
}
_WAREHOUSE_PROBE_FALLBACK_WARNING = (
    "Warehouse season lookup was unavailable; used the calendar season."
)


class QueryAgent:
    def __init__(self, duckdb_path: Path, catalog: SemanticCatalog | None = None) -> None:
        self._path = duckdb_path
        self._guard = ReadOnlyGuard()
        self._catalog = catalog or default_catalog()
        self._context = SchemaContext(duckdb_path, catalog=self._catalog)

    def _warehouse_season_year(
        self,
        probe: WarehouseSeasonProbe,
        *,
        season_type: str | None,
        entity_meta: RouteEntityMeta,
        entity_ids: tuple[int, ...],
    ) -> _WarehouseSeasonLookup:
        """Execute one request-local route probe, falling back without leakage."""
        try:
            with duckdb.connect(str(self._path), read_only=True) as conn:
                conn.execute("SET enable_external_access = false")
                sql, entity_parameters = apply_entity_bind(
                    probe.sql,
                    entity_meta,
                    entity_ids,
                    for_probe=True,
                )
                parameters: tuple[object, ...] = (
                    *((season_type,) if season_type is not None else ()),
                    *entity_parameters,
                )
                if parameters:
                    row = conn.execute(sql, parameters).fetchone()
                else:
                    row = conn.execute(sql).fetchone()
        except (duckdb.Error, ValueError):
            return _WarehouseSeasonLookup(None, _WAREHOUSE_PROBE_FALLBACK_WARNING)
        if row and row[0] is not None:
            valid = validate_season_year(str(row[0]).strip())
            if valid is not None:
                return _WarehouseSeasonLookup(valid)
        return _WarehouseSeasonLookup(None, _WAREHOUSE_PROBE_FALLBACK_WARNING)

    @staticmethod
    def _needs_plan(entry: CatalogEntry, reason: NeedsReason) -> QueryPlan:
        return QueryPlan(
            sql="",
            route="needs_params",
            tables=entry.tables,
            catalog_entry=entry.name,
            scd2_notes=entry.scd2_notes(),
            needs_reason=reason,
        )

    def _plan_from_entry(self, entry: CatalogEntry, question: str) -> QueryPlan:
        meta = season_meta_for(entry.route)
        entity_meta = entity_meta_for(entry.route)
        parsed = parse_season_bind(question)
        extracted = parsed.bind
        if parsed.invalid_year_token is not None:
            return self._needs_plan(entry, "invalid_season_year")
        if extracted.season_year is not None and not meta.requires_year:
            return self._needs_plan(entry, "unsupported_season_year")
        if extracted.season_type is not None and not meta.requires_type:
            return self._needs_plan(entry, "unsupported_season_type")

        entity_ids: tuple[int, ...] = ()
        entity_names: tuple[str, ...] = ()
        required_entities = entity_meta.required_count(question)
        if entity_meta.kind != "none" and (
            required_entities or question_has_entity_intent(entry, question)
        ):
            resolution = resolve_entities(
                self._path,
                entity_meta,
                question,
                required_count=required_entities,
            )
            if resolution.status == "ambiguous":
                return self._needs_plan(entry, "ambiguous_entity")
            if resolution.status == "unresolved":
                return self._needs_plan(entry, "unresolved_entity")
            entity_ids = tuple(item.entity_id for item in resolution.identities)
            entity_names = tuple(item.display_name for item in resolution.identities)

        lookup: _WarehouseSeasonLookup | None = None
        default_year: str | None = None
        if meta.requires_year and extracted.season_year is None:
            if meta.probe is None:
                return self._needs_plan(entry, "missing_season_year")
            effective_type = extracted.season_type
            if meta.requires_type and effective_type is None:
                effective_type = default_season_bind().season_type
            lookup = self._warehouse_season_year(
                meta.probe,
                season_type=effective_type if meta.requires_type else None,
                entity_meta=entity_meta,
                entity_ids=entity_ids,
            )
            default_year = lookup.season_year

        bind = resolve_season_bind(
            question,
            requires_year=meta.requires_year,
            requires_type=meta.requires_type,
            default_year=default_year,
        )
        if lookup is not None and lookup.warning is not None:
            bind = replace(bind, warnings=(*bind.warnings, lookup.warning))
        if meta.requires_year and bind.season_year is None:
            return self._needs_plan(entry, "missing_season_year")
        sql = apply_season_bind(entry.sql_template, bind, route=entry.route, meta=meta)
        sql, parameters = apply_entity_bind(sql, entity_meta, entity_ids)
        return QueryPlan(
            sql=sql,
            route=entry.route,
            tables=entry.tables,
            catalog_entry=entry.name,
            scd2_notes=entry.scd2_notes(),
            season_year=bind.season_year,
            season_type=bind.season_type,
            season_source=(bind.source if meta.requires_year or meta.requires_type else None),
            warnings=bind.warnings,
            parameters=parameters,
            entity_ids=entity_ids,
            entity_names=entity_names,
        )

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
        if plan.route == "needs_params":
            reason = plan.needs_reason or "missing_season_year"
            return QueryResponse(
                question=question,
                route="needs_params",
                sql=None,
                tables=plan.tables,
                warnings=plan.warnings,
                max_rows=max_rows,
                metadata=self._response_metadata(plan, None),
                schema_context=_NEEDS_PARAM_MESSAGES[reason],
            )
        error = self._guard.validate(plan.sql)
        if error:
            return QueryResponse(
                question=question,
                route="blocked",
                sql=plan.sql,
                tables=plan.tables,
                error=f"Query blocked: {error}",
                max_rows=max_rows,
                metadata=self._response_metadata(plan, plan.sql),
            )
        sql = self._guard.wrap_with_limit(plan.sql, max_rows=max_rows)
        return self._execute(question=question, plan=plan, sql=sql, max_rows=max_rows)

    def _response_metadata(self, plan: QueryPlan, sql: str | None) -> dict[str, object]:
        metadata: dict[str, object] = {}
        if sql:
            metadata["sql_hash"] = _sql_hash(sql)
        if plan.catalog_entry:
            metadata["catalog_entry"] = plan.catalog_entry
        if plan.scd2_notes:
            metadata["scd2_notes"] = list(plan.scd2_notes)
        if plan.season_year:
            metadata["season_year"] = plan.season_year
        if plan.season_type:
            metadata["season_type"] = plan.season_type
        if plan.season_source:
            metadata["season_source"] = plan.season_source
        if plan.needs_reason:
            metadata["needs_reason"] = plan.needs_reason
        if plan.entity_ids:
            metadata["entity_ids"] = list(plan.entity_ids)
        if plan.entity_names:
            metadata["entity_names"] = list(plan.entity_names)
        return metadata

    def _match_pattern(self, question: str) -> QueryPlan | None:
        entry = self._catalog.match_route(question)
        if entry is not None:
            return self._plan_from_entry(entry, question)
        return None

    def _execute(self, *, question: str, plan: QueryPlan, sql: str, max_rows: int) -> QueryResponse:
        started = perf_counter()
        metadata = self._response_metadata(plan, sql)
        try:
            with duckdb.connect(str(self._path), read_only=True) as conn:
                conn.execute("SET enable_external_access = false")
                dry_run_error = self._guard.dry_run(conn, sql, plan.parameters)
                if dry_run_error:
                    return QueryResponse(
                        question=question,
                        route=plan.route,
                        sql=sql,
                        tables=plan.tables,
                        error=dry_run_error,
                        max_rows=max_rows,
                        metadata=metadata,
                        warnings=plan.warnings,
                    )
                result = (
                    conn.execute(sql, plan.parameters) if plan.parameters else conn.execute(sql)
                )
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
                    warnings=plan.warnings,
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
                warnings=plan.warnings,
            )
