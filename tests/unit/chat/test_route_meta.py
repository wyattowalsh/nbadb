from __future__ import annotations

from dataclasses import replace

import duckdb
import pytest

from nbadb.chat.catalog import default_catalog
from nbadb.chat.catalog.entity_meta import (
    ROUTE_ENTITY_META,
    apply_entity_bind,
    question_has_entity_intent,
    validate_route_entity_meta,
)
from nbadb.chat.catalog.models import SemanticCatalog
from nbadb.chat.catalog.route_meta import (
    ROUTE_SEASON_META,
    WarehouseSeasonProbe,
    validate_route_season_meta,
)
from nbadb.transform.pipeline import _star_schema_map


def _duckdb_type(column_name: str) -> str:
    if column_name == "is_current":
        return "BOOLEAN"
    if column_name.endswith("_id") and column_name != "game_id":
        return "BIGINT"
    text_markers = (
        "abbr",
        "city",
        "date",
        "game_id",
        "group",
        "matchup",
        "name",
        "phase",
        "season",
        "slug",
        "type",
        "window",
        "zone",
    )
    if any(marker in column_name for marker in text_markers):
        return "VARCHAR"
    return "DOUBLE"


def _create_table(conn: duckdb.DuckDBPyConnection, table: str) -> None:
    schema_cls = _star_schema_map()[table]
    columns = schema_cls.to_schema().columns
    column_sql = ", ".join(f"{name} {_duckdb_type(name)}" for name in columns)
    conn.execute(f"CREATE TABLE {table} ({column_sql})")


def test_route_season_capability_inventory() -> None:
    year_routes = [meta for meta in ROUTE_SEASON_META.values() if meta.requires_year]
    type_routes = [meta for meta in ROUTE_SEASON_META.values() if meta.requires_type]
    unfiltered_routes = [meta for meta in ROUTE_SEASON_META.values() if not meta.requires_year]

    assert len(year_routes) == 22
    assert len(type_routes) == 13
    assert len(unfiltered_routes) == 4
    assert ROUTE_SEASON_META["clutch_performance"].type_column is None
    assert ROUTE_SEASON_META["player_matchups"].type_column is None


def test_route_entity_capability_inventory_and_intent_detection() -> None:
    catalog = default_catalog()
    entries = {entry.route: entry for entry in catalog.entries}

    assert len(ROUTE_ENTITY_META) == 26
    assert validate_route_entity_meta(catalog) == []
    assert ROUTE_ENTITY_META["league_benchmarks"].kind == "none"
    assert ROUTE_ENTITY_META["player_game_log"].kind == "player"
    assert ROUTE_ENTITY_META["team_roster"].kind == "team"
    assert ROUTE_ENTITY_META["head_to_head"].max_entities == 2
    assert not question_has_entity_intent(entries["player_game_log"], "show game log")
    assert question_has_entity_intent(entries["player_game_log"], "show LeBron James game log")
    assert not question_has_entity_intent(entries["head_to_head"], "head to head records")


def test_route_season_metadata_validates_against_catalog() -> None:
    assert validate_route_season_meta(default_catalog()) == []


def test_route_season_validator_rejects_unsafe_or_mismatched_probe() -> None:
    metadata = dict(ROUTE_SEASON_META)
    metadata["shot_chart"] = replace(
        metadata["shot_chart"],
        probe=WarehouseSeasonProbe(
            "DELETE FROM undeclared_table",
            ("undeclared_table",),
        ),
    )

    errors = validate_route_season_meta(default_catalog(), metadata=metadata)

    assert any("undeclared tables" in error for error in errors)
    assert any("unsafe probe SQL" in error for error in errors)
    assert any("probe rowset differs" in error for error in errors)


def test_route_season_validator_requires_fixed_visibility_predicates() -> None:
    catalog = default_catalog()
    entries = tuple(
        replace(
            entry,
            sql_template=entry.sql_template.replace(
                "ORDER BY s.wins DESC",
                "WHERE s.wins >= 0 ORDER BY s.wins DESC",
            ),
        )
        if entry.route == "team_standings"
        else entry
        for entry in catalog.entries
    )
    fixed_catalog = SemanticCatalog(entries)

    errors = validate_route_season_meta(fixed_catalog)

    assert "team_standings: probe rowset differs from catalog SQL" in errors

    metadata = dict(ROUTE_SEASON_META)
    metadata["team_standings"] = replace(
        metadata["team_standings"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id "
            "WHERE (s.wins >= 0) AND s.season_type = ?",
            ("fact_standings", "dim_team"),
        ),
    )

    assert not any(
        error == "team_standings: probe rowset differs from catalog SQL"
        for error in validate_route_season_meta(fixed_catalog, metadata=metadata)
    )


def test_route_season_validator_rejects_type_predicate_below_or() -> None:
    catalog = default_catalog()
    entries = tuple(
        replace(
            entry,
            sql_template=entry.sql_template.replace(
                "ORDER BY s.wins DESC",
                "WHERE s.wins >= 0 OR s.losses >= 0 ORDER BY s.wins DESC",
            ),
        )
        if entry.route == "team_standings"
        else entry
        for entry in catalog.entries
    )
    fixed_catalog = SemanticCatalog(entries)
    metadata = dict(ROUTE_SEASON_META)
    metadata["team_standings"] = replace(
        metadata["team_standings"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id "
            "WHERE s.wins >= 0 OR s.losses >= 0 AND s.season_type = ?",
            ("fact_standings", "dim_team"),
        ),
    )

    assert "team_standings: probe rowset differs from catalog SQL" in (
        validate_route_season_meta(fixed_catalog, metadata=metadata)
    )

    metadata["team_standings"] = replace(
        metadata["team_standings"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id "
            "WHERE (s.wins >= 0 OR s.losses >= 0) AND s.season_type = ?",
            ("fact_standings", "dim_team"),
        ),
    )
    assert "team_standings: probe rowset differs from catalog SQL" not in (
        validate_route_season_meta(fixed_catalog, metadata=metadata)
    )


def test_route_season_validator_preserves_fixed_literal_case() -> None:
    catalog = default_catalog()
    entries = tuple(
        replace(
            entry,
            sql_template=entry.sql_template.replace(
                "ORDER BY s.wins DESC",
                "WHERE t.full_name = 'ABC' ORDER BY s.wins DESC",
            ),
        )
        if entry.route == "team_standings"
        else entry
        for entry in catalog.entries
    )
    metadata = dict(ROUTE_SEASON_META)
    metadata["team_standings"] = replace(
        metadata["team_standings"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_standings s "
            "JOIN dim_team t ON s.team_id = t.team_id "
            "WHERE (t.full_name = 'abc') AND s.season_type = ?",
            ("fact_standings", "dim_team"),
        ),
    )

    assert "team_standings: probe rowset differs from catalog SQL" in (
        validate_route_season_meta(SemanticCatalog(entries), metadata=metadata)
    )


def test_route_season_validator_bounds_malformed_quoted_probe() -> None:
    metadata = dict(ROUTE_SEASON_META)
    metadata["shot_chart"] = replace(
        metadata["shot_chart"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_shot_chart s WHERE s.label = 'unterminated",
            ("fact_shot_chart",),
        ),
    )

    errors = validate_route_season_meta(default_catalog(), metadata=metadata)

    assert "shot_chart: probe rowset differs from catalog SQL" in errors


@pytest.mark.parametrize(
    "suffix",
    (
        "LIMIT 0",
        "GROUP BY s.season_year",
        "HAVING FALSE",
        "UNION ALL SELECT max(s.season_year) FROM fact_shot_chart s",
    ),
)
def test_route_season_validator_rejects_probe_trailing_semantics(suffix: str) -> None:
    metadata = dict(ROUTE_SEASON_META)
    metadata["shot_chart"] = replace(
        metadata["shot_chart"],
        probe=WarehouseSeasonProbe(
            "SELECT max(s.season_year) FROM fact_shot_chart s "
            "JOIN dim_player p ON s.player_id = p.player_id AND p.is_current = TRUE "
            f"{suffix}",
            (
                "fact_shot_chart",
                "dim_player",
                *(("fact_shot_chart",) if suffix.startswith("UNION") else ()),
            ),
        ),
    )

    errors = validate_route_season_meta(default_catalog(), metadata=metadata)

    assert "shot_chart: probe rowset differs from catalog SQL" in errors


def test_every_route_season_probe_explains_against_star_schemas() -> None:
    probes = [meta for meta in ROUTE_SEASON_META.values() if meta.probe is not None]
    tables = sorted(
        {table for meta in probes if meta.probe is not None for table in meta.probe.tables}
    )
    failures: dict[str, str] = {}

    with duckdb.connect(":memory:") as conn:
        for table in tables:
            _create_table(conn, table)
        for route, meta in ROUTE_SEASON_META.items():
            if meta.probe is None:
                continue
            params = ["Regular Season"] if meta.requires_type else []
            try:
                conn.execute(f"EXPLAIN {meta.probe.sql}", params)
            except duckdb.Error as exc:
                failures[route] = str(exc)

    assert failures == {}


def test_every_entity_route_and_probe_explains_with_bound_ids() -> None:
    catalog = default_catalog()
    entries = {entry.route: entry for entry in catalog.entries}
    entity_routes = {
        route: meta for route, meta in ROUTE_ENTITY_META.items() if meta.kind != "none"
    }
    tables = sorted(
        {
            table
            for route in entity_routes
            for table in entries[route].tables
            if table in _star_schema_map()
        }
    )
    failures: dict[str, str] = {}

    with duckdb.connect(":memory:") as conn:
        for table in tables:
            _create_table(conn, table)
        for route, entity_meta in entity_routes.items():
            ids = (1, 2) if entity_meta.max_entities == 2 else (1,)
            try:
                sql, parameters = apply_entity_bind(
                    entries[route].sql_template,
                    entity_meta,
                    ids,
                )
                conn.execute(f"EXPLAIN {sql}", parameters)
                season_meta = ROUTE_SEASON_META[route]
                if season_meta.probe is not None:
                    probe_sql, entity_parameters = apply_entity_bind(
                        season_meta.probe.sql,
                        entity_meta,
                        ids,
                        for_probe=True,
                    )
                    probe_parameters = (
                        *(("Regular Season",) if season_meta.requires_type else ()),
                        *entity_parameters,
                    )
                    conn.execute(f"EXPLAIN {probe_sql}", probe_parameters)
            except (duckdb.Error, ValueError) as exc:
                failures[route] = str(exc)

    assert failures == {}
