from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactPlayerGameHustleSchema(BaseSchema):
    game_id: str = pa.Field(
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.GAME_ID"
            ),
            "description": (
                "Unique game identifier"
            ),
            "fk_ref": "dim_game.game_id",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.PLAYER_ID"
            ),
            "description": (
                "Player identifier"
            ),
            "fk_ref": (
                "dim_player.player_id"
            ),
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "dim_team.team_id",
        },
    )
    contested_shots: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".CONTESTED_SHOTS"
            ),
            "description": (
                "Total contested shots"
            ),
        },
    )
    contested_shots_2pt: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".CONTESTED_SHOTS_2PT"
            ),
            "description": (
                "Contested two-point shots"
            ),
        },
    )
    contested_shots_3pt: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".CONTESTED_SHOTS_3PT"
            ),
            "description": (
                "Contested three-point shots"
            ),
        },
    )
    deflections: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.DEFLECTIONS"
            ),
            "description": "Deflections",
        },
    )
    charges_drawn: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".CHARGES_DRAWN"
            ),
            "description": "Charges drawn",
        },
    )
    screen_assists: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".SCREEN_ASSISTS"
            ),
            "description": "Screen assists",
        },
    )
    screen_ast_pts: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats"
                ".SCREEN_AST_PTS"
            ),
            "description": (
                "Points from screen assists"
            ),
        },
    )
    loose_balls_recovered: int | None = (
        pa.Field(
            nullable=True, ge=0,
            metadata={
                "source": (
                    "BoxScoreHustleV2"
                    ".PlayerStats"
                    ".LOOSE_BALLS_RECOVERED"
                ),
                "description": (
                    "Loose balls recovered"
                ),
            },
        )
    )
    box_outs: int | None = pa.Field(
        nullable=True, ge=0,
        metadata={
            "source": (
                "BoxScoreHustleV2"
                ".PlayerStats.BOX_OUTS"
            ),
            "description": "Box outs",
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
