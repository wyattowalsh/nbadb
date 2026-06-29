from __future__ import annotations

import duckdb

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


def test_catalog_match_route_uses_sql_template() -> None:
    catalog = default_catalog()
    entry = catalog.match_route("show the shot chart")
    assert entry is not None
    assert entry.route == "shot_chart"
    assert "fact_shot_chart" in entry.sql_template


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
