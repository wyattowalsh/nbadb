"""Live snapshot transformers.

These are intentionally isolated so the historical pipeline can exclude them
while support-matrix and audit discovery can still treat them as first-class
warehouse ownership for live surfaces.
"""

from __future__ import annotations

from typing import Any, cast

from nbadb.transform.base import make_passthrough, make_union


def _mark_live_snapshot(cls: type) -> type:
    cast("Any", cls).is_live_snapshot = True
    return cls


FactLiveScoreBoardTransformer = _mark_live_snapshot(
    make_passthrough("fact_live_score_board", "stg_live_score_board")
)
FactLiveOddsTransformer = _mark_live_snapshot(make_passthrough("fact_live_odds", "stg_live_odds"))
FactLivePlayByPlayTransformer = _mark_live_snapshot(
    make_passthrough("fact_live_play_by_play", "stg_live_play_by_play")
)
FactLiveBoxScoreGameTransformer = _mark_live_snapshot(
    make_passthrough("fact_live_box_score_game", "stg_live_box_score_game_details")
)
FactLiveBoxScoreArenaTransformer = _mark_live_snapshot(
    make_passthrough("fact_live_box_score_arena", "stg_live_box_score_arena")
)
BridgeLiveBoxScoreOfficialTransformer = _mark_live_snapshot(
    make_passthrough("bridge_live_box_score_official", "stg_live_box_score_officials")
)
FactLiveBoxScoreTeamTransformer = _mark_live_snapshot(
    make_union(
        "fact_live_box_score_team",
        "team_side",
        {
            "home": "stg_live_box_score_team_stats_home",
            "away": "stg_live_box_score_team_stats_away",
        },
    )
)
FactLiveBoxScorePlayerTransformer = _mark_live_snapshot(
    make_union(
        "fact_live_box_score_player",
        "team_side",
        {
            "home": "stg_live_box_score_player_stats_home",
            "away": "stg_live_box_score_player_stats_away",
        },
    )
)
