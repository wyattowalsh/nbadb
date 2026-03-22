from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.views.analytics_clutch_performance import (
    AnalyticsClutchPerformanceTransformer,
)
from nbadb.transform.views.analytics_player_matchup import (
    AnalyticsPlayerMatchupTransformer,
)
from nbadb.transform.views.analytics_shooting_efficiency import (
    AnalyticsShootingEfficiencyTransformer,
)
from nbadb.transform.views.analytics_team_game_complete import (
    AnalyticsTeamGameCompleteTransformer,
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


# ---------------------------------------------------------------------------
# Analytics Team Game Complete
# ---------------------------------------------------------------------------
class TestAnalyticsTeamGameComplete:
    def test_output_table(self) -> None:
        t = AnalyticsTeamGameCompleteTransformer()
        assert t.output_table == "analytics_team_game_complete"

    def test_depends_on_count(self) -> None:
        t = AnalyticsTeamGameCompleteTransformer()
        assert len(t.depends_on) == 7

    def test_depends_on_contents(self) -> None:
        t = AnalyticsTeamGameCompleteTransformer()
        expected = {
            "fact_team_game",
            "fact_box_score_advanced_team",
            "fact_box_score_misc_team",
            "fact_team_game_hustle",
            "fact_box_score_player_track_team",
            "dim_team",
            "dim_game",
        }
        assert set(t.depends_on) == expected

    def test_join_produces_wide_output(self) -> None:
        fact_team_game = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "pts": [110],
            "reb": [45],
            "ast": [25],
            "stl": [8],
            "blk": [5],
            "tov": [13],
            "fgm": [40],
            "fga": [88],
            "fg_pct": [0.455],
            "fg3m": [13],
            "fg3a": [36],
            "fg3_pct": [0.361],
            "ftm": [18],
            "fta": [22],
            "ft_pct": [0.818],
            "oreb": [10],
            "dreb": [35],
            "pf": [20],
            "plus_minus": [5],
        }).lazy()

        fact_adv = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "off_rating": [112.0],
            "def_rating": [108.0],
            "net_rating": [4.0],
            "ast_pct": [0.62],
            "reb_pct": [0.51],
            "oreb_pct": [0.28],
            "dreb_pct": [0.74],
            "efg_pct": [0.54],
            "ts_pct": [0.57],
            "pace": [100.5],
            "pie": [0.52],
        }).lazy()

        fact_misc = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "pts_off_tov": [18],
            "second_chance_pts": [12],
            "fbps": [15],
            "pitp": [48],
        }).lazy()

        fact_hustle = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "contested_shots": [45],
            "deflections": [12],
            "loose_balls_recovered": [6],
            "charges_drawn": [1],
            "screen_assists": [8],
        }).lazy()

        fact_track = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "dist": [250.5],
            "spd": [4.5],
            "tchs": [300],
            "passes": [280],
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": [1610612738],
            "full_name": ["Boston Celtics"],
            "abbreviation": ["BOS"],
        }).lazy()

        dim_game = pl.DataFrame({
            "game_id": ["0022400001"],
            "season_year": ["2024-25"],
            "game_date": ["2025-01-15"],
            "home_team_id": [1610612738],
            "visitor_team_id": [1610612739],
        }).lazy()

        staging = {
            "fact_team_game": fact_team_game,
            "fact_box_score_advanced_team": fact_adv,
            "fact_box_score_misc_team": fact_misc,
            "fact_team_game_hustle": fact_hustle,
            "fact_box_score_player_track_team": fact_track,
            "dim_team": dim_team,
            "dim_game": dim_game,
        }
        result = _run(AnalyticsTeamGameCompleteTransformer(), staging)

        assert result.shape[0] == 1
        # Traditional columns
        assert result["pts"][0] == 110
        assert result["ast"][0] == 25
        # Advanced columns from join
        assert result["off_rating"][0] == pytest.approx(112.0)
        assert result["net_rating"][0] == pytest.approx(4.0)
        # Misc columns from join
        assert result["pts_off_tov"][0] == 18
        assert result["pitp"][0] == 48
        # Hustle columns from join
        assert result["contested_shots"][0] == 45
        assert result["deflections"][0] == 12
        # Tracking columns from join
        assert result["dist"][0] == pytest.approx(250.5)
        assert result["passes"][0] == 280
        # Dimension enrichment
        assert result["team_name"][0] == "Boston Celtics"
        assert result["team_abbreviation"][0] == "BOS"
        assert result["season_year"][0] == "2024-25"

    def test_left_join_nulls_when_no_match(self) -> None:
        """LEFT JOINs produce NULLs for unmatched dimension/fact rows."""
        fact_team_game = pl.DataFrame({
            "team_id": [1610612738],
            "game_id": ["0022400001"],
            "pts": [110],
            "reb": [45],
            "ast": [25],
            "stl": [8],
            "blk": [5],
            "tov": [13],
            "fgm": [40],
            "fga": [88],
            "fg_pct": [0.455],
            "fg3m": [13],
            "fg3a": [36],
            "fg3_pct": [0.361],
            "ftm": [18],
            "fta": [22],
            "ft_pct": [0.818],
            "oreb": [10],
            "dreb": [35],
            "pf": [20],
            "plus_minus": [5],
        }).lazy()

        # Empty tables for everything else
        fact_adv = pl.DataFrame({
            "team_id": pl.Series([], dtype=pl.Int64),
            "game_id": pl.Series([], dtype=pl.Utf8),
            "off_rating": pl.Series([], dtype=pl.Float64),
            "def_rating": pl.Series([], dtype=pl.Float64),
            "net_rating": pl.Series([], dtype=pl.Float64),
            "ast_pct": pl.Series([], dtype=pl.Float64),
            "reb_pct": pl.Series([], dtype=pl.Float64),
            "oreb_pct": pl.Series([], dtype=pl.Float64),
            "dreb_pct": pl.Series([], dtype=pl.Float64),
            "efg_pct": pl.Series([], dtype=pl.Float64),
            "ts_pct": pl.Series([], dtype=pl.Float64),
            "pace": pl.Series([], dtype=pl.Float64),
            "pie": pl.Series([], dtype=pl.Float64),
        }).lazy()

        fact_misc = pl.DataFrame({
            "team_id": pl.Series([], dtype=pl.Int64),
            "game_id": pl.Series([], dtype=pl.Utf8),
            "pts_off_tov": pl.Series([], dtype=pl.Int64),
            "second_chance_pts": pl.Series([], dtype=pl.Int64),
            "fbps": pl.Series([], dtype=pl.Int64),
            "pitp": pl.Series([], dtype=pl.Int64),
        }).lazy()

        fact_hustle = pl.DataFrame({
            "team_id": pl.Series([], dtype=pl.Int64),
            "game_id": pl.Series([], dtype=pl.Utf8),
            "contested_shots": pl.Series([], dtype=pl.Int64),
            "deflections": pl.Series([], dtype=pl.Int64),
            "loose_balls_recovered": pl.Series([], dtype=pl.Int64),
            "charges_drawn": pl.Series([], dtype=pl.Int64),
            "screen_assists": pl.Series([], dtype=pl.Int64),
        }).lazy()

        fact_track = pl.DataFrame({
            "team_id": pl.Series([], dtype=pl.Int64),
            "game_id": pl.Series([], dtype=pl.Utf8),
            "dist": pl.Series([], dtype=pl.Float64),
            "spd": pl.Series([], dtype=pl.Float64),
            "tchs": pl.Series([], dtype=pl.Int64),
            "passes": pl.Series([], dtype=pl.Int64),
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": pl.Series([], dtype=pl.Int64),
            "full_name": pl.Series([], dtype=pl.Utf8),
            "abbreviation": pl.Series([], dtype=pl.Utf8),
        }).lazy()

        dim_game = pl.DataFrame({
            "game_id": pl.Series([], dtype=pl.Utf8),
            "season_year": pl.Series([], dtype=pl.Utf8),
            "game_date": pl.Series([], dtype=pl.Utf8),
            "home_team_id": pl.Series([], dtype=pl.Int64),
            "visitor_team_id": pl.Series([], dtype=pl.Int64),
        }).lazy()

        staging = {
            "fact_team_game": fact_team_game,
            "fact_box_score_advanced_team": fact_adv,
            "fact_box_score_misc_team": fact_misc,
            "fact_team_game_hustle": fact_hustle,
            "fact_box_score_player_track_team": fact_track,
            "dim_team": dim_team,
            "dim_game": dim_game,
        }
        result = _run(AnalyticsTeamGameCompleteTransformer(), staging)

        assert result.shape[0] == 1
        assert result["pts"][0] == 110
        # Unmatched joins produce NULLs
        assert result["off_rating"][0] is None
        assert result["team_name"][0] is None


# ---------------------------------------------------------------------------
# Analytics Clutch Performance
# ---------------------------------------------------------------------------
class TestAnalyticsClutchPerformance:
    def test_output_table(self) -> None:
        t = AnalyticsClutchPerformanceTransformer()
        assert t.output_table == "analytics_clutch_performance"

    def test_depends_on_count(self) -> None:
        t = AnalyticsClutchPerformanceTransformer()
        assert len(t.depends_on) == 3

    def test_depends_on_contents(self) -> None:
        t = AnalyticsClutchPerformanceTransformer()
        assert set(t.depends_on) == {
            "fact_player_clutch_detail",
            "dim_player",
            "dim_team",
        }

    def test_join_enriches_with_player_and_team(self) -> None:
        fact = pl.DataFrame({
            "player_id": [201566],
            "team_id": [1610612738],
            "season_year": ["2024-25"],
            "clutch_window": ["last5min_5pt"],
            "gp": [50],
            "w": [30],
            "l": [20],
            "min": [5.0],
            "fgm": [3.0],
            "fga": [7.0],
            "fg_pct": [0.429],
            "fg3m": [1.0],
            "fg3a": [3.0],
            "fg3_pct": [0.333],
            "ftm": [2.0],
            "fta": [2.5],
            "ft_pct": [0.800],
            "oreb": [0.5],
            "dreb": [2.0],
            "reb": [2.5],
            "ast": [2.0],
            "tov": [1.0],
            "stl": [0.5],
            "blk": [0.2],
            "pf": [1.0],
            "pts": [9.0],
            "plus_minus": [3.0],
            "net_rating": [8.0],
            "off_rating": [112.0],
            "def_rating": [104.0],
        }).lazy()

        dim_player = pl.DataFrame({
            "player_id": [201566],
            "full_name": ["Russell Westbrook"],
            "is_current": [True],
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": [1610612738],
            "abbreviation": ["BOS"],
        }).lazy()

        staging = {
            "fact_player_clutch_detail": fact,
            "dim_player": dim_player,
            "dim_team": dim_team,
        }
        result = _run(AnalyticsClutchPerformanceTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] == "Russell Westbrook"
        assert result["team_abbreviation"][0] == "BOS"
        assert result["clutch_window"][0] == "last5min_5pt"
        assert result["pts"][0] == pytest.approx(9.0)
        assert result["net_rating"][0] == pytest.approx(8.0)

    def test_null_player_name_when_not_current(self) -> None:
        """dim_player join requires is_current = TRUE; non-current yields NULL."""
        fact = pl.DataFrame({
            "player_id": [201566],
            "team_id": [1610612738],
            "season_year": ["2024-25"],
            "clutch_window": ["overall"],
            "gp": [50],
            "w": [30],
            "l": [20],
            "min": [5.0],
            "fgm": [3.0],
            "fga": [7.0],
            "fg_pct": [0.429],
            "fg3m": [1.0],
            "fg3a": [3.0],
            "fg3_pct": [0.333],
            "ftm": [2.0],
            "fta": [2.5],
            "ft_pct": [0.800],
            "oreb": [0.5],
            "dreb": [2.0],
            "reb": [2.5],
            "ast": [2.0],
            "tov": [1.0],
            "stl": [0.5],
            "blk": [0.2],
            "pf": [1.0],
            "pts": [9.0],
            "plus_minus": [3.0],
            "net_rating": [8.0],
            "off_rating": [112.0],
            "def_rating": [104.0],
        }).lazy()

        dim_player = pl.DataFrame({
            "player_id": [201566],
            "full_name": ["Russell Westbrook"],
            "is_current": [False],
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": [1610612738],
            "abbreviation": ["BOS"],
        }).lazy()

        staging = {
            "fact_player_clutch_detail": fact,
            "dim_player": dim_player,
            "dim_team": dim_team,
        }
        result = _run(AnalyticsClutchPerformanceTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] is None


# ---------------------------------------------------------------------------
# Analytics Shooting Efficiency
# ---------------------------------------------------------------------------
class TestAnalyticsShootingEfficiency:
    def test_output_table(self) -> None:
        t = AnalyticsShootingEfficiencyTransformer()
        assert t.output_table == "analytics_shooting_efficiency"

    def test_depends_on_count(self) -> None:
        t = AnalyticsShootingEfficiencyTransformer()
        assert len(t.depends_on) == 4

    def test_depends_on_contents(self) -> None:
        t = AnalyticsShootingEfficiencyTransformer()
        assert set(t.depends_on) == {
            "fact_shot_chart",
            "fact_shot_chart_league_averages",
            "dim_player",
            "dim_game",
        }

    def test_join_enriches_shots_with_league_averages(self) -> None:
        fact_shot = pl.DataFrame({
            "player_id": [201566],
            "game_id": ["0022400001"],
            "team_id": [1610612738],
            "shot_zone_basic": ["Mid-Range"],
            "shot_zone_area": ["Left Side(L)"],
            "shot_zone_range": ["8-16 ft."],
            "shot_distance": [12],
            "shot_type": ["2PT Field Goal"],
            "shot_made_flag": [1],
            "loc_x": [-80],
            "loc_y": [90],
        }).lazy()

        fact_league_avg = pl.DataFrame({
            "shot_zone_basic": ["Mid-Range"],
            "shot_zone_area": ["Left Side(L)"],
            "shot_zone_range": ["8-16 ft."],
            "fgm": [4.2],
            "fga": [10.5],
            "fg_pct": [0.400],
        }).lazy()

        dim_player = pl.DataFrame({
            "player_id": [201566],
            "full_name": ["Russell Westbrook"],
            "is_current": [True],
        }).lazy()

        dim_game = pl.DataFrame({
            "game_id": ["0022400001"],
            "season_year": ["2024-25"],
            "game_date": ["2025-01-15"],
        }).lazy()

        staging = {
            "fact_shot_chart": fact_shot,
            "fact_shot_chart_league_averages": fact_league_avg,
            "dim_player": dim_player,
            "dim_game": dim_game,
        }
        result = _run(AnalyticsShootingEfficiencyTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] == "Russell Westbrook"
        assert result["shot_zone_basic"][0] == "Mid-Range"
        assert result["league_avg_fg_pct"][0] == pytest.approx(0.400)
        assert result["season_year"][0] == "2024-25"
        assert result["shot_made_flag"][0] == 1


# ---------------------------------------------------------------------------
# Analytics Player Matchup
# ---------------------------------------------------------------------------
class TestAnalyticsPlayerMatchup:
    def test_output_table(self) -> None:
        t = AnalyticsPlayerMatchupTransformer()
        assert t.output_table == "analytics_player_matchup"

    def test_depends_on_count(self) -> None:
        t = AnalyticsPlayerMatchupTransformer()
        assert len(t.depends_on) == 3

    def test_depends_on_contents(self) -> None:
        t = AnalyticsPlayerMatchupTransformer()
        assert set(t.depends_on) == {
            "fact_player_matchups",
            "dim_player",
            "dim_team",
        }

    def test_join_enriches_matchup_with_names(self) -> None:
        fact = pl.DataFrame({
            "player_id": [201566],
            "team_id": [1610612738],
            "vs_player_id": [203507],
            "season_year": ["2024-25"],
            "matchup_min": [12.5],
            "player_pts": [8.0],
            "team_pts": [22.0],
            "ast": [2],
            "tov": [1],
            "stl": [1],
            "blk": [0],
            "fgm": [3],
            "fga": [7],
            "fg_pct": [0.429],
            "fg3m": [1],
            "fg3a": [3],
            "fg3_pct": [0.333],
        }).lazy()

        dim_player = pl.DataFrame({
            "player_id": [201566, 203507],
            "full_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
            "is_current": [True, True],
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": [1610612738],
            "abbreviation": ["BOS"],
        }).lazy()

        staging = {
            "fact_player_matchups": fact,
            "dim_player": dim_player,
            "dim_team": dim_team,
        }
        result = _run(AnalyticsPlayerMatchupTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] == "Russell Westbrook"
        assert result["vs_player_name"][0] == "Giannis Antetokounmpo"
        assert result["team_abbreviation"][0] == "BOS"
        assert result["matchup_min"][0] == pytest.approx(12.5)
        assert result["player_pts"][0] == pytest.approx(8.0)

    def test_null_vs_player_when_not_current(self) -> None:
        """vs_player_name is NULL when vs_player has is_current = FALSE."""
        fact = pl.DataFrame({
            "player_id": [201566],
            "team_id": [1610612738],
            "vs_player_id": [203507],
            "season_year": ["2024-25"],
            "matchup_min": [12.5],
            "player_pts": [8.0],
            "team_pts": [22.0],
            "ast": [2],
            "tov": [1],
            "stl": [1],
            "blk": [0],
            "fgm": [3],
            "fga": [7],
            "fg_pct": [0.429],
            "fg3m": [1],
            "fg3a": [3],
            "fg3_pct": [0.333],
        }).lazy()

        dim_player = pl.DataFrame({
            "player_id": [201566, 203507],
            "full_name": ["Russell Westbrook", "Giannis Antetokounmpo"],
            "is_current": [True, False],
        }).lazy()

        dim_team = pl.DataFrame({
            "team_id": [1610612738],
            "abbreviation": ["BOS"],
        }).lazy()

        staging = {
            "fact_player_matchups": fact,
            "dim_player": dim_player,
            "dim_team": dim_team,
        }
        result = _run(AnalyticsPlayerMatchupTransformer(), staging)

        assert result.shape[0] == 1
        assert result["player_name"][0] == "Russell Westbrook"
        assert result["vs_player_name"][0] is None


# ---------------------------------------------------------------------------
# Cross-cutting: all analytics views share SqlTransformer mechanics
# ---------------------------------------------------------------------------
ALL_ANALYTICS = [
    AnalyticsTeamGameCompleteTransformer,
    AnalyticsShootingEfficiencyTransformer,
    AnalyticsClutchPerformanceTransformer,
    AnalyticsPlayerMatchupTransformer,
]


@pytest.mark.parametrize(
    "cls",
    ALL_ANALYTICS,
    ids=[c.__name__ for c in ALL_ANALYTICS],
)
def test_sql_is_non_empty(cls) -> None:
    assert cls._SQL.strip(), f"{cls.__name__}._SQL should be non-empty"


@pytest.mark.parametrize(
    "cls",
    ALL_ANALYTICS,
    ids=[c.__name__ for c in ALL_ANALYTICS],
)
def test_output_table_starts_with_analytics(cls) -> None:
    t = cls()
    assert t.output_table.startswith("analytics_")


@pytest.mark.parametrize(
    "cls",
    ALL_ANALYTICS,
    ids=[c.__name__ for c in ALL_ANALYTICS],
)
def test_no_connection_before_injection(cls) -> None:
    t = cls()
    with pytest.raises(RuntimeError, match="No DuckDB connection"):
        t.conn  # noqa: B018
