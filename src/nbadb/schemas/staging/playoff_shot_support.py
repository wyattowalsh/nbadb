from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema
from nbadb.schemas.staging.misc import StagingShotChartDetailSchema


class StagingShotChartLeagueAveragesSchema(BaseSchema):
    grid_type: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.GRID_TYPE",
            "description": "Shot chart grid type",
        },
    )
    shot_zone_basic: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.SHOT_ZONE_BASIC",
            "description": "Basic shot zone category",
        },
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.SHOT_ZONE_AREA",
            "description": "Shot zone area on court",
        },
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.SHOT_ZONE_RANGE",
            "description": "Shot zone distance bucket",
        },
    )
    fga: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.FGA",
            "description": "Field goals attempted",
        },
    )
    fgm: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.FGM",
            "description": "Field goals made",
        },
    )
    fg_pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={
            "source": "ShotChartDetail.LeagueAverages.FG_PCT",
            "description": "Field goal percentage",
        },
    )


class StagingShotChartLineupSchema(StagingShotChartDetailSchema):
    group_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartLineupDetail.ShotChartLineupDetail.GROUP_ID",
            "description": "Lineup group identifier",
        },
    )
    group_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "ShotChartLineupDetail.ShotChartLineupDetail.GROUP_NAME",
            "description": "Lineup group display name",
        },
    )


class StagingShotChartLineupDetailSchema(StagingShotChartLineupSchema):
    pass


class StagingShotChartLineupLeagueAvgSchema(StagingShotChartLeagueAveragesSchema):
    pass


class PlayoffPictureRemainingBaseSchema(BaseSchema):
    team: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfRemainingGames.TEAM", "description": "Team name"},
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "PlayoffPicture.ConfRemainingGames.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    remaining_g: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayoffPicture.ConfRemainingGames.REMAINING_G",
            "description": "Remaining games",
        },
    )
    remaining_home_g: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayoffPicture.ConfRemainingGames.REMAINING_HOME_G",
            "description": "Remaining home games",
        },
    )
    remaining_away_g: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={
            "source": "PlayoffPicture.ConfRemainingGames.REMAINING_AWAY_G",
            "description": "Remaining away games",
        },
    )


class StagingPlayoffPictureEastRemainingSchema(PlayoffPictureRemainingBaseSchema):
    pass


class StagingPlayoffPictureWestRemainingSchema(PlayoffPictureRemainingBaseSchema):
    pass


class PlayoffPictureStandingsBaseSchema(BaseSchema):
    conference: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.CONFERENCE",
            "description": "Conference name",
        },
    )
    rank: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"source": "PlayoffPicture.ConfStandings.RANK", "description": "Conference rank"},
    )
    team: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.TEAM", "description": "Team name"},
    )
    team_slug: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.TEAM_SLUG", "description": "Team slug"},
    )
    team_id: int | None = pa.Field(
        nullable=True,
        gt=0,
        metadata={
            "source": "PlayoffPicture.ConfStandings.TEAM_ID",
            "description": "Team identifier",
            "fk_ref": "staging_team.team_id",
        },
    )
    wins: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"source": "PlayoffPicture.ConfStandings.WINS", "description": "Wins"},
    )
    losses: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"source": "PlayoffPicture.ConfStandings.LOSSES", "description": "Losses"},
    )
    pct: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        le=1.0,
        metadata={"source": "PlayoffPicture.ConfStandings.PCT", "description": "Win percentage"},
    )
    div: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.DIV", "description": "Division record"},
    )
    conf: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.CONF",
            "description": "Conference record",
        },
    )
    home: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.HOME", "description": "Home record"},
    )
    away: str | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.AWAY", "description": "Away record"},
    )
    gb: float | None = pa.Field(
        nullable=True,
        metadata={"source": "PlayoffPicture.ConfStandings.GB", "description": "Games behind"},
    )
    gr_over_500: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_OVER_500",
            "description": "Games remaining vs teams over .500",
        },
    )
    gr_over_500_home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_OVER_500_HOME",
            "description": "Home games remaining vs teams over .500",
        },
    )
    gr_over_500_away: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_OVER_500_AWAY",
            "description": "Away games remaining vs teams over .500",
        },
    )
    gr_under_500: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_UNDER_500",
            "description": "Games remaining vs teams under .500",
        },
    )
    gr_under_500_home: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_UNDER_500_HOME",
            "description": "Home games remaining vs teams under .500",
        },
    )
    gr_under_500_away: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.GR_UNDER_500_AWAY",
            "description": "Away games remaining vs teams under .500",
        },
    )
    ranking_criteria: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.RANKING_CRITERIA",
            "description": "Ranking criteria summary",
        },
    )
    clinched_playoffs: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.CLINCHED_PLAYOFFS",
            "description": "Whether the team clinched the playoffs",
        },
    )
    clinched_conference: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.CLINCHED_CONFERENCE",
            "description": "Whether the team clinched the conference",
        },
    )
    clinched_division: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.CLINCHED_DIVISION",
            "description": "Whether the team clinched the division",
        },
    )
    clinched_play_in: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Clinched_Play_In",
            "description": "Whether the team clinched the play-in",
        },
    )
    eliminated_playoffs: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.ELIMINATED_PLAYOFFS",
            "description": "Whether the team is eliminated from playoffs",
        },
    )
    sosa_remaining: float | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.SOSA_REMAINING",
            "description": "Strength of schedule remaining",
        },
    )
    return_to_play_already_eliminated: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.ReturnToPlay_Already_Eliminated",
            "description": (
                "Whether the team was already eliminated entering return-to-play seeding games"
            ),
        },
    )
    seeding_game_1_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_1_Outcome",
            "description": "Outcome of seeding game 1",
        },
    )
    seeding_game_2_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_2_Outcome",
            "description": "Outcome of seeding game 2",
        },
    )
    seeding_game_3_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_3_Outcome",
            "description": "Outcome of seeding game 3",
        },
    )
    seeding_game_4_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_4_Outcome",
            "description": "Outcome of seeding game 4",
        },
    )
    seeding_game_5_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_5_Outcome",
            "description": "Outcome of seeding game 5",
        },
    )
    seeding_game_6_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_6_Outcome",
            "description": "Outcome of seeding game 6",
        },
    )
    seeding_game_7_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_7_Outcome",
            "description": "Outcome of seeding game 7",
        },
    )
    seeding_game_8_outcome: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_8_Outcome",
            "description": "Outcome of seeding game 8",
        },
    )
    seeding_game_1_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_1_ID",
            "description": "Game identifier for seeding game 1",
        },
    )
    seeding_game_2_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_2_ID",
            "description": "Game identifier for seeding game 2",
        },
    )
    seeding_game_3_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_3_ID",
            "description": "Game identifier for seeding game 3",
        },
    )
    seeding_game_4_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_4_ID",
            "description": "Game identifier for seeding game 4",
        },
    )
    seeding_game_5_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_5_ID",
            "description": "Game identifier for seeding game 5",
        },
    )
    seeding_game_6_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_6_ID",
            "description": "Game identifier for seeding game 6",
        },
    )
    seeding_game_7_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_7_ID",
            "description": "Game identifier for seeding game 7",
        },
    )
    seeding_game_8_id: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_8_ID",
            "description": "Game identifier for seeding game 8",
        },
    )
    seeding_game_1_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_1_Opponent",
            "description": "Opponent in seeding game 1",
        },
    )
    seeding_game_2_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_2_Opponent",
            "description": "Opponent in seeding game 2",
        },
    )
    seeding_game_3_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_3_Opponent",
            "description": "Opponent in seeding game 3",
        },
    )
    seeding_game_4_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_4_Opponent",
            "description": "Opponent in seeding game 4",
        },
    )
    seeding_game_5_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_5_Opponent",
            "description": "Opponent in seeding game 5",
        },
    )
    seeding_game_6_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_6_Opponent",
            "description": "Opponent in seeding game 6",
        },
    )
    seeding_game_7_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_7_Opponent",
            "description": "Opponent in seeding game 7",
        },
    )
    seeding_game_8_opponent: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_8_Opponent",
            "description": "Opponent in seeding game 8",
        },
    )
    seeding_game_1_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_1_Label",
            "description": "Label for seeding game 1",
        },
    )
    seeding_game_2_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_2_Label",
            "description": "Label for seeding game 2",
        },
    )
    seeding_game_3_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_3_Label",
            "description": "Label for seeding game 3",
        },
    )
    seeding_game_4_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_4_Label",
            "description": "Label for seeding game 4",
        },
    )
    seeding_game_5_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_5_Label",
            "description": "Label for seeding game 5",
        },
    )
    seeding_game_6_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_6_Label",
            "description": "Label for seeding game 6",
        },
    )
    seeding_game_7_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_7_Label",
            "description": "Label for seeding game 7",
        },
    )
    seeding_game_8_label: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.ConfStandings.Seeding_Game_8_Label",
            "description": "Label for seeding game 8",
        },
    )


class StagingPlayoffPictureEastStandingsSchema(PlayoffPictureStandingsBaseSchema):
    return_to_play_east_pi_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.EastConfStandings.ReturnToPlay_East_PI_Flag",
            "description": "Return-to-play play-in flag for East",
        },
    )


class StagingPlayoffPictureWestStandingsSchema(PlayoffPictureStandingsBaseSchema):
    return_to_play_west_pi_flag: int | None = pa.Field(
        nullable=True,
        metadata={
            "source": "PlayoffPicture.WestConfStandings.ReturnToPlay_West_PI_Flag",
            "description": "Return-to-play play-in flag for West",
        },
    )
