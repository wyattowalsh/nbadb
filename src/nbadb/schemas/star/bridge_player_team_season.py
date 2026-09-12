from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class BridgePlayerTeamSeasonSchema(BaseSchema):
    __consumer_metadata__ = {
        "grain": "player-team-competition-season-season_type",
        "agent_intents": ["roster", "player_team_season"],
        "join_hints": {
            "dim_player": "player_id (identity only)",
            "dim_team": "team_id",
        },
    }

    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("PlayerCareerStats.SeasonTotals*.PLAYER_ID"),
            "description": ("Player identifier"),
            "fk_ref": ("dim_player.player_id"),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("PlayerCareerStats.SeasonTotals*.TEAM_ID"),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "PlayerCareerStats.SeasonTotals*.SEASON_ID",
            "description": ("Season year (e.g. 2024-25)"),
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayerCareerStats.SeasonTotals*.LEAGUE_ID",
            "description": "League or competition identifier",
        },
    )
    season_type: str = pa.Field(
        isin=["Regular Season", "Playoffs", "All Star"],
        metadata={
            "source": "derived.player_career_result_set",
            "description": "Season type represented by the source result set",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayerCareerStats.SeasonTotals*.TEAM_ABBREVIATION",
            "description": "Provider team abbreviation for the season membership",
        },
    )
    jersey_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.unavailable",
            "description": (
                "Unavailable from PlayerCareerStats; retained nullable for compatibility"
            ),
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "derived.unavailable",
            "description": (
                "Unavailable from PlayerCareerStats; retained nullable for compatibility"
            ),
        },
    )
