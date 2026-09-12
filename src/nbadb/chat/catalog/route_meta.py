"""Per-route season capability metadata for catalog SQL binding."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.chat.catalog.models import SemanticCatalog

from nbadb.chat.catalog.sql_shape import (
    SQLShapeError,
    normalize_static_sql,
    normalized_visibility_rowset,
    split_filterable_sql,
    top_level_clause_present,
)


@dataclass(frozen=True)
class WarehouseSeasonProbe:
    """Static route-rowset query used to select a warehouse-backed season."""

    sql: str
    tables: tuple[str, ...]


@dataclass(frozen=True)
class RouteSeasonMeta:
    """How season filters and route-local discovery attach to catalog SQL."""

    year_column: str | None = None
    type_column: str | None = None
    probe: WarehouseSeasonProbe | None = None

    @property
    def requires_year(self) -> bool:
        return self.year_column is not None

    @property
    def requires_type(self) -> bool:
        return self.type_column is not None


_PLAYER_SEASON_PROBE = WarehouseSeasonProbe(
    sql=(
        "SELECT max(s.season_year) FROM agg_player_season s "
        "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
        "WHERE s.season_type = ?"
    ),
    tables=("agg_player_season", "dim_player"),
)


# Columns and probes use the aliases and complete visibility-defining rowsets from
# each route's catalog SQL template. Declared hint tables that the template does
# not join are intentionally absent from the probe.
ROUTE_SEASON_META: dict[str, RouteSeasonMeta] = {
    "player_season_scoring": RouteSeasonMeta(
        "s.season_year", "s.season_type", _PLAYER_SEASON_PROBE
    ),
    "player_season_assists": RouteSeasonMeta(
        "s.season_year", "s.season_type", _PLAYER_SEASON_PROBE
    ),
    "player_season_rebounds": RouteSeasonMeta(
        "s.season_year", "s.season_type", _PLAYER_SEASON_PROBE
    ),
    "team_standings": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id WHERE s.season_type = ?",
            ("fact_standings", "dim_team"),
        ),
    ),
    "pipeline_inventory": RouteSeasonMeta(),
    "game_count": RouteSeasonMeta(),
    "team_pace": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM agg_team_pace_and_efficiency s "
            "JOIN dim_team t ON s.team_id = t.team_id WHERE s.season_type = ?",
            ("agg_team_pace_and_efficiency", "dim_team"),
        ),
    ),
    "shot_chart": RouteSeasonMeta(
        "s.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_shot_chart s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE",
            ("fact_shot_chart", "dim_player"),
        ),
    ),
    "draft_value": RouteSeasonMeta(),
    "head_to_head": RouteSeasonMeta(
        "h.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(h.season_year) FROM analytics_head_to_head h",
            ("analytics_head_to_head",),
        ),
    ),
    "team_season": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM agg_team_season s "
            "JOIN dim_team t ON s.team_id = t.team_id WHERE s.season_type = ?",
            ("agg_team_season", "dim_team"),
        ),
    ),
    "player_season_complete": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_player_season_complete s "
            "WHERE s.season_type = ?",
            ("analytics_player_season_complete",),
        ),
    ),
    "player_game_log": RouteSeasonMeta(
        "g.season_year",
        "g.season_type",
        WarehouseSeasonProbe(
            "SELECT max(g.season_year) FROM analytics_player_game_complete s "
            "JOIN dim_game g ON s.game_id = g.game_id WHERE g.season_type = ?",
            ("analytics_player_game_complete", "dim_game"),
        ),
    ),
    # These analytics outputs have season_year but no season_type column.
    "clutch_performance": RouteSeasonMeta(
        "c.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(c.season_year) FROM analytics_clutch_performance c",
            ("analytics_clutch_performance",),
        ),
    ),
    "player_matchups": RouteSeasonMeta(
        "m.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(m.season_year) FROM analytics_player_matchup m",
            ("analytics_player_matchup",),
        ),
    ),
    "franchise_history": RouteSeasonMeta(),
    "team_game_log": RouteSeasonMeta(
        "s.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_team_game_complete s",
            ("analytics_team_game_complete",),
        ),
    ),
    "player_splits": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_player_general_splits s "
            "WHERE s.season_type = ?",
            ("analytics_player_general_splits",),
        ),
    ),
    "team_splits": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_team_general_splits s "
            "WHERE s.season_type = ?",
            ("analytics_team_general_splits",),
        ),
    ),
    "player_impact": RouteSeasonMeta(
        "s.season_year",
        "s.season_type",
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_player_impact s WHERE s.season_type = ?",
            ("analytics_player_impact",),
        ),
    ),
    "league_benchmarks": RouteSeasonMeta(
        "season_year",
        "season_type",
        WarehouseSeasonProbe(
            "SELECT max(season_year) FROM analytics_league_benchmarks WHERE season_type = ?",
            ("analytics_league_benchmarks",),
        ),
    ),
    "game_summary": RouteSeasonMeta(
        "season_year",
        "season_type",
        WarehouseSeasonProbe(
            "SELECT max(season_year) FROM analytics_game_summary WHERE season_type = ?",
            ("analytics_game_summary",),
        ),
    ),
    "shooting_efficiency": RouteSeasonMeta(
        "s.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM analytics_shooting_efficiency s",
            ("analytics_shooting_efficiency",),
        ),
    ),
    "team_roster": RouteSeasonMeta(
        "b.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(b.season_year) FROM bridge_player_team_season b "
            "JOIN dim_player p ON b.player_id = p.player_id AND p.is_current = TRUE "
            "JOIN dim_team t ON b.team_id = t.team_id",
            ("bridge_player_team_season", "dim_player", "dim_team"),
        ),
    ),
    "team_box_score": RouteSeasonMeta(
        "g.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(g.season_year) FROM fact_box_score_team b "
            "JOIN dim_team t ON b.team_id = t.team_id "
            "JOIN dim_game g ON b.game_id = g.game_id",
            ("fact_box_score_team", "dim_team", "dim_game"),
        ),
    ),
    "player_box_score": RouteSeasonMeta(
        "b.season_year",
        None,
        WarehouseSeasonProbe(
            "SELECT max(b.season_year) FROM fact_player_game_traditional b "
            "JOIN dim_player p ON b.player_id = p.player_id AND p.is_current = TRUE",
            ("fact_player_game_traditional", "dim_player"),
        ),
    ),
}

_TABLE_REFERENCE_RE = re.compile(r"\b(?:FROM|JOIN)\s+([A-Za-z_][A-Za-z0-9_]*)\b", re.IGNORECASE)


def validate_route_season_meta(
    catalog: SemanticCatalog,
    *,
    metadata: Mapping[str, RouteSeasonMeta] | None = None,
) -> list[str]:
    """Return fail-closed static contract errors for route season metadata."""
    from nbadb.agent.safety import ReadOnlyGuard

    target = ROUTE_SEASON_META if metadata is None else metadata
    routed = {entry.route: entry for entry in catalog.entries if entry.route and entry.sql_template}
    errors: list[str] = []

    for route in sorted(set(routed) - set(target)):
        errors.append(f"{route}: missing route season metadata")
    for route in sorted(set(target) - set(routed)):
        errors.append(f"{route}: metadata has no routed catalog entry")

    guard = ReadOnlyGuard()
    for route, entry in routed.items():
        meta = target.get(route)
        if meta is None:
            continue
        if meta.requires_type and not meta.requires_year:
            errors.append(f"{route}: season type requires a season year")
        if meta.requires_year and meta.probe is None:
            errors.append(f"{route}: year-filterable route requires a probe")
            continue
        if not meta.requires_year and meta.probe is not None:
            errors.append(f"{route}: route without a year must not define a probe")
            continue
        probe = meta.probe
        if probe is None:
            continue
        year_column = meta.year_column
        if year_column is None:
            errors.append(f"{route}: probe requires a season-year column")
            continue
        if not probe.sql.strip():
            errors.append(f"{route}: probe SQL is empty")
            continue
        if not probe.tables:
            errors.append(f"{route}: probe tables are empty")
        referenced = tuple(_TABLE_REFERENCE_RE.findall(probe.sql))
        if referenced != probe.tables:
            errors.append(f"{route}: probe tables {probe.tables!r} do not match SQL {referenced!r}")
        undeclared = set(probe.tables) - set(entry.tables)
        if undeclared:
            errors.append(f"{route}: probe uses undeclared tables {sorted(undeclared)!r}")
        problem = guard.validate(probe.sql)
        if problem:
            errors.append(f"{route}: unsafe probe SQL: {problem}")
        placeholders = probe.sql.count("?")
        expected_placeholders = 1 if meta.requires_type else 0
        if placeholders != expected_placeholders:
            errors.append(
                f"{route}: expected {expected_placeholders} probe placeholders, "
                f"found {placeholders}"
            )
        try:
            normalized_probe = normalize_static_sql(probe.sql)
            expected_select = normalize_static_sql(f"SELECT max({year_column}) FROM")
            if not normalized_probe.startswith(f"{expected_select} "):
                errors.append(f"{route}: probe does not select max({year_column})")
            if meta.type_column:
                expected_type = normalize_static_sql(f"{meta.type_column} = ?")
                if expected_type not in normalized_probe:
                    errors.append(f"{route}: probe does not bind {meta.type_column}")
            probe_shape = split_filterable_sql(probe.sql)
            if probe_shape.suffix or top_level_clause_present(
                entry.sql_template,
                "having",
                "qualify",
                "limit",
                "offset",
                "fetch",
                "union",
                "intersect",
                "except",
            ):
                raise SQLShapeError("route rowset has unsupported trailing semantics")
            template_source, fixed_predicate = normalized_visibility_rowset(entry.sql_template)
            probe_source, probe_predicate = normalized_visibility_rowset(probe.sql)
        except SQLShapeError:
            errors.append(f"{route}: probe rowset differs from catalog SQL")
            continue

        expected_probe_predicate = fixed_predicate
        if meta.type_column:
            type_predicate = normalize_static_sql(f"{meta.type_column} = ?")
            expected_probe_predicate = (
                f"( {fixed_predicate} ) and {type_predicate}" if fixed_predicate else type_predicate
            )
        if (probe_source, probe_predicate) != (
            template_source,
            expected_probe_predicate,
        ):
            errors.append(f"{route}: probe rowset differs from catalog SQL")

    return errors


def season_meta_for(route: str) -> RouteSeasonMeta:
    return ROUTE_SEASON_META.get(route, RouteSeasonMeta())
