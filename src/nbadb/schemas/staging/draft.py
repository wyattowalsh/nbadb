from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingDraftHistorySchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".PERSON_ID"
            ),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    season: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.SEASON"
            ),
            "description": "Draft season year",
        },
    )
    round_number: int | None = pa.Field(
        nullable=True,
        isin=[1, 2],
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".ROUND_NUMBER"
            ),
            "description": "Draft round number",
        },
    )
    round_pick: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".ROUND_PICK"
            ),
            "description": (
                "Pick number within the round"
            ),
        },
    )
    overall_pick: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".OVERALL_PICK"
            ),
            "description": (
                "Overall draft pick number"
            ),
        },
    )
    draft_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".DRAFT_TYPE"
            ),
            "description": "Type of draft",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    organization: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".ORGANIZATION"
            ),
            "description": (
                "Pre-draft organization"
            ),
        },
    )
    organization_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".ORGANIZATION_TYPE"
            ),
            "description": (
                "Type of pre-draft organization"
            ),
        },
    )
    player_profile_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".PLAYER_PROFILE_FLAG"
            ),
            "description": (
                "Player profile availability flag"
            ),
        },
    )


class StagingDraftCombineStatsSchema(BaseSchema):
    season: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.SEASON"
            ),
            "description": "Combine season year",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
            "fk_ref": "staging_player.person_id",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.POSITION"
            ),
            "description": "Player position",
        },
    )
    height_wo_shoes: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".HEIGHT_WO_SHOES"
            ),
            "description": (
                "Height without shoes in inches"
            ),
        },
    )
    height_wo_shoes_ft_in: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".HEIGHT_WO_SHOES_FT_IN"
            ),
            "description": (
                "Height without shoes in"
                " feet-inches"
            ),
        },
    )
    height_w_shoes: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".HEIGHT_W_SHOES"
            ),
            "description": (
                "Height with shoes in inches"
            ),
        },
    )
    height_w_shoes_ft_in: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".HEIGHT_W_SHOES_FT_IN"
            ),
            "description": (
                "Height with shoes in feet-inches"
            ),
        },
    )
    weight: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.WEIGHT"
            ),
            "description": (
                "Player weight in pounds"
            ),
        },
    )
    wingspan: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.WINGSPAN"
            ),
            "description": "Wingspan in inches",
        },
    )
    wingspan_ft_in: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".WINGSPAN_FT_IN"
            ),
            "description": (
                "Wingspan in feet-inches"
            ),
        },
    )
    standing_reach: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".STANDING_REACH"
            ),
            "description": (
                "Standing reach in inches"
            ),
        },
    )
    standing_reach_ft_in: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".STANDING_REACH_FT_IN"
            ),
            "description": (
                "Standing reach in feet-inches"
            ),
        },
    )
    body_fat_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.BODY_FAT_PCT"
            ),
            "description": "Body fat percentage",
        },
    )
    hand_length: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.HAND_LENGTH"
            ),
            "description": (
                "Hand length in inches"
            ),
        },
    )
    hand_width: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.HAND_WIDTH"
            ),
            "description": "Hand width in inches",
        },
    )
    standing_vertical_leap: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".STANDING_VERTICAL_LEAP"
            ),
            "description": (
                "Standing vertical leap in inches"
            ),
        },
    )
    max_vertical_leap: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".MAX_VERTICAL_LEAP"
            ),
            "description": (
                "Maximum vertical leap in inches"
            ),
        },
    )
    lane_agility_time: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".LANE_AGILITY_TIME"
            ),
            "description": (
                "Lane agility drill time"
                " in seconds"
            ),
        },
    )
    modified_lane_agility_time: float | None = (
        pa.Field(
            nullable=True,
            gt=0,
            metadata={
                "source": (
                    "DraftCombineStats"
                    ".DraftCombineStats"
                    ".MODIFIED_LANE_AGILITY_TIME"
                ),
                "description": (
                    "Modified lane agility time"
                    " in seconds"
                ),
            },
        )
    )
    three_quarter_sprint: float | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".THREE_QUARTER_SPRINT"
            ),
            "description": (
                "Three-quarter court sprint"
                " time in seconds"
            ),
        },
    )
    bench_press: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.BENCH_PRESS"
            ),
            "description": (
                "Bench press repetitions"
            ),
        },
    )
