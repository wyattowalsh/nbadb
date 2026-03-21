from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.derived.agg_clutch_stats import AggClutchStatsTransformer
from nbadb.transform.facts.fact_player_dashboard_clutch_overall import (
    FactPlayerDashboardClutchOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_game_splits_overall import (
    FactPlayerDashboardGameSplitsOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_general_splits_overall import (
    FactPlayerDashboardGeneralSplitsOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_last_n_overall import (
    FactPlayerDashboardLastNOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_shooting_overall import (
    FactPlayerDashboardShootingOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_team_perf_overall import (
    FactPlayerDashboardTeamPerfOverallTransformer,
)
from nbadb.transform.facts.fact_player_dashboard_yoy_overall import (
    FactPlayerDashboardYoyOverallTransformer,
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


@pytest.mark.parametrize(
    ("transformer_cls", "output_table", "staging_key"),
    [
        (
            FactPlayerDashboardClutchOverallTransformer,
            "fact_player_dashboard_clutch_overall",
            "stg_player_dashboard_clutch",
        ),
        (
            FactPlayerDashboardGameSplitsOverallTransformer,
            "fact_player_dashboard_game_splits_overall",
            "stg_player_dashboard_game_splits",
        ),
        (
            FactPlayerDashboardGeneralSplitsOverallTransformer,
            "fact_player_dashboard_general_splits_overall",
            "stg_player_dashboard_general_splits",
        ),
        (
            FactPlayerDashboardLastNOverallTransformer,
            "fact_player_dashboard_last_n_overall",
            "stg_player_dashboard_last_n_games",
        ),
        (
            FactPlayerDashboardShootingOverallTransformer,
            "fact_player_dashboard_shooting_overall",
            "stg_player_dashboard_shooting_splits",
        ),
        (
            FactPlayerDashboardTeamPerfOverallTransformer,
            "fact_player_dashboard_team_perf_overall",
            "stg_player_dashboard_team_performance",
        ),
        (
            FactPlayerDashboardYoyOverallTransformer,
            "fact_player_dashboard_yoy_overall",
            "stg_player_dashboard_year_over_year",
        ),
    ],
)
def test_player_dashboard_fact_transformers_passthrough(
    transformer_cls: type,
    output_table: str,
    staging_key: str,
) -> None:
    transformer = transformer_cls()
    assert transformer.output_table == output_table
    assert transformer.depends_on == [staging_key]

    staging = {
        staging_key: pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "season_type": ["Regular Season"],
                "group_set": ["Overall"],
                "group_value": ["Overall"],
                "metric": [1.0],
            }
        ).lazy()
    }

    result = _run(transformer, staging)
    assert result.to_dict(as_series=False) == staging[staging_key].collect().to_dict(
        as_series=False
    )


def test_agg_clutch_stats_joins_player_dashboard_overall_rows() -> None:
    staging = {
        "stg_player_dashboard_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "gp": [12],
                "min": [24.5],
                "pts": [36.0],
                "fg_pct": [0.55],
                "ft_pct": [0.88],
            }
        ).lazy(),
        "stg_league_player_clutch": pl.DataFrame(
            {
                "player_id": [2544],
                "season_year": ["2024-25"],
                "pts": [22.0],
                "fg_pct": [0.48],
            }
        ).lazy(),
    }

    result = _run(AggClutchStatsTransformer(), staging)

    assert result.shape == (1, 9)
    assert result["player_id"].to_list() == [2544]
    assert result["clutch_pts"].to_list() == [36.0]
    assert result["league_clutch_fg_pct"].to_list() == [0.48]
