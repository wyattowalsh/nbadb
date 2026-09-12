from __future__ import annotations

import re

import duckdb
import pytest

from nbadb.chat.catalog import default_catalog, load_catalog
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


def _create_catalog_table(conn: duckdb.DuckDBPyConnection, table: str) -> None:
    if table == "_pipeline_metadata":
        conn.execute(
            "CREATE TABLE _pipeline_metadata "
            "(table_name VARCHAR, row_count BIGINT, schema_hash VARCHAR)"
        )
        return
    schema_cls = _star_schema_map()[table]
    columns = schema_cls.to_schema().columns
    column_sql = ", ".join(f"{name} {_duckdb_type(name)}" for name in columns)
    conn.execute(f"CREATE TABLE {table} ({column_sql})")


def test_catalog_returns_relevant_entries_for_points_question() -> None:
    catalog = default_catalog()

    entries = catalog.relevant_entries("Who had the most points?")

    assert entries
    assert entries[0].name == "player season scoring"
    assert "agg_player_season" in entries[0].tables


def test_catalog_returns_table_hints_without_duplicates() -> None:
    catalog = default_catalog()

    tables = catalog.table_hints("Who had the most points and scoring title?")

    assert tables == ("agg_player_season", "dim_player")


def test_catalog_does_not_match_short_metric_substrings_inside_words() -> None:
    catalog = default_catalog()

    for question in ("what is a forecast?", "past results", "last"):
        assert catalog.relevant_entries(question) == ()
        assert catalog.table_hints(question) == ()


def test_catalog_still_matches_intended_short_metric_phrases() -> None:
    catalog = default_catalog()

    assert catalog.match_route("show last game") is not None
    assert catalog.match_route("who had the most assists?") is not None
    assert catalog.match_route("team pace leaders") is not None
    assert any(entry.route == "team_season" for entry in catalog.relevant_entries("avg pts"))


def test_catalog_exposes_at_least_twenty_five_routed_intents() -> None:
    catalog = default_catalog()
    routed = [entry for entry in catalog.entries if entry.route and entry.sql_template]
    assert len(routed) >= 25


def test_load_agent_catalog_export_reads_generated_file(tmp_path) -> None:
    from nbadb.chat.catalog import load_agent_catalog_export

    export_path = tmp_path / "agent-catalog.json"
    export_path.write_text(
        (
            '{"version": 1, "table_count": 1, "tables": ['
            '{"table": "agg_player_season", "grain": "player-season", '
            '"agent_intents": ["scoring"]}]}'
        ),
        encoding="utf-8",
    )
    payload = load_agent_catalog_export(export_path)
    assert payload["table_count"] == 1
    assert payload["tables"][0]["table"] == "agg_player_season"


def test_catalog_export_context_lines_include_grain() -> None:
    catalog = default_catalog()
    export = {
        "tables": [
            {
                "table": "agg_player_season",
                "grain": "player-season",
                "scd2_notes": "Filter is_current = TRUE.",
            }
        ]
    }
    lines = catalog.export_context_lines("Who led scoring?", export=export)
    assert any("agg_player_season" in line and "player-season" in line for line in lines)


def test_all_catalog_sql_templates_pass_readonly_guard() -> None:
    from nbadb.chat.catalog.models import validate_catalog_sql_templates

    errors = validate_catalog_sql_templates()
    assert errors == [], errors


def test_catalog_match_route_uses_sql_template() -> None:
    catalog = default_catalog()
    entry = catalog.match_route("show the shot chart")
    assert entry is not None
    assert entry.route == "shot_chart"
    assert "fact_shot_chart" in entry.sql_template


def test_match_route_prefers_more_specific_team_game_log() -> None:
    catalog = default_catalog()
    team = catalog.match_route("team game log")
    player = catalog.match_route("show game log")
    assert team is not None
    assert team.route == "team_game_log"
    assert player is not None
    assert player.route == "player_game_log"


def test_match_route_specificity_is_independent_of_catalog_order() -> None:
    catalog = default_catalog()
    reversed_catalog = type(catalog)(entries=tuple(reversed(catalog.entries)))

    match = reversed_catalog.match_route("team game log")

    assert match is not None
    assert match.route == "team_game_log"


def test_reviewed_route_match_corpus_has_unique_expected_winners() -> None:
    from nbadb.chat.catalog.models import validate_route_match_corpus

    assert validate_route_match_corpus(default_catalog()) == []


def test_default_catalog_fails_closed_on_invalid_route_season_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from nbadb.chat.catalog import route_meta

    monkeypatch.setattr(
        route_meta,
        "validate_route_season_meta",
        lambda _catalog: ["team_standings: invalid test metadata"],
    )

    with pytest.raises(ValueError, match="invalid route season metadata"):
        default_catalog()


def test_route_match_corpus_rejects_cross_route_co_top() -> None:
    from nbadb.chat.catalog import CatalogEntry, SemanticCatalog
    from nbadb.chat.catalog.models import validate_route_match_corpus

    catalog = SemanticCatalog(
        entries=(
            CatalogEntry(
                name="route a",
                description="",
                tables=("dim_game",),
                route="route_a",
                sql_template="SELECT 1",
                patterns=(re.compile(r"shared\s+phrase", re.IGNORECASE),),
            ),
            CatalogEntry(
                name="route b",
                description="",
                tables=("dim_game",),
                route="route_b",
                sql_template="SELECT 1",
                patterns=(re.compile(r"shared\s+phrase", re.IGNORECASE),),
            ),
        )
    )

    errors = validate_route_match_corpus(
        catalog,
        corpus=(("shared phrase", "route_a"),),
    )

    assert len(errors) == 1
    assert "cross-route co-top" in errors[0]
    assert "route_a, route_b" in errors[0]


def test_route_match_corpus_rejects_expected_route_drift() -> None:
    from nbadb.chat.catalog.models import validate_route_match_corpus

    errors = validate_route_match_corpus(
        default_catalog(),
        corpus=(("team game log", "player_game_log"),),
    )

    assert errors == ["'team game log': expected 'player_game_log', got 'team_game_log'"]


def test_route_season_meta_matrix_rejects_phantom_columns() -> None:
    import json
    from pathlib import Path

    from nbadb.chat.catalog.route_meta import ROUTE_SEASON_META

    matrix_path = Path(__file__).with_name("fixtures") / "route_season_meta_matrix.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    routes = matrix["routes"]
    failures: list[str] = []
    for route, meta in ROUTE_SEASON_META.items():
        allowed = routes.get(route)
        if allowed is None:
            failures.append(f"missing matrix row for {route}")
            continue
        if meta.year_column:
            bare = meta.year_column.split(".")[-1]
            if bare not in allowed["year"]:
                failures.append(f"{route}: year {bare} not in {allowed['year']}")
        if meta.type_column:
            bare = meta.type_column.split(".")[-1]
            if bare not in allowed["type"]:
                failures.append(f"{route}: type {bare} not in {allowed['type']}")
    assert failures == [], failures


def test_catalog_routed_sql_templates_bind_to_declared_tables() -> None:
    catalog = default_catalog()
    routed = [entry for entry in catalog.entries if entry.route and entry.sql_template]
    schema_tables = set(_star_schema_map()) | {"_pipeline_metadata"}

    with duckdb.connect(":memory:") as conn:
        for table in sorted({table for entry in routed for table in entry.tables}):
            assert table in schema_tables
            _create_catalog_table(conn, table)

        failures: dict[str, str] = {}
        for entry in routed:
            try:
                conn.execute(f"EXPLAIN {entry.sql_template}")
            except duckdb.Error as exc:
                failures[entry.route] = str(exc)

    assert failures == {}


def test_load_catalog_merges_json_overrides() -> None:
    catalog = load_catalog()
    entry = next(item for item in catalog.entries if item.route == "team_pace")
    assert "pace" in entry.aliases
