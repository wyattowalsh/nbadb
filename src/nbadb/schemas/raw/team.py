from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawCommonTeamYearsSchema(BaseSchema):
    league_id: str = pa.Field(
        metadata={
            "source": (
                "CommonTeamYears.TeamYears.LEAGUE_ID"
            ),
            "description": "League identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "CommonTeamYears.TeamYears.TEAM_ID"
            ),
            "description": "Unique team identifier",
        },
    )
    min_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamYears.TeamYears.MIN_YEAR"
            ),
            "description": "First year of team activity",
        },
    )
    max_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamYears.TeamYears.MAX_YEAR"
            ),
            "description": "Last year of team activity",
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonTeamYears.TeamYears.ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )


class RawTeamInfoCommonSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.TEAM_ID"
            ),
            "description": "Unique team identifier",
        },
    )
    season_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.SEASON_YEAR"
            ),
            "description": "Season year string",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon"
                ".TEAM_CONFERENCE"
            ),
            "description": "Conference name",
        },
    )
    team_division: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon"
                ".TEAM_DIVISION"
            ),
            "description": "Division name",
        },
    )
    team_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.TEAM_CODE"
            ),
            "description": "Team code slug",
        },
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.TEAM_SLUG"
            ),
            "description": "URL-friendly team slug",
        },
    )
    w: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.W",
            "description": "Wins",
        },
    )
    l: int | None = pa.Field(  # noqa: E741
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.L",
            "description": "Losses",
        },
    )
    pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "TeamInfoCommon.TeamInfoCommon.PCT",
            "description": "Win percentage",
        },
    )
    conf_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.CONF_RANK"
            ),
            "description": "Conference ranking",
        },
    )
    div_rank: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.DIV_RANK"
            ),
            "description": "Division ranking",
        },
    )
    min_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.MIN_YEAR"
            ),
            "description": "First year of team activity",
        },
    )
    max_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamInfoCommon.TeamInfoCommon.MAX_YEAR"
            ),
            "description": "Last year of team activity",
        },
    )


class RawTeamDetailsSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.TEAM_ID"
            ),
            "description": "Unique team identifier",
        },
    )
    abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.NICKNAME"
            ),
            "description": "Team nickname",
        },
    )
    yearfounded: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.YEARFOUNDED"
            ),
            "description": "Year the team was founded",
        },
    )
    city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.CITY"
            ),
            "description": "Team city name",
        },
    )
    arena: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.ARENA"
            ),
            "description": "Home arena name",
        },
    )
    arenacapacity: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.ARENACAPACITY"
            ),
            "description": "Arena seating capacity",
        },
    )
    owner: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.OWNER"
            ),
            "description": "Team owner name",
        },
    )
    generalmanager: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.GENERALMANAGER"
            ),
            "description": "General manager name",
        },
    )
    headcoach: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground.HEADCOACH"
            ),
            "description": "Head coach name",
        },
    )
    dleagueaffiliation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "TeamDetails.TeamBackground"
                ".DLEAGUEAFFILIATION"
            ),
            "description": "G-League affiliate team name",
        },
    )
