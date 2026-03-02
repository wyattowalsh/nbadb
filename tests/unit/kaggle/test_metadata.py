from __future__ import annotations

import json
from typing import TYPE_CHECKING
from unittest.mock import patch

from nbadb.kaggle.metadata import _build_resources, generate_metadata

if TYPE_CHECKING:
    from pathlib import Path

    from nbadb.core.config import NbaDbSettings


class TestGenerateMetadata:
    def test_returns_valid_json_with_required_fields(
        self, tmp_path: Path, settings: NbaDbSettings
    ) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        for key in ("id", "title", "resources", "licenses"):
            assert key in data, f"Missing required field: {key}"

    def test_id_matches_kaggle_dataset(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert data["id"] == settings.kaggle_dataset

    def test_license_is_cc_by_sa(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data["licenses"]) == 1
        assert data["licenses"][0]["name"] == "CC-BY-SA-4.0"

    def test_resources_count_is_55(self, tmp_path: Path, settings: NbaDbSettings) -> None:
        output = tmp_path / "dataset-metadata.json"
        with patch("nbadb.kaggle.metadata.get_settings", return_value=settings):
            generate_metadata(output)
        data = json.loads(output.read_text(encoding="utf-8"))
        assert len(data["resources"]) == 55

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


class TestBuildResources:
    def test_returns_55_entries(self) -> None:
        resources = _build_resources()
        assert len(resources) == 55

    def test_each_resource_has_path_and_description(self) -> None:
        for r in _build_resources():
            assert "path" in r
            assert "description" in r

    def test_all_paths_are_csv(self) -> None:
        for r in _build_resources():
            assert r["path"].startswith("csv/")
            assert r["path"].endswith(".csv")

    def test_covers_all_four_categories(self) -> None:
        categories = {r["description"].split("(")[-1].rstrip(")") for r in _build_resources()}
        assert categories == {"dimensions", "facts", "derived", "analytics"}

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
