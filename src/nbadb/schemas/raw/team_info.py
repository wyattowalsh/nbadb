from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawCommonTeamRosterSchema(BaseSchema):
    teamid: int = pa.Field(
        gt=0,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.TeamID"),
            "description": "Unique team identifier",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.SEASON"),
            "description": "Season string",
        },
    )
    leagueid: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.LeagueID"),
            "description": "League identifier",
        },
    )
    player: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.PLAYER"),
            "description": "Player full name",
        },
    )
    nickname: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.NICKNAME"),
            "description": "Player nickname",
        },
    )
    player_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.PLAYER_SLUG"),
            "description": ("URL-friendly player slug"),
        },
    )
    num: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.NUM"),
            "description": ("Jersey number as string"),
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.POSITION"),
            "description": "Player position",
        },
    )
    height: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.HEIGHT"),
            "description": "Player height as string",
        },
    )
    weight: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.WEIGHT"),
            "description": "Player weight as string",
        },
    )
    birth_date: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.BIRTH_DATE"),
            "description": "Player date of birth",
        },
    )
    age: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.AGE"),
            "description": "Player age",
        },
    )
    exp: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.EXP"),
            "description": ("Years of experience as string"),
        },
    )
    school: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.SCHOOL"),
            "description": ("School or college attended"),
        },
    )
    player_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.PLAYER_ID"),
            "description": "Unique player identifier",
        },
    )
    how_acquired: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.CommonTeamRoster.HOW_ACQUIRED"),
            "description": ("How the player was acquired"),
        },
    )


class RawCommonTeamRosterCoachesSchema(BaseSchema):
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("CommonTeamRoster.Coaches.TEAM_ID"),
            "description": "Unique team identifier",
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.SEASON"),
            "description": "Season string",
        },
    )
    coach_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.COACH_ID"),
            "description": ("Unique coach identifier"),
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.FIRST_NAME"),
            "description": "Coach first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.LAST_NAME"),
            "description": "Coach last name",
        },
    )
    coach_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.COACH_NAME"),
            "description": "Coach full name",
        },
    )
    is_assistant: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.IS_ASSISTANT"),
            "description": ("Flag indicating assistant coach"),
        },
    )
    coach_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.COACH_TYPE"),
            "description": "Type of coaching role",
        },
    )
    sort_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.SORT_SEQUENCE"),
            "description": "Display sort order",
        },
    )
    sub_sort_sequence: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.SUB_SORT_SEQUENCE"),
            "description": ("Secondary display sort order"),
        },
    )
    school: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonTeamRoster.Coaches.SCHOOL"),
            "description": ("School or college attended"),
        },
    )


class RawFranchiseHistorySchema(BaseSchema):
    league_id: str = pa.Field(
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.LEAGUE_ID"),
            "description": "League identifier",
        },
    )
    team_id: int = pa.Field(
        gt=0,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.TEAM_ID"),
            "description": "Unique team identifier",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.TEAM_CITY"),
            "description": "Team city name",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.TEAM_NAME"),
            "description": "Team name",
        },
    )
    start_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.START_YEAR"),
            "description": ("First year of franchise era"),
        },
    )
    end_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.END_YEAR"),
            "description": ("Last year of franchise era"),
        },
    )
    years: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.YEARS"),
            "description": ("Total years in franchise era"),
        },
    )
    games: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.GAMES"),
            "description": "Total games played",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.WINS"),
            "description": "Total wins",
        },
    )
    losses: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.LOSSES"),
            "description": "Total losses",
        },
    )
    win_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.WIN_PCT"),
            "description": "Win percentage",
        },
    )
    po_appearances: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.PO_APPEARANCES"),
            "description": ("Playoff appearances count"),
        },
    )
    div_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.DIV_TITLES"),
            "description": ("Division titles won"),
        },
    )
    conf_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.CONF_TITLES"),
            "description": ("Conference titles won"),
        },
    )
    league_titles: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("FranchiseHistory.FranchiseHistory.LEAGUE_TITLES"),
            "description": ("League championships won"),
        },
    )
