"""Tests for uncovered dimension transformers: arena, college, shot_zone, official, team."""

from __future__ import annotations

import polars as pl


class TestDimArenaTransformer:
    def test_transform_basic(self) -> None:
        from nbadb.transform.dimensions.dim_arena import DimArenaTransformer

        staging = {
            "stg_schedule": pl.DataFrame(
                {"arena_name": ["Arena1", "Arena2"], "arena_city": ["City1", "City2"]}
            ).lazy(),
            "stg_league_game_log": pl.DataFrame(
                {"arena_name": ["Arena2", "Arena3"], "arena_city": ["City2", "City3"]}
            ).lazy(),
            "stg_arena_info": pl.DataFrame(
                {
                    "arena_name": ["Arena1", "Arena2", "Arena3"],
                    "arena_city": ["City1", "City2", "City3"],
                    "arena_state": ["ST1", "ST2", "ST3"],
                    "arena_country": ["US", "US", "CA"],
                    "arena_timezone": ["ET", "CT", "PT"],
                }
            ).lazy(),
        }
        t = DimArenaTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 3
        assert "arena_id" in result.columns
        assert "arena_name" in result.columns
        assert "arena_timezone" in result.columns

    def test_deduplicates_arenas(self) -> None:
        from nbadb.transform.dimensions.dim_arena import DimArenaTransformer

        staging = {
            "stg_schedule": pl.DataFrame(
                {"arena_name": ["Arena1"], "arena_city": ["City1"]}
            ).lazy(),
            "stg_league_game_log": pl.DataFrame(
                {"arena_name": ["Arena1"], "arena_city": ["City1"]}
            ).lazy(),
            "stg_arena_info": pl.DataFrame(
                {
                    "arena_name": ["Arena1"],
                    "arena_city": ["City1"],
                    "arena_state": ["ST1"],
                    "arena_country": ["US"],
                    "arena_timezone": ["ET"],
                }
            ).lazy(),
        }
        t = DimArenaTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 1

    def test_output_table_name(self) -> None:
        from nbadb.transform.dimensions.dim_arena import DimArenaTransformer

        assert DimArenaTransformer.output_table == "dim_arena"


class TestDimCollegeTransformer:
    def test_transform_basic(self) -> None:
        from nbadb.transform.dimensions.dim_college import DimCollegeTransformer

        staging = {
            "stg_player_college": pl.DataFrame(
                {"college_name": ["Duke", "UNC", "Duke", None]}
            ).lazy(),
        }
        t = DimCollegeTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 2  # Duke, UNC (null dropped)
        assert "college_id" in result.columns
        assert "college_name" in result.columns

    def test_sorted_output(self) -> None:
        from nbadb.transform.dimensions.dim_college import DimCollegeTransformer

        staging = {
            "stg_player_college": pl.DataFrame(
                {"college_name": ["Zeta U", "Alpha U", "Mid U"]}
            ).lazy(),
        }
        t = DimCollegeTransformer()
        result = t.transform(staging)
        names = result["college_name"].to_list()
        assert names == sorted(names)

    def test_output_table_name(self) -> None:
        from nbadb.transform.dimensions.dim_college import DimCollegeTransformer

        assert DimCollegeTransformer.output_table == "dim_college"


class TestDimShotZoneTransformer:
    def test_transform_basic(self) -> None:
        from nbadb.transform.dimensions.dim_shot_zone import DimShotZoneTransformer

        staging = {
            "stg_shot_chart": pl.DataFrame(
                {
                    "shot_zone_basic": ["Restricted Area", "Mid-Range", "Restricted Area"],
                    "shot_zone_area": ["Center(C)", "Left Side(L)", "Center(C)"],
                    "shot_zone_range": ["Less Than 8 ft.", "8-16 ft.", "Less Than 8 ft."],
                }
            ).lazy(),
        }
        t = DimShotZoneTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 2  # two unique combinations
        assert "zone_id" in result.columns
        assert "shot_zone_basic" in result.columns

    def test_output_table_name(self) -> None:
        from nbadb.transform.dimensions.dim_shot_zone import DimShotZoneTransformer

        assert DimShotZoneTransformer.output_table == "dim_shot_zone"


class TestDimOfficialTransformer:
    def test_transform_basic(self) -> None:
        from nbadb.transform.dimensions.dim_official import DimOfficialTransformer

        staging = {
            "stg_officials": pl.DataFrame(
                {
                    "official_id": [101, 102, 101],
                    "first_name": ["John", "Jane", "John"],
                    "last_name": ["Doe", "Smith", "Doe"],
                    "jersey_number": ["12", "34", "12"],
                }
            ).lazy(),
        }
        t = DimOfficialTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 2  # deduplicated by official_id
        assert "official_id" in result.columns
        assert "first_name" in result.columns

    def test_keeps_last_on_duplicate(self) -> None:
        from nbadb.transform.dimensions.dim_official import DimOfficialTransformer

        staging = {
            "stg_officials": pl.DataFrame(
                {
                    "official_id": [101, 101],
                    "first_name": ["OldName", "NewName"],
                    "last_name": ["Doe", "Doe"],
                    "jersey_number": ["12", "12"],
                }
            ).lazy(),
        }
        t = DimOfficialTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 1

    def test_output_table_name(self) -> None:
        from nbadb.transform.dimensions.dim_official import DimOfficialTransformer

        assert DimOfficialTransformer.output_table == "dim_official"


class TestDimTeamTransformer:
    def test_transform_basic(self) -> None:
        from nbadb.transform.dimensions.dim_team import DimTeamTransformer

        staging = {
            "stg_team_info": pl.DataFrame(
                {
                    "team_id": [1, 2],
                    "abbreviation": ["BOS", "LAL"],
                    "full_name": ["Boston Celtics", "Los Angeles Lakers"],
                    "city": ["Boston", "Los Angeles"],
                    "state": ["Massachusetts", "California"],
                    "arena": ["TD Garden", "Crypto.com Arena"],
                    "year_founded": [1946, 1947],
                    "conference": ["East", "West"],
                    "division": ["Atlantic", "Pacific"],
                }
            ).lazy(),
        }
        t = DimTeamTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 2
        assert "team_id" in result.columns
        assert "conference" in result.columns
        assert "division" in result.columns

    def test_deduplicates_by_team_id(self) -> None:
        from nbadb.transform.dimensions.dim_team import DimTeamTransformer

        staging = {
            "stg_team_info": pl.DataFrame(
                {
                    "team_id": [1, 1],
                    "abbreviation": ["BOS", "BOS"],
                    "full_name": ["Boston Celtics", "Boston Celtics"],
                    "city": ["Boston", "Boston"],
                    "state": ["MA", "MA"],
                    "arena": ["Old Arena", "TD Garden"],
                    "year_founded": [1946, 1946],
                    "conference": ["East", "East"],
                    "division": ["Atlantic", "Atlantic"],
                }
            ).lazy(),
        }
        t = DimTeamTransformer()
        result = t.transform(staging)
        assert result.shape[0] == 1

    def test_output_table_name(self) -> None:
        from nbadb.transform.dimensions.dim_team import DimTeamTransformer

        assert DimTeamTransformer.output_table == "dim_team"
