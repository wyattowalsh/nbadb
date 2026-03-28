from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING
from unittest.mock import patch

from nbadb.kaggle.metadata import (
    _STAGING_FALLBACKS,
    TABLE_CATEGORIES,
    TABLE_DESCRIPTIONS,
    _build_resources,
    _extract_column_schema,
    _resolve_parquet_resource_path,
    _table_display_name,
    generate_metadata,
)
from nbadb.load.parquet_loader import PARTITIONED_TABLES

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.core.config import NbaDbSettings

_ALL_TABLES = [table for tables in TABLE_CATEGORIES.values() for table in tables]
_TABLE_COUNT = len(_ALL_TABLES)


class TestGenerateMetadata:
    def test_returns_valid_json_with_required_fields(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        for key in ("id", "title", "resources", "licenses", "description", "keywords"):
            assert key in data, f"Missing required field: {key}"

    def test_id_matches_kaggle_dataset(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["id"] == settings.kaggle_dataset

    def test_title_is_specific_to_nba_dataset(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["title"] == "NBA Basketball Database"

    def test_license_is_cc_by_sa(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data["licenses"]) == 1
        assert data["licenses"][0]["name"] == "CC-BY-SA-4.0"

    def test_resources_include_database_files(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        paths = {r["path"] for r in data["resources"]}
        assert "nba.duckdb" in paths
        assert "nba.sqlite" in paths

    def test_resources_count(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data["resources"]) == 2 + _TABLE_COUNT * 2

    def test_subtitle_tracks_catalog_count(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert f"{_TABLE_COUNT}-table star schema" in data["subtitle"]

    def test_no_pipeline_internal_tables_in_resources(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        for resource in data["resources"]:
            assert not resource["path"].startswith("csv/_pipeline")

    def test_overwrites_existing_file(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        output.write_text("{}", encoding="utf-8")
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert "id" in data

    def test_description_is_markdown(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert "# NBA Basketball Database" in desc
        assert "## Source and Provenance" in desc
        assert "## Schema Overview" in desc
        assert "## Getting Started" in desc
        assert "```python" in desc


class TestBuildResources:
    def test_returns_expected_entries(self) -> None:
        resources = _build_resources()
        assert len(resources) == 2 + _TABLE_COUNT * 2

    def test_each_resource_has_path_and_description(self) -> None:
        for r in _build_resources():
            assert "path" in r
            assert "description" in r

    def test_csv_and_parquet_for_each_table(self) -> None:
        resources = _build_resources()
        paths = {r["path"] for r in resources}
        for table in _ALL_TABLES:
            assert f"csv/{table}.csv" in paths, f"Missing CSV: {table}"
            assert any(
                path == f"parquet/{table}" or path == f"parquet/{table}/{table}.parquet"
                for path in paths
            ), f"Missing Parquet: {table}"

    def test_database_files_first(self) -> None:
        resources = _build_resources()
        assert resources[0]["path"] == "nba.duckdb"
        assert resources[1]["path"] == "nba.sqlite"

    def test_covers_all_five_categories(self) -> None:
        assert set(TABLE_CATEGORIES.keys()) == {
            "dimensions",
            "bridges",
            "facts",
            "derived",
            "analytics",
        }

    def test_all_tables_have_descriptions(self) -> None:
        missing = [table for table in _ALL_TABLES if table not in TABLE_DESCRIPTIONS]
        assert missing == [], f"Tables missing descriptions: {missing}"

    def test_all_transforms_in_catalog(self) -> None:
        from pathlib import Path

        catalog = set(_ALL_TABLES)
        tables: set[str] = set()
        for path in Path("src/nbadb/transform").rglob("*.py"):
            matches = re.findall(
                r'output_table\s*:\s*ClassVar\[str\]\s*=\s*"([^"]+)"',
                path.read_text(encoding="utf-8"),
            )
            tables.update(matches)
        missing = sorted(tables - catalog)
        assert missing == [], f"Transforms not in TABLE_CATEGORIES: {missing}"

    def test_bridge_tables_present(self) -> None:
        paths = {r["path"] for r in _build_resources()}
        for table in TABLE_CATEGORIES["bridges"]:
            assert f"csv/{table}.csv" in paths

    def test_partitioned_parquet_tables_use_directory_paths(self) -> None:
        catalog_partitioned = set(PARTITIONED_TABLES) & set(_ALL_TABLES)
        for table in catalog_partitioned:
            assert _resolve_parquet_resource_path(table) == f"parquet/{table}"

    def test_non_partitioned_parquet_tables_use_file_paths(self) -> None:
        assert (
            _resolve_parquet_resource_path("dim_player") == "parquet/dim_player/dim_player.parquet"
        )

    def test_data_dir_filters_missing_resources(self, tmp_path: Path) -> None:
        (tmp_path / "csv").mkdir()
        (tmp_path / "parquet" / "dim_player").mkdir(parents=True)
        (tmp_path / "csv" / "dim_player.csv").write_text("player_id\n1\n", encoding="utf-8")
        (tmp_path / "parquet" / "dim_player" / "dim_player.parquet").write_bytes(b"")
        (tmp_path / "nba.sqlite").write_bytes(b"")

        resources = _build_resources(data_dir=tmp_path)
        paths = {r["path"] for r in resources}

        assert paths == {
            "nba.sqlite",
            "csv/dim_player.csv",
            "parquet/dim_player/dim_player.parquet",
        }

    def test_dim_tables_present(self) -> None:
        paths = {r["path"] for r in _build_resources()}
        for dim in ("dim_player", "dim_team", "dim_game", "dim_season"):
            assert f"csv/{dim}.csv" in paths

    def test_fact_tables_present(self) -> None:
        paths = {r["path"] for r in _build_resources()}
        for fact in (
            "fact_player_game_traditional",
            "fact_shot_chart",
            "fact_play_by_play",
        ):
            assert f"csv/{fact}.csv" in paths

    def test_derived_tables_present(self) -> None:
        paths = {r["path"] for r in _build_resources()}
        for agg in ("agg_player_season", "agg_team_season"):
            assert f"csv/{agg}.csv" in paths

    def test_analytics_tables_present(self) -> None:
        paths = {r["path"] for r in _build_resources()}
        for view in (
            "analytics_player_game_complete",
            "analytics_player_season_complete",
        ):
            assert f"csv/{view}.csv" in paths

    def test_no_duplicate_paths(self) -> None:
        paths = [r["path"] for r in _build_resources()]
        assert len(paths) == len(set(paths))


class TestColumnSchemas:
    def test_schema_extraction_returns_fields(self) -> None:
        fields = _extract_column_schema("dim_player")
        assert fields is not None
        assert len(fields) > 0

    def test_schema_fields_have_required_keys(self) -> None:
        fields = _extract_column_schema("dim_player")
        assert fields is not None
        for field in fields:
            assert "name" in field
            assert "type" in field

    def test_schema_types_are_kaggle_compatible(self) -> None:
        valid_types = {"integer", "number", "string", "boolean", "date", "datetime"}
        fields = _extract_column_schema("dim_player")
        assert fields is not None
        for field in fields:
            assert field["type"] in valid_types, f"Unknown type: {field['type']}"

    def test_schema_descriptions_present(self) -> None:
        fields = _extract_column_schema("dim_player")
        assert fields is not None
        described = [f for f in fields if "description" in f]
        assert len(described) > 0

    def test_returns_none_for_unknown_table(self) -> None:
        assert _extract_column_schema("nonexistent_table") is None

    def test_csv_resources_with_star_schemas_have_column_defs(self) -> None:
        resources = _build_resources()
        csv_with_schema = [r for r in resources if r["path"].startswith("csv/") and "schema" in r]
        # At least some CSV resources should have schemas
        assert len(csv_with_schema) > 50

    def test_schema_fields_match_known_columns(self) -> None:
        fields = _extract_column_schema("fact_shot_chart")
        assert fields is not None
        names = {f["name"] for f in fields}
        for col in ("game_id", "player_id", "loc_x", "loc_y", "shot_made_flag"):
            assert col in names, f"Missing expected column: {col}"

    def test_staging_fallback_extracts_columns(self) -> None:
        """Tables in _STAGING_FALLBACKS should get schemas from staging input."""
        for table in _STAGING_FALLBACKS:
            fields = _extract_column_schema(table)
            assert fields is not None, f"Staging fallback failed for {table}"
            assert len(fields) > 0

    def test_staging_fallback_coverage(self) -> None:
        resources = _build_resources()
        csv_with_schema = [r for r in resources if r["path"].startswith("csv/") and "schema" in r]
        assert len(csv_with_schema) >= 90

    def test_parquet_resources_include_schema_when_available(self) -> None:
        resources = _build_resources()
        parquet_with_schema = [
            r for r in resources if r["path"].startswith("parquet/") and "schema" in r
        ]
        assert len(parquet_with_schema) >= 90


class TestResourceNames:
    def test_all_resources_have_name(self) -> None:
        for r in _build_resources():
            assert "name" in r, f"Resource missing name: {r['path']}"

    def test_display_name_strips_prefix(self) -> None:
        assert _table_display_name("dim_player") == "Player"
        assert _table_display_name("fact_shot_chart") == "Shot Chart"
        assert _table_display_name("agg_player_season") == "Player Season"
        assert _table_display_name("bridge_game_official") == "Game Official"
        assert _table_display_name("analytics_head_to_head") == "Head To Head"

    def test_parquet_name_has_suffix(self) -> None:
        resources = _build_resources()
        parquet_resources = [r for r in resources if r["path"].endswith(".parquet")]
        for r in parquet_resources:
            assert r["name"].endswith("(Parquet)")

    def test_database_names(self) -> None:
        resources = _build_resources()
        assert resources[0]["name"] == "DuckDB Database"
        assert resources[1]["name"] == "SQLite Database"


class TestDescription:
    def test_has_table_catalog(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert "## Table Catalog" in desc
        assert "### Dimensions" in desc
        assert "### Bridges" in desc
        assert "### Aggregations" in desc
        assert "### Analytics Views" in desc

    def test_has_export_inventory_section(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert "## Export Inventory" in desc
        assert f"**CSV exports available**: {_TABLE_COUNT}/{_TABLE_COUNT}" in desc

    def test_data_dir_inventory_is_rendered(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        (tmp_path / "csv").mkdir()
        (tmp_path / "parquet" / "dim_player").mkdir(parents=True)
        (tmp_path / "csv" / "dim_player.csv").write_text("player_id\n1\n", encoding="utf-8")
        (tmp_path / "parquet" / "dim_player" / "dim_player.parquet").write_bytes(b"")
        (tmp_path / "nba.duckdb").write_bytes(b"")

        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output, data_dir=tmp_path)

        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert f"**CSV exports available**: 1/{_TABLE_COUNT}" in desc
        assert f"**Parquet exports available**: 1/{_TABLE_COUNT}" in desc
        assert "**Database bundles available**: DuckDB" in desc

    def test_has_key_relationships(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert "## Key Relationships" in desc
        assert "player_id" in desc
        assert "game_id" in desc
        assert "dim_player" in desc

    def test_has_update_schedule(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert "## Update Schedule" in data["description"]

    def test_has_source_and_provenance_section(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        desc = data["description"]
        assert "## Source and Provenance" in desc
        assert "wyattowalsh/basketball" in desc
        assert "https://nbadb.w4w.dev" in desc
        assert "https://github.com/wyattowalsh/nbadb" in desc
