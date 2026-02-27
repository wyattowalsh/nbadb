from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class RawCommonPlayerInfoSchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".PERSON_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    display_first_last: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DISPLAY_FIRST_LAST"
            ),
            "description": "Player name as First Last",
        },
    )
    display_last_comma_first: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DISPLAY_LAST_COMMA_FIRST"
            ),
            "description": (
                "Player name as Last, First"
            ),
        },
    )
    display_fi_last: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DISPLAY_FI_LAST"
            ),
            "description": (
                "Player name as F. Last"
            ),
        },
    )
    player_slug: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".PLAYER_SLUG"
            ),
            "description": "URL-friendly player slug",
        },
    )
    birthdate: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".BIRTHDATE"
            ),
            "description": "Player date of birth",
        },
    )
    school: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".SCHOOL"
            ),
            "description": "School or college attended",
        },
    )
    country: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".COUNTRY"
            ),
            "description": "Country of origin",
        },
    )
    last_affiliation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".LAST_AFFILIATION"
            ),
            "description": (
                "Last team or school affiliation"
            ),
        },
    )
    height: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".HEIGHT"
            ),
            "description": "Player height as string",
        },
    )
    weight: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".WEIGHT"
            ),
            "description": "Player weight as string",
        },
    )
    season_exp: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".SEASON_EXP"
            ),
            "description": (
                "Years of NBA experience"
            ),
        },
    )
    jersey: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".JERSEY"
            ),
            "description": "Jersey number as string",
        },
    )
    position: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".POSITION"
            ),
            "description": "Player position",
        },
    )
    roster_status: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".ROSTER_STATUS"
            ),
            "description": "Current roster status",
        },
    )
    games_played_current_season_flag: str | None = (
        pa.Field(
            nullable=True,
            metadata={
                "source": (
                    "CommonPlayerInfo"
                    ".CommonPlayerInfo"
                    ".GAMES_PLAYED_CURRENT_SEASON_FLAG"
                ),
                "description": (
                    "Flag for games played this season"
                ),
            },
        )
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TEAM_NAME"
            ),
            "description": "Team name",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    team_code: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TEAM_CODE"
            ),
            "description": "Team code slug",
        },
    )
    team_city: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TEAM_CITY"
            ),
            "description": "Team city name",
        },
    )
    playercode: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".PLAYERCODE"
            ),
            "description": "Player code slug",
        },
    )
    from_year: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".FROM_YEAR"
            ),
            "description": (
                "First year in the league"
            ),
        },
    )
    to_year: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".TO_YEAR"
            ),
            "description": (
                "Last year in the league"
            ),
        },
    )
    dleague_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DLEAGUE_FLAG"
            ),
            "description": (
                "G-League eligibility flag"
            ),
        },
    )
    nba_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".NBA_FLAG"
            ),
            "description": "NBA eligibility flag",
        },
    )
    games_played_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".GAMES_PLAYED_FLAG"
            ),
            "description": (
                "Flag indicating games played"
            ),
        },
    )
    draft_year: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DRAFT_YEAR"
            ),
            "description": "Year drafted",
        },
    )
    draft_round: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DRAFT_ROUND"
            ),
            "description": "Round drafted",
        },
    )
    draft_number: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".DRAFT_NUMBER"
            ),
            "description": "Overall draft pick number",
        },
    )
    greatest_75_flag: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "CommonPlayerInfo.CommonPlayerInfo"
                ".GREATEST_75_FLAG"
            ),
            "description": (
                "NBA 75th anniversary team flag"
            ),
        },
    )


class RawPlayerCareerStatsSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".PLAYER_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    season_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".SEASON_ID"
            ),
            "description": (
                "Season identifier string"
            ),
        },
    )
    league_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".LEAGUE_ID"
            ),
            "description": "League identifier",
        },
    )
    team_id: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".TEAM_ID"
            ),
            "description": "Team identifier",
        },
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".TEAM_ABBREVIATION"
            ),
            "description": "Team abbreviation code",
        },
    )
    player_age: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".PLAYER_AGE"
            ),
            "description": (
                "Player age during season"
            ),
        },
    )
    gp: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.GP"
            ),
            "description": "Games played",
        },
    )
    gs: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.GS"
            ),
            "description": "Games started",
        },
    )
    min: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.MIN"
            ),
            "description": "Minutes played",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FGM"
            ),
            "description": "Field goals made",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FGA"
            ),
            "description": "Field goals attempted",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".FG_PCT"
            ),
            "description": "Field goal percentage",
        },
    )
    fg3m: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FG3M"
            ),
            "description": "Three-point field goals made",
        },
    )
    fg3a: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FG3A"
            ),
            "description": (
                "Three-point field goals attempted"
            ),
        },
    )
    fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".FG3_PCT"
            ),
            "description": (
                "Three-point field goal percentage"
            ),
        },
    )
    ftm: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FTM"
            ),
            "description": "Free throws made",
        },
    )
    fta: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.FTA"
            ),
            "description": "Free throws attempted",
        },
    )
    ft_pct: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason"
                ".FT_PCT"
            ),
            "description": "Free throw percentage",
        },
    )
    oreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.OREB"
            ),
            "description": "Offensive rebounds",
        },
    )
    dreb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.DREB"
            ),
            "description": "Defensive rebounds",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.REB"
            ),
            "description": "Total rebounds",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.AST"
            ),
            "description": "Assists",
        },
    )
    stl: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.STL"
            ),
            "description": "Steals",
        },
    )
    blk: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.BLK"
            ),
            "description": "Blocks",
        },
    )
    tov: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.TOV"
            ),
            "description": "Turnovers",
        },
    )
    pf: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.PF"
            ),
            "description": "Personal fouls",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerCareerStats"
                ".SeasonTotalsRegularSeason.PTS"
            ),
            "description": "Points scored",
        },
    )


class RawPlayerAwardsSchema(BaseSchema):
    person_id: int = pa.Field(
        gt=0,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".PERSON_ID"
            ),
            "description": "Unique player identifier",
        },
    )
    first_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".FIRST_NAME"
            ),
            "description": "Player first name",
        },
    )
    last_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".LAST_NAME"
            ),
            "description": "Player last name",
        },
    )
    team: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.TEAM"
            ),
            "description": "Team name at time of award",
        },
    )
    description: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".DESCRIPTION"
            ),
            "description": "Award description",
        },
    )
    all_nba_team_number: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".ALL_NBA_TEAM_NUMBER"
            ),
            "description": (
                "All-NBA team number selection"
            ),
        },
    )
    season: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.SEASON"
            ),
            "description": "Season of the award",
        },
    )
    month: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.MONTH"
            ),
            "description": (
                "Month of the award if applicable"
            ),
        },
    )
    week: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.WEEK"
            ),
            "description": (
                "Week of the award if applicable"
            ),
        },
    )
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards"
                ".CONFERENCE"
            ),
            "description": "Conference for the award",
        },
    )
    type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.TYPE"
            ),
            "description": "Award type category",
        },
    )
    subtype1: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.SUBTYPE1"
            ),
            "description": "Award subtype level 1",
        },
    )
    subtype2: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.SUBTYPE2"
            ),
            "description": "Award subtype level 2",
        },
    )
    subtype3: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": (
                "PlayerAwards.PlayerAwards.SUBTYPE3"
            ),
            "description": "Award subtype level 3",
        },
    )
