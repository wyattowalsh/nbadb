from __future__ import annotations

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.player_support_matrix import (
    StagingLeaguePlayerOnDetailsSchema,
)

_PROVIDER_COLUMNS = (
    "group_set",
    "team_id",
    "team_abbreviation",
    "team_name",
    "vs_player_id",
    "vs_player_name",
    "court_status",
    "gp",
    "w",
    "l",
    "w_pct",
    "min",
    "fgm",
    "fga",
    "fg_pct",
    "fg3m",
    "fg3a",
    "fg3_pct",
    "ftm",
    "fta",
    "ft_pct",
    "oreb",
    "dreb",
    "reb",
    "ast",
    "tov",
    "stl",
    "blk",
    "blka",
    "pf",
    "pfd",
    "pts",
    "plus_minus",
    "gp_rank",
    "w_rank",
    "l_rank",
    "w_pct_rank",
    "min_rank",
    "fgm_rank",
    "fga_rank",
    "fg_pct_rank",
    "fg3m_rank",
    "fg3a_rank",
    "fg3_pct_rank",
    "ftm_rank",
    "fta_rank",
    "ft_pct_rank",
    "oreb_rank",
    "dreb_rank",
    "reb_rank",
    "ast_rank",
    "tov_rank",
    "stl_rank",
    "blk_rank",
    "blka_rank",
    "pf_rank",
    "pfd_rank",
    "pts_rank",
    "plus_minus_rank",
)


@derived_output_schema(
    source_overrides={
        **{
            column: (f"LeaguePlayerOnDetails.PlayersOnCourtLeaguePlayerDetails.{column.upper()}")
            for column in _PROVIDER_COLUMNS
        },
        "season_year": "request.LeaguePlayerOnDetails.Season",
        "season_type": "request.LeaguePlayerOnDetails.SeasonType",
    }
)
class FactLeaguePlayerOnDetailsSchema(StagingLeaguePlayerOnDetailsSchema):
    """Team on/off results for one compared player and request season."""

    __consumer_metadata__ = {
        "grain": "team-vs-player-court-status-group-season-season_type",
        "agent_intents": [
            "player_on_off",
            "team_on_off",
            "lineup_context",
            "player_impact",
        ],
        "join_hints": {
            "dim_team": "team_id",
            "dim_player": "vs_player_id + is_current = TRUE",
        },
    }


__all__ = ["FactLeaguePlayerOnDetailsSchema"]
