from __future__ import annotations

import json
import re
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import patch

import pytest

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
    from nbadb.core.config import NbaDbSettings

_ALL_TABLES = [table for tables in TABLE_CATEGORIES.values() for table in tables]
_TABLE_COUNT = len(_ALL_TABLES)


def _generate_metadata_json(
    tmp_path: Path,
    settings: NbaDbSettings,
    *,
    data_dir: Path | None = None,
) -> dict:
    output = tmp_path / "dataset-metadata.json"
    with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
        generate_metadata(output, data_dir=data_dir)
    return json.loads(output.read_text(encoding="utf-8"))


def _schema_csv_header(table: str = "dim_player") -> str:
    fields = _extract_column_schema(table)
    assert fields is not None
    return ",".join(field["name"] for field in fields)


def _write_schema_csv(root: Path, table: str = "dim_player", *, prefix: str = "") -> Path:
    csv_dir = root / "csv"
    csv_dir.mkdir(exist_ok=True)
    csv_path = csv_dir / f"{table}.csv"
    csv_path.write_text(f"{prefix}{_schema_csv_header(table)}\n", encoding="utf-8")
    return csv_path


class TestGenerateMetadata:
    def test_returns_valid_json_with_required_fields(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        for key in ("id", "title", "resources", "licenses", "description", "keywords"):
            assert key in data, f"Missing required field: {key}"

    def test_top_level_metadata_contract(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert set(data) == {
            "id",
            "id_no",
            "title",
            "subtitle",
            "description",
            "isPrivate",
            "licenses",
            "keywords",
            "collaborators",
            "data",
            "resources",
        }
        assert isinstance(data["id"], str)
        assert data["id_no"] is None
        assert isinstance(data["title"], str)
        assert isinstance(data["subtitle"], str)
        assert isinstance(data["description"], str)
        assert isinstance(data["isPrivate"], bool)
        assert isinstance(data["licenses"], list)
        assert isinstance(data["keywords"], list)
        assert isinstance(data["collaborators"], list)
        assert isinstance(data["data"], list)
        assert isinstance(data["resources"], list)

    def test_id_matches_kaggle_dataset(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert data["id"] == settings.kaggle_dataset

    def test_title_is_specific_to_nba_dataset(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert data["title"] == "NBA Basketball Database"

    def test_license_is_cc_by_sa(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert len(data["licenses"]) == 1
        assert data["licenses"][0]["name"] == "CC-BY-SA-4.0"

    def test_resources_include_database_files(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        paths = {r["path"] for r in data["resources"]}
        assert "nba.duckdb" in paths
        assert "nba.sqlite" in paths

    def test_resources_count(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert len(data["resources"]) == 2 + _TABLE_COUNT * 2

    def test_subtitle_tracks_catalog_count(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert f"{_TABLE_COUNT}-table star schema" in data["subtitle"]

    def test_subtitle_matches_kaggle_length_bounds(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert 20 <= len(data["subtitle"]) <= 80

    def test_subtitle_reflects_data_dir_formats(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        _write_schema_csv(tmp_path)

        data = _generate_metadata_json(tmp_path, settings, data_dir=tmp_path)
        assert "CSV" in data["subtitle"]
        assert "SQL" not in data["subtitle"]

    def test_description_reflects_data_dir_formats(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        _write_schema_csv(tmp_path)

        data = _generate_metadata_json(tmp_path, settings, data_dir=tmp_path)
        desc = data["description"]
        assert "This release includes CSV" in desc
        assert "`csv/<table>.csv`" in desc
        assert "| DuckDB |" not in desc
        assert "| SQLite |" not in desc
        assert "| Parquet |" not in desc
        assert "nba.duckdb\nnba.sqlite" not in desc
        assert "parquet/<table>/..." not in desc

    def test_missing_data_dir_fails_closed(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        with pytest.raises(FileNotFoundError, match="Metadata data_dir does not exist"):
            _generate_metadata_json(tmp_path, settings, data_dir=tmp_path / "missing")

    def test_no_pipeline_internal_tables_in_resources(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
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
        data = _generate_metadata_json(tmp_path, settings)
        desc = data["description"]
        assert "# NBA Basketball Database" in desc
        assert "## Source and Provenance" in desc
        assert "## Start Here" in desc
        assert "## Quick Queries" in desc
        assert "```python" in desc

    def test_metadata_omits_unverified_optional_kaggle_fields(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert "expectedUpdateFrequency" not in data
        assert "userSpecifiedSources" not in data
        assert "image" not in data


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
        catalog = set(_ALL_TABLES)
        tables: set[str] = set()
        transform_root = Path(__file__).parents[3] / "src" / "nbadb" / "transform"
        for path in transform_root.rglob("*.py"):
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

    def test_data_dir_includes_assured_provenance_manifest(self, tmp_path: Path) -> None:
        manifest = tmp_path / "assured-artifact-manifest.json"
        manifest.write_text("{}\n", encoding="utf-8")

        resources = _build_resources(data_dir=tmp_path)

        assert resources == [
            {
                "path": "assured-artifact-manifest.json",
                "name": "Assured Artifact Provenance",
                "description": (
                    "Source commit, extraction chain, coverage fingerprint, and SHA-256 "
                    "inventory for the published database and export files."
                ),
            }
        ]

    def test_data_dir_ignores_empty_non_partitioned_parquet_dir(self, tmp_path: Path) -> None:
        (tmp_path / "parquet" / "dim_player").mkdir(parents=True)

        resources = _build_resources(data_dir=tmp_path)

        assert {r["path"] for r in resources} == set()

    def test_data_dir_detects_partitioned_parquet_files(self, tmp_path: Path) -> None:
        table = "fact_shot_chart"
        assert table in PARTITIONED_TABLES
        partition_dir = tmp_path / "parquet" / table / "season_year=2024-25"
        partition_dir.mkdir(parents=True)
        (partition_dir / "part0.parquet").write_bytes(b"")

        resources = _build_resources(data_dir=tmp_path)

        assert {r["path"] for r in resources} == {f"parquet/{table}"}

    def test_data_dir_ignores_empty_partitioned_parquet_dir(self, tmp_path: Path) -> None:
        table = "fact_shot_chart"
        assert table in PARTITIONED_TABLES
        (tmp_path / "parquet" / table / "season_year=2024-25").mkdir(parents=True)

        resources = _build_resources(data_dir=tmp_path)

        assert {r["path"] for r in resources} == set()

    def test_data_dir_generation_rejects_csv_header_mismatch(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        (tmp_path / "csv").mkdir()
        (tmp_path / "csv" / "dim_player.csv").write_text("wrong_column\n1\n", encoding="utf-8")

        with (
            patch("nbadb.kaggle.metadata.get_settings", return_value=settings),
            pytest.raises(ValueError, match="CSV header mismatch for csv/dim_player.csv"),
        ):
            generate_metadata(output, data_dir=tmp_path)

    def test_data_dir_generation_accepts_csv_schema_order(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        _write_schema_csv(tmp_path)

        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output, data_dir=tmp_path)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert {r["path"] for r in data["resources"]} == {"csv/dim_player.csv"}

    def test_data_dir_generation_accepts_bom_csv_header(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        _write_schema_csv(tmp_path, prefix="\ufeff")

        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output, data_dir=tmp_path)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert {r["path"] for r in data["resources"]} == {"csv/dim_player.csv"}

    def test_data_dir_generation_rejects_empty_csv(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        (tmp_path / "csv").mkdir()
        (tmp_path / "csv" / "dim_player.csv").write_text("", encoding="utf-8")

        with (
            patch("nbadb.kaggle.metadata.get_settings", return_value=settings),
            pytest.raises(ValueError, match="file is empty"),
        ):
            generate_metadata(output, data_dir=tmp_path)

    def test_data_dir_generation_rejects_reordered_csv_header(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        header = _schema_csv_header().split(",")
        (tmp_path / "csv").mkdir()
        (tmp_path / "csv" / "dim_player.csv").write_text(
            ",".join(reversed(header)) + "\n",
            encoding="utf-8",
        )

        with (
            patch("nbadb.kaggle.metadata.get_settings", return_value=settings),
            pytest.raises(ValueError, match="CSV header mismatch for csv/dim_player.csv"),
        ):
            generate_metadata(output, data_dir=tmp_path)

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

    def test_catalog_csv_schema_coverage_is_explicit(self) -> None:
        schema_resources = {
            r["path"].removeprefix("csv/").removesuffix(".csv")
            for r in _build_resources()
            if r["path"].startswith("csv/") and "schema" in r
        }
        missing = sorted(set(_ALL_TABLES) - schema_resources)
        assert missing == [], f"Catalog tables missing Kaggle resource schemas: {missing}"

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
        data = _generate_metadata_json(tmp_path, settings)
        desc = data["description"]
        assert "## Table Catalog" in desc
        assert "### Dimensions" in desc
        assert "### Bridges" in desc
        assert "### Aggregations" in desc
        assert "### Analytics Views" in desc

    def test_has_export_inventory_section(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        desc = data["description"]
        assert "## Export Inventory" in desc
        assert f"**CSV exports available**: {_TABLE_COUNT}/{_TABLE_COUNT}" in desc

    def test_data_dir_inventory_is_rendered(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        _write_schema_csv(tmp_path)
        (tmp_path / "parquet" / "dim_player").mkdir(parents=True)
        (tmp_path / "parquet" / "dim_player" / "dim_player.parquet").write_bytes(b"")
        (tmp_path / "nba.duckdb").write_bytes(b"")

        data = _generate_metadata_json(tmp_path, settings, data_dir=tmp_path)
        desc = data["description"]
        assert f"**CSV exports available**: 1/{_TABLE_COUNT}" in desc
        assert f"**Parquet exports available**: 1/{_TABLE_COUNT}" in desc
        assert "**Database bundles available**: DuckDB" in desc

    def test_has_key_relationships(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        desc = data["description"]
        assert "## Key Relationships" in desc
        assert "player_id" in desc
        assert "game_id" in desc
        assert "dim_player" in desc

    def test_has_update_schedule(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        assert "## Refresh And Versioning" in data["description"]

    def test_has_source_and_provenance_section(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        data = _generate_metadata_json(tmp_path, settings)
        desc = data["description"]
        assert "## Source and Provenance" in desc
        assert "wyattowalsh/basketball" in desc
        assert "https://nbadb.w4w.dev" in desc
        assert "https://github.com/wyattowalsh/nbadb" in desc

    def test_description_has_reuse_and_risk_sections(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        desc = _generate_metadata_json(tmp_path, settings)["description"]
        for heading in (
            "## Intended Uses",
            "## Not Intended For",
            "## Citation And Attribution",
            "## License",
        ):
            assert heading in desc
        assert "not an official NBA records system" in desc
        assert "upstream-unavailable" in desc
