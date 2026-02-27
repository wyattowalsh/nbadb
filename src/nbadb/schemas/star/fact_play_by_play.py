from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayByPlaySchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.GAME_ID"
            ),
            "description": (
                "Unique game identifier"
            ),
            "fk_ref": "dim_game.game_id",
        },
    )
    event_num: int = pa.Field(
        ge=0,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.EVENTNUM"
            ),
            "description": (
                "Event sequence number"
            ),
        },
    )
    event_msg_type: int = pa.Field(
        ge=0,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.EVENTMSGTYPE"
            ),
            "description": (
                "Event message type code"
            ),
        },
    )
    event_msg_action_type: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "PlayByPlayV3"
                    ".PlayByPlay"
                    ".EVENTMSGACTIONTYPE"
                ),
                "description": (
                    "Event action type code"
                ),
            },
        )
    )
    period: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.PERIOD"
            ),
            "description": (
                "Game period (1-4 qtrs, 5+ OT)"
            ),
        },
    )
    wc_time_string: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.WCTIMESTRING"
            ),
            "description": "Wall clock time",
        },
    )
    pc_time_string: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.PCTIMESTRING"
            ),
            "description": (
                "Period clock time string"
            ),
        },
    )
    home_description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".HOMEDESCRIPTION"
            ),
            "description": (
                "Home team event description"
            ),
        },
    )
    neutral_description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".NEUTRALDESCRIPTION"
            ),
            "description": (
                "Neutral event description"
            ),
        },
    )
    visitor_description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".VISITORDESCRIPTION"
            ),
            "description": (
                "Visitor team event description"
            ),
        },
    )
    score: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.SCORE"
            ),
            "description": (
                "Score at event (e.g. 102 - 98)"
            ),
        },
    )
    score_margin: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.SCOREMARGIN"
            ),
            "description": "Score margin at event",
        },
    )
    player1_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.PLAYER1_ID"
            ),
            "description": (
                "Primary player identifier"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    player1_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".PLAYER1_TEAM_ID"
            ),
            "description": (
                "Primary player team ID"
            ),
            "fk_ref": "dim_team.team_id",
        },
    )
    player2_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.PLAYER2_ID"
            ),
            "description": (
                "Secondary player identifier"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    player2_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".PLAYER2_TEAM_ID"
            ),
            "description": (
                "Secondary player team ID"
            ),
            "fk_ref": "dim_team.team_id",
        },
    )
    player3_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay.PLAYER3_ID"
            ),
            "description": (
                "Tertiary player identifier"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    player3_team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayByPlayV3"
                ".PlayByPlay"
                ".PLAYER3_TEAM_ID"
            ),
            "description": (
                "Tertiary player team ID"
            ),
            "fk_ref": "dim_team.team_id",
        },
    )
    event_type_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "derived.event_type_name"
            ),
            "description": (
                "Derived event type label"
            ),
        },
    )
    season_year: str = pa.Field(
        metadata={
            "source": "derived.season_year",
            "description": (
                "Season year (e.g. 2024-25)"
            ),
        },
    )
