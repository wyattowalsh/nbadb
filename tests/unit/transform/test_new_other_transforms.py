from __future__ import annotations

import duckdb
import polars as pl

from nbadb.transform.derived.agg_player_bio import AggPlayerBioTransformer
from nbadb.transform.dimensions.dim_team_extended import DimTeamExtendedTransformer
from nbadb.transform.facts.fact_player_game_log import FactPlayerGameLogTransformer
from nbadb.transform.facts.fact_team_game_log import FactTeamGameLogTransformer


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    for key, val in staging.items():
        conn.register(key, val.collect())
    transformer._conn = conn
    result = transformer.transform(staging)
    conn.close()
    return result


# ---------------------------------------------------------------------------
# 1. dim_team_extended — JOINs on team_id
# ---------------------------------------------------------------------------
class TestDimTeamExtended:
    def test_class_attrs(self) -> None:
        assert DimTeamExtendedTransformer.output_table == "dim_team_extended"
        assert set(DimTeamExtendedTransformer.depends_on) == {
            "stg_team_details",
            "stg_team_info_common",
            "stg_team_years",
        }

    def test_join_on_team_id(self) -> None:
        staging = {
            "stg_team_details": pl.DataFrame(
                {"team_id": [1], "city": ["Boston"], "nickname": ["Celtics"]}
            ).lazy(),
            "stg_team_info_common": pl.DataFrame(
                {"team_id": [1], "abbreviation": ["BOS"], "conference": ["East"]}
            ).lazy(),
            "stg_team_years": pl.DataFrame(
                {"team_id": [1], "min_year": [1946], "max_year": [2024]}
            ).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        assert result.shape[0] == 1
        assert "team_id" in result.columns
        assert "city" in result.columns
        assert "abbreviation" in result.columns
        assert "min_year" in result.columns
        # team_id should appear once (EXCLUDE removes duplicates from joined tables)
        assert result.columns.count("team_id") == 1

    def test_left_join_team_years_null(self) -> None:
        staging = {
            "stg_team_details": pl.DataFrame({"team_id": [1], "city": ["Boston"]}).lazy(),
            "stg_team_info_common": pl.DataFrame({"team_id": [1], "abbreviation": ["BOS"]}).lazy(),
            "stg_team_years": pl.DataFrame({"team_id": [999], "min_year": [2000]}).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        assert result.shape[0] == 1
        assert result["min_year"][0] is None

    def test_inner_join_filters_missing_common(self) -> None:
        """stg_team_info_common uses INNER JOIN, so missing rows are excluded."""
        staging = {
            "stg_team_details": pl.DataFrame({"team_id": [1, 2], "city": ["Boston", "LA"]}).lazy(),
            "stg_team_info_common": pl.DataFrame({"team_id": [1], "abbreviation": ["BOS"]}).lazy(),
            "stg_team_years": pl.DataFrame({"team_id": [1, 2], "min_year": [1946, 1960]}).lazy(),
        }
        result = _run(DimTeamExtendedTransformer(), staging)
        # Only team_id=1 survives the INNER JOIN with stg_team_info_common
        assert result.shape[0] == 1
        assert result["team_id"][0] == 1


# ---------------------------------------------------------------------------
# 2. agg_player_bio — SELECT * passthrough
# ---------------------------------------------------------------------------
class TestAggPlayerBio:
    def test_class_attrs(self) -> None:
        assert AggPlayerBioTransformer.output_table == "agg_player_bio"
        assert "stg_league_player_bio" in AggPlayerBioTransformer.depends_on

    def test_transform_passthrough(self) -> None:
        staging = {
            "stg_league_player_bio": pl.DataFrame(
                {
                    "player_id": [101, 102],
                    "player_name": ["Jokic", "Embiid"],
                    "age": [28, 29],
                    "height": ["6-11", "7-0"],
                }
            ).lazy(),
        }
        result = _run(AggPlayerBioTransformer(), staging)
        assert result.shape[0] == 2
        assert set(result.columns) == {"player_id", "player_name", "age", "height"}


# ---------------------------------------------------------------------------
# 3. fact_player_game_log — UNION ALL BY NAME + QUALIFY dedup
# ---------------------------------------------------------------------------
class TestFactPlayerGameLog:
    def test_class_attrs(self) -> None:
        assert FactPlayerGameLogTransformer.output_table == "fact_player_game_log"
        assert set(FactPlayerGameLogTransformer.depends_on) == {
            "stg_player_game_logs",
            "stg_player_game_log",
            "stg_player_game_logs_v2",
        }

    def test_union_and_dedup(self) -> None:
        """Duplicate player_id+game_id rows across sources should be deduplicated."""
        staging = {
            "stg_player_game_logs": pl.DataFrame({
                "player_id": [1, 2], "game_id": ["G1", "G2"],
                "season_year": ["2024-25", "2024-25"], "pts": [20, 30],
            }).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        # player_id=1, game_id=G1 appears in all 3 sources but should be deduplicated
        assert result.shape[0] == 2
        assert "player_id" in result.columns
        assert "game_id" in result.columns

    def test_unique_rows_preserved(self) -> None:
        """Rows that are unique across sources should all be preserved."""
        staging = {
            "stg_player_game_logs": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [2], "game_id": ["G2"], "season_year": ["2024-25"], "pts": [25]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [3], "game_id": ["G3"], "season_year": ["2024-25"], "pts": [30]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        assert result.shape[0] == 3

    def test_mismatched_columns_filled_null(self) -> None:
        """UNION ALL BY NAME fills missing columns with NULL."""
        staging = {
            "stg_player_game_logs": pl.DataFrame(
                {"player_id": [1], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [20]}
            ).lazy(),
            "stg_player_game_log": pl.DataFrame(
                {"player_id": [2], "game_id": ["G2"], "season_year": ["2024-25"], "reb": [10]}
            ).lazy(),
            "stg_player_game_logs_v2": pl.DataFrame(
                {"player_id": [3], "game_id": ["G3"], "season_year": ["2024-25"], "ast": [8]}
            ).lazy(),
        }
        result = _run(FactPlayerGameLogTransformer(), staging)
        assert result.shape[0] == 3
        assert "pts" in result.columns
        assert "reb" in result.columns
        assert "ast" in result.columns


# ---------------------------------------------------------------------------
# 4. fact_team_game_log — UNION ALL BY NAME + QUALIFY dedup
# ---------------------------------------------------------------------------
class TestFactTeamGameLog:
    def test_class_attrs(self) -> None:
        assert FactTeamGameLogTransformer.output_table == "fact_team_game_log"
        assert set(FactTeamGameLogTransformer.depends_on) == {
            "stg_team_game_logs_v2",
            "stg_team_game_log",
        }

    def test_union_and_dedup(self) -> None:
        """Duplicate team_id+game_id rows across sources should be deduplicated."""
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame({
                "team_id": [10, 20], "game_id": ["G1", "G2"],
                "season_year": ["2024-25", "2024-25"], "pts": [100, 110],
            }).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        # team_id=10, game_id=G1 appears in both sources but should be deduplicated
        assert result.shape[0] == 2
        assert "team_id" in result.columns
        assert "game_id" in result.columns

    def test_unique_rows_preserved(self) -> None:
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [20], "game_id": ["G2"], "season_year": ["2024-25"], "pts": [95]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        assert result.shape[0] == 2

    def test_mismatched_columns_filled_null(self) -> None:
        """UNION ALL BY NAME fills missing columns with NULL."""
        staging = {
            "stg_team_game_logs_v2": pl.DataFrame(
                {"team_id": [10], "game_id": ["G1"], "season_year": ["2024-25"], "pts": [100]}
            ).lazy(),
            "stg_team_game_log": pl.DataFrame(
                {"team_id": [20], "game_id": ["G2"], "season_year": ["2024-25"], "fg_pct": [0.48]}
            ).lazy(),
        }
        result = _run(FactTeamGameLogTransformer(), staging)
        assert result.shape[0] == 2
        assert "pts" in result.columns
        assert "fg_pct" in result.columns
