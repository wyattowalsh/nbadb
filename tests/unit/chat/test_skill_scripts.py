"""Regression coverage for the tracked NBA analytics skill scripts."""

from __future__ import annotations

import importlib.util
from datetime import date
from functools import cache
from pathlib import Path

import matplotlib
import pandas as pd
import pytest

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

_SCRIPTS_DIR = (
    Path(__file__).resolve().parents[3] / "chat" / "skills" / "nba-data-analytics" / "scripts"
)


@cache
def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, _SCRIPTS_DIR / f"{name}.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(autouse=True)
def _close_figures() -> None:
    yield
    plt.close("all")


def test_skill_script_inventory_matches_current_surface() -> None:
    assert sorted(path.stem for path in _SCRIPTS_DIR.glob("*.py")) == [
        "compare",
        "court",
        "lineups",
        "metric_calculator",
        "nba_stats",
        "season_utils",
        "similarity",
        "team_colors",
        "trends",
    ]


def test_compare_script_outputs_league_average_and_percentiles() -> None:
    mod = _load_module("compare")
    df = pd.DataFrame(
        {
            "full_name": ["Alice", "Bob", "Carol"],
            "player_id": [1, 2, 3],
            "pts": [25.0, 18.0, 30.0],
            "ast": [7.0, 3.0, 9.0],
            "tov": [3.0, 2.0, 4.0],
        }
    )

    comparison = mod.compare_players(df, metrics=["pts", "ast"])
    percentiles = mod.percentile_rank(df, metrics=["tov"], ascending_cols=["tov"])

    assert "League Avg" in comparison.index
    assert (
        percentiles.set_index("full_name").loc["Bob", "tov_pctile"]
        > percentiles.set_index("full_name").loc["Carol", "tov_pctile"]
    )


def test_court_script_draws_expected_visuals() -> None:
    mod = _load_module("court")
    shot_df = pd.DataFrame(
        {
            "loc_x": [-10, 0, 20],
            "loc_y": [0, 25, 150],
            "shot_made_flag": [1, 0, 1],
        }
    )

    ax = mod.draw_court()
    fig = mod.shot_chart(shot_df, title="Shots")

    assert isinstance(ax, plt.Axes)
    assert fig.axes[0].get_title() == "Shots"


def test_lineups_script_computes_deltas_and_pairings() -> None:
    mod = _load_module("lineups")
    on_off_df = pd.DataFrame(
        {
            "entity_id": [1, 1],
            "on_off": ["On", "Off"],
            "net_rating": [7.0, 2.0],
        }
    )
    lineup_df = pd.DataFrame(
        {
            "player1": ["A", "A"],
            "player2": ["B", "C"],
            "avg_net_rating": [8.0, 4.0],
            "min": [20.0, 10.0],
        }
    )

    impact = mod.on_off_impact(on_off_df)
    combos = mod.two_man_combos(lineup_df)

    assert impact.loc[0, "net_rating_delta"] == pytest.approx(5.0)
    assert {"player_1", "player_2", "weighted_net_rating"} <= set(combos.columns)


def test_metric_calculator_handles_core_formulas() -> None:
    mod = _load_module("metric_calculator")

    assert mod.true_shooting_pct(30, 20, 10) == pytest.approx(0.6148, abs=0.001)
    assert mod.assist_to_turnover(10, 0) is None
    assert mod.turnover_pct(4, 16, 8) == pytest.approx(17.0068, abs=0.001)


def test_nba_stats_reports_breakouts_and_streaks() -> None:
    mod = _load_module("nba_stats")

    breakouts = mod.breakout_threshold([20.0] * 20 + [45.0])
    streaks = mod.streak_significance([1, 1, 1, 0, 0, 1, 1, 1, 1, 0])

    assert breakouts["breakout_count"] == 1
    assert streaks["longest_streak"] == 4


def test_season_utils_round_trip_identifiers() -> None:
    mod = _load_module("season_utils")

    season = mod.current_season(date(2025, 11, 1))
    season_id = mod.season_year_to_id("2024-25")

    assert season == "2025-26"
    assert mod.season_id_to_year(season_id) == "2024-25"


def test_similarity_finds_clone_as_top_match() -> None:
    mod = _load_module("similarity")
    df = pd.DataFrame(
        {
            "full_name": ["Target", "Clone", "Other"],
            "pts": [25.0, 25.0, 10.0],
            "reb": [8.0, 8.0, 3.0],
            "ast": [7.0, 7.0, 2.0],
        }
    )

    result = mod.find_similar(df, "Target", metrics=["pts", "reb", "ast"], n=2)

    assert result.iloc[0]["full_name"] == "Clone"
    assert result.iloc[0]["similarity"] == pytest.approx(1.0, abs=1e-6)


def test_team_colors_covers_known_and_unknown_teams() -> None:
    mod = _load_module("team_colors")

    assert mod.get_team_color("LAL") == "#552583"
    assert mod.get_team_color("XXX") == "#888888"
    assert mod.get_color_map(["LAL", "BOS"]) == {"LAL": "#552583", "BOS": "#007A33"}


def test_trends_rolls_stats_and_projects_season_totals() -> None:
    mod = _load_module("trends")
    game_log = pd.DataFrame(
        {
            "game_date": pd.date_range("2025-10-01", periods=4, freq="D"),
            "pts": [20.0, 24.0, 28.0, 32.0],
        }
    )

    rolled = mod.rolling_stats(game_log, ["pts"], window=2)
    projection = mod.season_projection({"pts": 820.0}, games_played=41, total_games=82)

    assert rolled.loc[1, "pts_rolling_2"] == pytest.approx(22.0)
    assert projection["projections"]["pts"]["projected_total"] == pytest.approx(1640.0, abs=0.1)
