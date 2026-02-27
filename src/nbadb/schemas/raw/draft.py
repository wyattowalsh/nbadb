from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawDraftHistorySchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.PERSON_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.SEASON"
            ),
            "description": "Draft season year",
        },
    )
    round_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.ROUND_NUMBER"
            ),
            "description": "Draft round number",
        },
    )
    round_pick: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.ROUND_PICK"
            ),
            "description": "Pick number within the round",
        },
    )
    overall_pick: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.OVERALL_PICK"
            ),
            "description": "Overall draft pick number",
        },
    )
    draft_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.DRAFT_TYPE"
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
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory.TEAM_NAME"
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
                "DraftHistory.DraftHistory.ORGANIZATION"
            ),
            "description": "Pre-draft organization",
        },
    )
    organization_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".ORGANIZATION_TYPE"
            ),
            "description": "Type of pre-draft organization",
        },
    )
    player_profile_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftHistory.DraftHistory"
                ".PLAYER_PROFILE_FLAG"
            ),
            "description": "Player profile availability flag",
        },
    )


class RawDraftCombineStatsSchema(BaseSchema):
    season: str = pa.Field(
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.PLAYER_ID"
            ),
            "description": "Unique player identifier",
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.HEIGHT_WO_SHOES"
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
                "Height without shoes in feet-inches"
            ),
        },
    )
    height_w_shoes: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.HEIGHT_W_SHOES"
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.WEIGHT"
            ),
            "description": "Player weight in pounds",
        },
    )
    wingspan: float | None = pa.Field(
        nullable=True,
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
                ".DraftCombineStats.WINGSPAN_FT_IN"
            ),
            "description": "Wingspan in feet-inches",
        },
    )
    standing_reach: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.STANDING_REACH"
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.HAND_LENGTH"
            ),
            "description": "Hand length in inches",
        },
    )
    hand_width: float | None = pa.Field(
        nullable=True,
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats"
                ".LANE_AGILITY_TIME"
            ),
            "description": (
                "Lane agility drill time in seconds"
            ),
        },
    )
    modified_lane_agility_time: float | None = (
        pa.Field(
            nullable=True,
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
        metadata={
            "source": (
                "DraftCombineStats"
                ".DraftCombineStats.BENCH_PRESS"
            ),
            "description": "Bench press repetitions",
        },
    )


class RawDraftCombineDrillResultsSchema(BaseSchema):
    season: str = pa.Field(
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.SEASON"
            ),
            "description": "Combine season year",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.POSITION"
            ),
            "description": "Player position",
        },
    )
    standing_vertical_leap: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.STANDING_VERTICAL_LEAP"
            ),
            "description": (
                "Standing vertical leap in inches"
            ),
        },
    )
    max_vertical_leap: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.MAX_VERTICAL_LEAP"
            ),
            "description": (
                "Maximum vertical leap in inches"
            ),
        },
    )
    lane_agility_time: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.LANE_AGILITY_TIME"
            ),
            "description": (
                "Lane agility drill time in seconds"
            ),
        },
    )
    modified_lane_agility_time: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineDrillResults"
                    ".Results"
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
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.THREE_QUARTER_SPRINT"
            ),
            "description": (
                "Three-quarter court sprint"
                " time in seconds"
            ),
        },
    )
    bench_press: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineDrillResults"
                ".Results.BENCH_PRESS"
            ),
            "description": "Bench press repetitions",
        },
    )


class RawDraftCombinePlayerAnthroSchema(BaseSchema):
    season: str = pa.Field(
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.SEASON"
            ),
            "description": "Combine season year",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.POSITION"
            ),
            "description": "Player position",
        },
    )
    height_wo_shoes: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.HEIGHT_WO_SHOES"
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
                "DraftCombinePlayerAnthro"
                ".Results"
                ".HEIGHT_WO_SHOES_FT_IN"
            ),
            "description": (
                "Height without shoes in feet-inches"
            ),
        },
    )
    height_w_shoes: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.HEIGHT_W_SHOES"
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
                "DraftCombinePlayerAnthro"
                ".Results"
                ".HEIGHT_W_SHOES_FT_IN"
            ),
            "description": (
                "Height with shoes in feet-inches"
            ),
        },
    )
    weight: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.WEIGHT"
            ),
            "description": "Player weight in pounds",
        },
    )
    wingspan: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.WINGSPAN"
            ),
            "description": "Wingspan in inches",
        },
    )
    wingspan_ft_in: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.WINGSPAN_FT_IN"
            ),
            "description": "Wingspan in feet-inches",
        },
    )
    standing_reach: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.STANDING_REACH"
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
                "DraftCombinePlayerAnthro"
                ".Results"
                ".STANDING_REACH_FT_IN"
            ),
            "description": (
                "Standing reach in feet-inches"
            ),
        },
    )
    body_fat_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.BODY_FAT_PCT"
            ),
            "description": "Body fat percentage",
        },
    )
    hand_length: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.HAND_LENGTH"
            ),
            "description": "Hand length in inches",
        },
    )
    hand_width: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombinePlayerAnthro"
                ".Results.HAND_WIDTH"
            ),
            "description": "Hand width in inches",
        },
    )


class RawDraftCombineSpotShootingSchema(BaseSchema):
    season: str = pa.Field(
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.SEASON"
            ),
            "description": "Combine season year",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.POSITION"
            ),
            "description": "Player position",
        },
    )
    nba_break_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_LEFT_MADE"
            ),
            "description": (
                "NBA break left shots made"
            ),
        },
    )
    nba_break_left_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_LEFT_ATTEMPT"
            ),
            "description": (
                "NBA break left shots attempted"
            ),
        },
    )
    nba_break_left_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_LEFT_PCT"
            ),
            "description": (
                "NBA break left shooting percentage"
            ),
        },
    )
    nba_break_right_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_RIGHT_MADE"
            ),
            "description": (
                "NBA break right shots made"
            ),
        },
    )
    nba_break_right_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_RIGHT_ATTEMPT"
            ),
            "description": (
                "NBA break right shots attempted"
            ),
        },
    )
    nba_break_right_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_BREAK_RIGHT_PCT"
            ),
            "description": (
                "NBA break right shooting percentage"
            ),
        },
    )
    nba_corner_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_CORNER_LEFT_MADE"
            ),
            "description": (
                "NBA corner left shots made"
            ),
        },
    )
    nba_corner_left_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_CORNER_LEFT_ATTEMPT"
            ),
            "description": (
                "NBA corner left shots attempted"
            ),
        },
    )
    nba_corner_left_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_CORNER_LEFT_PCT"
            ),
            "description": (
                "NBA corner left shooting percentage"
            ),
        },
    )
    nba_corner_right_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_CORNER_RIGHT_MADE"
            ),
            "description": (
                "NBA corner right shots made"
            ),
        },
    )
    nba_corner_right_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".NBA_CORNER_RIGHT_ATTEMPT"
            ),
            "description": (
                "NBA corner right shots attempted"
            ),
        },
    )
    nba_corner_right_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_CORNER_RIGHT_PCT"
            ),
            "description": (
                "NBA corner right shooting percentage"
            ),
        },
    )
    nba_top_key_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_TOP_KEY_MADE"
            ),
            "description": (
                "NBA top of key shots made"
            ),
        },
    )
    nba_top_key_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_TOP_KEY_ATTEMPT"
            ),
            "description": (
                "NBA top of key shots attempted"
            ),
        },
    )
    nba_top_key_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.NBA_TOP_KEY_PCT"
            ),
            "description": (
                "NBA top of key shooting percentage"
            ),
        },
    )
    college_break_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.COLLEGE_BREAK_LEFT_MADE"
            ),
            "description": (
                "College break left shots made"
            ),
        },
    )
    college_break_left_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_BREAK_LEFT_ATTEMPT"
                ),
                "description": (
                    "College break left shots"
                    " attempted"
                ),
            },
        )
    )
    college_break_left_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.COLLEGE_BREAK_LEFT_PCT"
            ),
            "description": (
                "College break left shooting"
                " percentage"
            ),
        },
    )
    college_break_right_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".COLLEGE_BREAK_RIGHT_MADE"
            ),
            "description": (
                "College break right shots made"
            ),
        },
    )
    college_break_right_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_BREAK_RIGHT_ATTEMPT"
                ),
                "description": (
                    "College break right shots"
                    " attempted"
                ),
            },
        )
    )
    college_break_right_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_BREAK_RIGHT_PCT"
                ),
                "description": (
                    "College break right shooting"
                    " percentage"
                ),
            },
        )
    )
    college_corner_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".COLLEGE_CORNER_LEFT_MADE"
            ),
            "description": (
                "College corner left shots made"
            ),
        },
    )
    college_corner_left_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_CORNER_LEFT_ATTEMPT"
                ),
                "description": (
                    "College corner left shots"
                    " attempted"
                ),
            },
        )
    )
    college_corner_left_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_CORNER_LEFT_PCT"
                ),
                "description": (
                    "College corner left shooting"
                    " percentage"
                ),
            },
        )
    )
    college_corner_right_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_CORNER_RIGHT_MADE"
                ),
                "description": (
                    "College corner right shots made"
                ),
            },
        )
    )
    college_corner_right_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_CORNER_RIGHT_ATTEMPT"
                ),
                "description": (
                    "College corner right shots"
                    " attempted"
                ),
            },
        )
    )
    college_corner_right_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".COLLEGE_CORNER_RIGHT_PCT"
                ),
                "description": (
                    "College corner right shooting"
                    " percentage"
                ),
            },
        )
    )
    college_top_key_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.COLLEGE_TOP_KEY_MADE"
            ),
            "description": (
                "College top of key shots made"
            ),
        },
    )
    college_top_key_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".COLLEGE_TOP_KEY_ATTEMPT"
            ),
            "description": (
                "College top of key shots attempted"
            ),
        },
    )
    college_top_key_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.COLLEGE_TOP_KEY_PCT"
            ),
            "description": (
                "College top of key shooting"
                " percentage"
            ),
        },
    )
    fifteen_break_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".FIFTEEN_BREAK_LEFT_MADE"
            ),
            "description": (
                "Fifteen-foot break left shots made"
            ),
        },
    )
    fifteen_break_left_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_BREAK_LEFT_ATTEMPT"
                ),
                "description": (
                    "Fifteen-foot break left shots"
                    " attempted"
                ),
            },
        )
    )
    fifteen_break_left_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".FIFTEEN_BREAK_LEFT_PCT"
            ),
            "description": (
                "Fifteen-foot break left shooting"
                " percentage"
            ),
        },
    )
    fifteen_break_right_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".FIFTEEN_BREAK_RIGHT_MADE"
            ),
            "description": (
                "Fifteen-foot break right shots made"
            ),
        },
    )
    fifteen_break_right_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_BREAK_RIGHT_ATTEMPT"
                ),
                "description": (
                    "Fifteen-foot break right shots"
                    " attempted"
                ),
            },
        )
    )
    fifteen_break_right_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_BREAK_RIGHT_PCT"
                ),
                "description": (
                    "Fifteen-foot break right shooting"
                    " percentage"
                ),
            },
        )
    )
    fifteen_corner_left_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".FIFTEEN_CORNER_LEFT_MADE"
            ),
            "description": (
                "Fifteen-foot corner left shots made"
            ),
        },
    )
    fifteen_corner_left_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_CORNER_LEFT_ATTEMPT"
                ),
                "description": (
                    "Fifteen-foot corner left shots"
                    " attempted"
                ),
            },
        )
    )
    fifteen_corner_left_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_CORNER_LEFT_PCT"
                ),
                "description": (
                    "Fifteen-foot corner left shooting"
                    " percentage"
                ),
            },
        )
    )
    fifteen_corner_right_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_CORNER_RIGHT_MADE"
                ),
                "description": (
                    "Fifteen-foot corner right"
                    " shots made"
                ),
            },
        )
    )
    fifteen_corner_right_attempt: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_CORNER_RIGHT_ATTEMPT"
                ),
                "description": (
                    "Fifteen-foot corner right shots"
                    " attempted"
                ),
            },
        )
    )
    fifteen_corner_right_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineSpotShooting"
                    ".Results"
                    ".FIFTEEN_CORNER_RIGHT_PCT"
                ),
                "description": (
                    "Fifteen-foot corner right"
                    " shooting percentage"
                ),
            },
        )
    )
    fifteen_top_key_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.FIFTEEN_TOP_KEY_MADE"
            ),
            "description": (
                "Fifteen-foot top of key shots made"
            ),
        },
    )
    fifteen_top_key_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results"
                ".FIFTEEN_TOP_KEY_ATTEMPT"
            ),
            "description": (
                "Fifteen-foot top of key shots"
                " attempted"
            ),
        },
    )
    fifteen_top_key_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineSpotShooting"
                ".Results.FIFTEEN_TOP_KEY_PCT"
            ),
            "description": (
                "Fifteen-foot top of key shooting"
                " percentage"
            ),
        },
    )


class RawDraftCombineNonStationaryShootingSchema(
    BaseSchema,
):
    season: str = pa.Field(
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.SEASON"
            ),
            "description": "Combine season year",
        },
    )
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.PLAYER_NAME"
            ),
            "description": "Player full name",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.POSITION"
            ),
            "description": "Player position",
        },
    )
    off_drib_fifteen_break_left_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_FIFTEEN_BREAK_LEFT_MADE"
                ),
                "description": (
                    "Off-dribble fifteen-foot break"
                    " left shots made"
                ),
            },
        )
    )
    off_drib_fifteen_break_left_attempt: (
        int | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_FIFTEEN_BREAK_LEFT"
                "_ATTEMPT"
            ),
            "description": (
                "Off-dribble fifteen-foot break"
                " left shots attempted"
            ),
        },
    )
    off_drib_fifteen_break_left_pct: (
        float | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_FIFTEEN_BREAK_LEFT_PCT"
            ),
            "description": (
                "Off-dribble fifteen-foot break"
                " left shooting percentage"
            ),
        },
    )
    off_drib_fifteen_top_key_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_FIFTEEN_TOP_KEY_MADE"
                ),
                "description": (
                    "Off-dribble fifteen-foot top"
                    " of key shots made"
                ),
            },
        )
    )
    off_drib_fifteen_top_key_attempt: (
        int | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_FIFTEEN_TOP_KEY"
                "_ATTEMPT"
            ),
            "description": (
                "Off-dribble fifteen-foot top"
                " of key shots attempted"
            ),
        },
    )
    off_drib_fifteen_top_key_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_FIFTEEN_TOP_KEY_PCT"
                ),
                "description": (
                    "Off-dribble fifteen-foot top"
                    " of key shooting percentage"
                ),
            },
        )
    )
    off_drib_college_break_left_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_COLLEGE_BREAK_LEFT"
                    "_MADE"
                ),
                "description": (
                    "Off-dribble college break"
                    " left shots made"
                ),
            },
        )
    )
    off_drib_college_break_left_attempt: (
        int | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_COLLEGE_BREAK_LEFT"
                "_ATTEMPT"
            ),
            "description": (
                "Off-dribble college break"
                " left shots attempted"
            ),
        },
    )
    off_drib_college_break_left_pct: (
        float | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_COLLEGE_BREAK_LEFT_PCT"
            ),
            "description": (
                "Off-dribble college break"
                " left shooting percentage"
            ),
        },
    )
    off_drib_college_top_key_made: int | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_COLLEGE_TOP_KEY_MADE"
                ),
                "description": (
                    "Off-dribble college top"
                    " of key shots made"
                ),
            },
        )
    )
    off_drib_college_top_key_attempt: (
        int | None
    ) = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".OFF_DRIB_COLLEGE_TOP_KEY"
                "_ATTEMPT"
            ),
            "description": (
                "Off-dribble college top"
                " of key shots attempted"
            ),
        },
    )
    off_drib_college_top_key_pct: float | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "DraftCombineNonStationaryShooting"
                    ".Results"
                    ".OFF_DRIB_COLLEGE_TOP_KEY_PCT"
                ),
                "description": (
                    "Off-dribble college top"
                    " of key shooting percentage"
                ),
            },
        )
    )
    on_move_fifteen_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.ON_MOVE_FIFTEEN_MADE"
            ),
            "description": (
                "On-move fifteen-foot shots made"
            ),
        },
    )
    on_move_fifteen_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".ON_MOVE_FIFTEEN_ATTEMPT"
            ),
            "description": (
                "On-move fifteen-foot shots"
                " attempted"
            ),
        },
    )
    on_move_fifteen_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.ON_MOVE_FIFTEEN_PCT"
            ),
            "description": (
                "On-move fifteen-foot shooting"
                " percentage"
            ),
        },
    )
    on_move_college_made: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.ON_MOVE_COLLEGE_MADE"
            ),
            "description": (
                "On-move college range shots made"
            ),
        },
    )
    on_move_college_attempt: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results"
                ".ON_MOVE_COLLEGE_ATTEMPT"
            ),
            "description": (
                "On-move college range shots"
                " attempted"
            ),
        },
    )
    on_move_college_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "DraftCombineNonStationaryShooting"
                ".Results.ON_MOVE_COLLEGE_PCT"
            ),
            "description": (
                "On-move college range shooting"
                " percentage"
            ),
        },
    )
