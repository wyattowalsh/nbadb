from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_cumulative_stats_detail import (
    FactCumulativeStatsDetailTransformer,
)
from nbadb.transform.facts.fact_gl_alum_similarity import (
    FactGlAlumSimilarityTransformer,
)
from nbadb.transform.facts.fact_hustle_availability import (
    FactHustleAvailabilityTransformer,
)
from nbadb.transform.facts.fact_on_off_detail import FactOnOffDetailTransformer
from nbadb.transform.facts.fact_scoreboard_win_probability import (
    FactScoreboardWinProbabilityTransformer,
)
from nbadb.transform.facts.fact_team_available_seasons import (
    FactTeamAvailableSeasonsTransformer,
)
from nbadb.transform.facts.fact_team_lineups_detail import (
    FactTeamLineupsDetailTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _frame(row: dict) -> pl.LazyFrame:
    return pl.DataFrame({k: [v] for k, v in row.items()}).lazy()


def _register_all(depends_on: list[str], row: dict) -> dict[str, pl.LazyFrame]:
    """Build staging dict with one identical row per dependency."""
    return {dep: _frame(row) for dep in depends_on}


# ---------------------------------------------------------------------------
# On/Off Detail
# ---------------------------------------------------------------------------
class TestFactOnOffDetail:
    def test_output_table(self) -> None:
        t = FactOnOffDetailTransformer()
        assert t.output_table == "fact_on_off_detail"

    def test_depends_on_count(self) -> None:
        t = FactOnOffDetailTransformer()
        assert len(t.depends_on) == 6

    def test_depends_on_contents(self) -> None:
        t = FactOnOffDetailTransformer()
        expected = {
            "stg_on_off_details_overall",
            "stg_on_off_details_off_court",
            "stg_on_off_details_on_court",
            "stg_on_off_summary_overall",
            "stg_on_off_summary_off_court",
            "stg_on_off_summary_on_court",
        }
        assert set(t.depends_on) == expected

    def test_transform_unions_all_sources(self) -> None:
        row = {"player_id": 201566, "team_id": 1610612738, "gp": 50, "min": 30.0}
        staging = _register_all(FactOnOffDetailTransformer.depends_on, row)
        result = _run(FactOnOffDetailTransformer(), staging)
        assert result.shape[0] == 6
        assert "court_status" in result.columns

    def test_discriminator_values(self) -> None:
        row = {"player_id": 201566, "team_id": 1610612738, "gp": 50, "min": 30.0}
        staging = _register_all(FactOnOffDetailTransformer.depends_on, row)
        result = _run(FactOnOffDetailTransformer(), staging)
        expected = {
            "detail_overall", "detail_off_court", "detail_on_court",
            "summary_overall", "summary_off_court", "summary_on_court",
        }
        assert set(result["court_status"].to_list()) == expected

    def test_preserves_original_columns(self) -> None:
        row = {"player_id": 201566, "team_id": 1610612738, "gp": 50, "min": 30.0}
        staging = _register_all(FactOnOffDetailTransformer.depends_on, row)
        result = _run(FactOnOffDetailTransformer(), staging)
        assert "player_id" in result.columns
        assert "team_id" in result.columns
        assert "gp" in result.columns


# ---------------------------------------------------------------------------
# Cumulative Stats Detail
# ---------------------------------------------------------------------------
class TestFactCumulativeStatsDetail:
    def test_output_table(self) -> None:
        t = FactCumulativeStatsDetailTransformer()
        assert t.output_table == "fact_cumulative_stats_detail"

    def test_depends_on_count(self) -> None:
        t = FactCumulativeStatsDetailTransformer()
        assert len(t.depends_on) == 4

    def test_depends_on_contents(self) -> None:
        t = FactCumulativeStatsDetailTransformer()
        expected = {
            "stg_cume_player_game_by_game",
            "stg_cume_player_totals",
            "stg_cume_team_game_by_game",
            "stg_cume_team_totals",
        }
        assert set(t.depends_on) == expected

    def test_transform_unions_all_sources(self) -> None:
        row = {"player_id": 201566, "team_id": 1610612738, "season_year": "2024-25"}
        staging = _register_all(FactCumulativeStatsDetailTransformer.depends_on, row)
        result = _run(FactCumulativeStatsDetailTransformer(), staging)
        assert result.shape[0] == 4
        assert "cume_type" in result.columns

    def test_discriminator_values(self) -> None:
        row = {"player_id": 201566, "team_id": 1610612738, "season_year": "2024-25"}
        staging = _register_all(FactCumulativeStatsDetailTransformer.depends_on, row)
        result = _run(FactCumulativeStatsDetailTransformer(), staging)
        expected = {
            "player_game_by_game", "player_totals",
            "team_game_by_game", "team_totals",
        }
        assert set(result["cume_type"].to_list()) == expected


# ---------------------------------------------------------------------------
# Scoreboard Win Probability
# ---------------------------------------------------------------------------
class TestFactScoreboardWinProbability:
    def test_output_table(self) -> None:
        t = FactScoreboardWinProbabilityTransformer()
        assert t.output_table == "fact_scoreboard_win_probability"

    def test_depends_on_single_source(self) -> None:
        t = FactScoreboardWinProbabilityTransformer()
        assert t.depends_on == ["stg_scoreboard_win_probability"]

    def test_passthrough(self) -> None:
        row = {"game_id": "0022400001", "home_pct": 0.65, "visitor_pct": 0.35}
        staging = {"stg_scoreboard_win_probability": _frame(row)}
        result = _run(FactScoreboardWinProbabilityTransformer(), staging)
        assert result.shape == (1, 3)
        assert result["game_id"][0] == "0022400001"
        assert result["home_pct"][0] == pytest.approx(0.65)

    def test_passthrough_multiple_rows(self) -> None:
        df = pl.DataFrame({
            "game_id": ["0022400001", "0022400002"],
            "home_pct": [0.65, 0.45],
            "visitor_pct": [0.35, 0.55],
        })
        staging = {"stg_scoreboard_win_probability": df.lazy()}
        result = _run(FactScoreboardWinProbabilityTransformer(), staging)
        assert result.shape[0] == 2


# ---------------------------------------------------------------------------
# Team Available Seasons
# ---------------------------------------------------------------------------
class TestFactTeamAvailableSeasons:
    def test_output_table(self) -> None:
        t = FactTeamAvailableSeasonsTransformer()
        assert t.output_table == "fact_team_available_seasons"

    def test_depends_on_single_source(self) -> None:
        t = FactTeamAvailableSeasonsTransformer()
        assert t.depends_on == ["stg_team_available_seasons"]

    def test_passthrough(self) -> None:
        row = {"team_id": 1610612738, "season_year": "2024-25"}
        staging = {"stg_team_available_seasons": _frame(row)}
        result = _run(FactTeamAvailableSeasonsTransformer(), staging)
        assert result.shape[0] == 1
        assert result["team_id"][0] == 1610612738

    def test_passthrough_preserves_all_columns(self) -> None:
        row = {"team_id": 1610612738, "season_year": "2024-25", "extra_col": "val"}
        staging = {"stg_team_available_seasons": _frame(row)}
        result = _run(FactTeamAvailableSeasonsTransformer(), staging)
        assert "extra_col" in result.columns


# ---------------------------------------------------------------------------
# GL Alum Similarity
# ---------------------------------------------------------------------------
class TestFactGlAlumSimilarity:
    def test_output_table(self) -> None:
        t = FactGlAlumSimilarityTransformer()
        assert t.output_table == "fact_gl_alum_similarity"

    def test_depends_on_single_source(self) -> None:
        t = FactGlAlumSimilarityTransformer()
        assert t.depends_on == ["stg_gl_alum_box_score_similarity_score"]

    def test_passthrough(self) -> None:
        row = {"player_id": 201566, "similarity_score": 0.85, "season_year": "2024-25"}
        staging = {"stg_gl_alum_box_score_similarity_score": _frame(row)}
        result = _run(FactGlAlumSimilarityTransformer(), staging)
        assert result.shape[0] == 1
        assert result["similarity_score"][0] == pytest.approx(0.85)


# ---------------------------------------------------------------------------
# Hustle Availability
# ---------------------------------------------------------------------------
class TestFactHustleAvailability:
    def test_output_table(self) -> None:
        t = FactHustleAvailabilityTransformer()
        assert t.output_table == "fact_hustle_availability"

    def test_depends_on_count(self) -> None:
        t = FactHustleAvailabilityTransformer()
        assert len(t.depends_on) == 2

    def test_depends_on_contents(self) -> None:
        t = FactHustleAvailabilityTransformer()
        assert set(t.depends_on) == {"stg_hustle_stats_available", "stg_box_score_hustle_box"}

    def test_transform_unions_both_sources(self) -> None:
        row = {"game_id": "0022400001", "status": "available"}
        staging = _register_all(FactHustleAvailabilityTransformer.depends_on, row)
        result = _run(FactHustleAvailabilityTransformer(), staging)
        assert result.shape[0] == 2
        assert "hustle_type" in result.columns

    def test_discriminator_values(self) -> None:
        row = {"game_id": "0022400001", "status": "available"}
        staging = _register_all(FactHustleAvailabilityTransformer.depends_on, row)
        result = _run(FactHustleAvailabilityTransformer(), staging)
        assert set(result["hustle_type"].to_list()) == {"availability", "box_score"}

    def test_preserves_original_columns(self) -> None:
        row = {"game_id": "0022400001", "status": "available"}
        staging = _register_all(FactHustleAvailabilityTransformer.depends_on, row)
        result = _run(FactHustleAvailabilityTransformer(), staging)
        assert "game_id" in result.columns
        assert "status" in result.columns


# ---------------------------------------------------------------------------
# Team Lineups Detail
# ---------------------------------------------------------------------------
class TestFactTeamLineupsDetail:
    def test_output_table(self) -> None:
        t = FactTeamLineupsDetailTransformer()
        assert t.output_table == "fact_team_lineups_detail"

    def test_depends_on_single_source(self) -> None:
        t = FactTeamLineupsDetailTransformer()
        assert t.depends_on == ["stg_team_lineups_overall"]

    def test_passthrough(self) -> None:
        row = {"team_id": 1610612738, "group_set": "Lineups", "gp": 50, "min": 120.5}
        staging = {"stg_team_lineups_overall": _frame(row)}
        result = _run(FactTeamLineupsDetailTransformer(), staging)
        assert result.shape[0] == 1
        assert result["team_id"][0] == 1610612738

    def test_passthrough_preserves_all_columns(self) -> None:
        row = {"team_id": 1610612738, "group_set": "Lineups", "gp": 50, "min": 120.5}
        staging = {"stg_team_lineups_overall": _frame(row)}
        result = _run(FactTeamLineupsDetailTransformer(), staging)
        assert set(row.keys()).issubset(set(result.columns))


# ---------------------------------------------------------------------------
# Cross-cutting: all Wave 2 transforms share SqlTransformer mechanics
# ---------------------------------------------------------------------------
ALL_WAVE2 = [
    FactOnOffDetailTransformer,
    FactCumulativeStatsDetailTransformer,
    FactScoreboardWinProbabilityTransformer,
    FactTeamAvailableSeasonsTransformer,
    FactGlAlumSimilarityTransformer,
    FactHustleAvailabilityTransformer,
    FactTeamLineupsDetailTransformer,
]


@pytest.mark.parametrize(
    "cls",
    ALL_WAVE2,
    ids=[c.__name__ for c in ALL_WAVE2],
)
def test_sql_is_non_empty(cls) -> None:
    assert cls._SQL.strip(), f"{cls.__name__}._SQL should be non-empty"


@pytest.mark.parametrize(
    "cls",
    ALL_WAVE2,
    ids=[c.__name__ for c in ALL_WAVE2],
)
def test_no_connection_before_injection(cls) -> None:
    t = cls()
    with pytest.raises(RuntimeError, match="No DuckDB connection"):
        t.conn  # noqa: B018


@pytest.mark.parametrize(
    "cls",
    ALL_WAVE2,
    ids=[c.__name__ for c in ALL_WAVE2],
)
def test_output_table_starts_with_fact(cls) -> None:
    t = cls()
    assert t.output_table.startswith("fact_")
