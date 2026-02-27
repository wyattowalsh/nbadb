from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingCommonAllPlayersSchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".PERSON_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    display_last_comma_first: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".DISPLAY_LAST_COMMA_FIRST"
            ),
            "description": "Player name as Last, First",
        },
    )
    display_first_last: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".DISPLAY_FIRST_LAST"
            ),
            "description": "Player name as First Last",
        },
    )
    roster_status: int | None = pa.Field(
        nullable=True,
        isin=[0, 1],
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".ROSTER_STATUS"
            ),
            "description": "Active roster flag (0 or 1)",
        },
    )
    from_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".FROM_YEAR"
            ),
            "description": "First year in the league",
        },
    )
    to_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TO_YEAR"
            ),
            "description": "Last year in the league",
        },
    )
    playercode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".PLAYERCODE"
            ),
            "description": "Player code slug",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".TEAM_CODE"
            ),
            "description": "Team code slug",
        },
    )
    games_played_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonAllPlayers.CommonAllPlayers"
                ".GAMES_PLAYED_FLAG"
            ),
            "description": (
                "Flag indicating games played"
            ),
        },
    )


class StagingPlayerIndexSchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.PERSON_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    player_last_name: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".PLAYER_LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    player_first_name: str = pa.Field(
        nullable=False,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".PLAYER_FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    player_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.PLAYER_SLUG"
            ),
            "description": "URL-friendly player slug",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.TEAM_ID"
            ),
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.TEAM_SLUG"
            ),
            "description": "URL-friendly team slug",
        },
    )
    is_defunct: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.IS_DEFUNCT"
            ),
            "description": "Whether team is defunct",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    jersey_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".JERSEY_NUMBER"
            ),
            "description": "Jersey number as string",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.POSITION"
            ),
            "description": "Player position",
        },
    )
    height: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.HEIGHT"
            ),
            "description": "Player height as string",
        },
    )
    weight: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.WEIGHT"
            ),
            "description": "Player weight as string",
        },
    )
    college: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.COLLEGE"
            ),
            "description": "College attended",
        },
    )
    country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.COUNTRY"
            ),
            "description": "Country of origin",
        },
    )
    draft_year: int | None = pa.Field(
        nullable=True,
        gt=1946,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.DRAFT_YEAR"
            ),
            "description": "Year drafted",
        },
    )
    draft_round: int | None = pa.Field(
        nullable=True,
        isin=[1, 2],
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.DRAFT_ROUND"
            ),
            "description": "Round drafted",
        },
    )
    draft_number: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".DRAFT_NUMBER"
            ),
            "description": "Overall draft pick number",
        },
    )
    roster_status: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".ROSTER_STATUS"
            ),
            "description": "Active roster status",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayerIndex.PlayerIndex.PTS",
            "description": "Points per game",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayerIndex.PlayerIndex.REB",
            "description": "Rebounds per game",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayerIndex.PlayerIndex.AST",
            "description": "Assists per game",
        },
    )
    stats_timeframe: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex"
                ".STATS_TIMEFRAME"
            ),
            "description": "Timeframe for stats",
        },
    )
    from_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.FROM_YEAR"
            ),
            "description": "First year in the league",
        },
    )
    to_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerIndex.PlayerIndex.TO_YEAR"
            ),
            "description": "Last year in the league",
        },
    )
