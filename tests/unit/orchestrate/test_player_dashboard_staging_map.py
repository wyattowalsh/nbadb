from __future__ import annotations

import pytest

from nbadb.orchestrate.staging_map import get_by_staging_key


@pytest.mark.parametrize(
    ("staging_key", "result_set_index"),
    [
        ("stg_player_dash_game_splits", 4),
        ("stg_player_dash_general_splits", 3),
        ("stg_player_dash_last_n_games", 5),
        ("stg_player_dash_shooting_splits", 2),
        ("stg_player_dash_team_perf", 0),
        ("stg_player_dash_yoy", 1),
        ("stg_player_dashboard_clutch", 10),
        ("stg_player_dashboard_game_splits", 4),
        ("stg_player_dashboard_general_splits", 3),
        ("stg_player_dashboard_last_n_games", 5),
        ("stg_player_dashboard_shooting_splits", 2),
        ("stg_player_dashboard_team_performance", 0),
        ("stg_player_dashboard_year_over_year", 1),
    ],
)
def test_player_dashboard_overall_entries_use_overall_result_set(
    staging_key: str,
    result_set_index: int,
) -> None:
    entry = get_by_staging_key(staging_key)
    assert entry is not None
    assert entry.use_multi is True
    assert entry.result_set_index == result_set_index
