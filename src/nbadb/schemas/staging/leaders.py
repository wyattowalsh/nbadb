from __future__ import annotations

from typing import ClassVar

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class _OpenStagingSchema(BaseSchema):
    """Preserve endpoint-specific passthrough columns for leaderboard packets."""

    class Config:
        coerce = False
        strict = False

    _lossless_provider_columns: ClassVar[tuple[str, ...]] = ()
    _provider_source_prefix: ClassVar[str | None] = None
    _compact_provider_column_names: ClassVar[bool] = False

    @classmethod
    def _provider_column_name(cls, column_name: str) -> str:
        provider_column = column_name.upper()
        return (
            provider_column.replace("_", "")
            if cls._compact_provider_column_names
            else provider_column
        )

    @classmethod
    def to_schema(cls):
        """Declare pinned provider fields without inventing unobserved dtypes.

        These provider contracts define names and ordinals but not physical
        types. A dtype-free, nullable Pandera column is therefore the lossless
        silver boundary: it requires every declared field, accepts the dtype
        actually observed in the response, and never coerces its values.
        """

        schema = super().to_schema()
        # Pandera cannot combine schema-level coercion with dtype-free columns.
        # Retain the established coercion behavior for existing typed fields
        # while leaving the newly declared provider fields untouched.
        for column in schema.columns.values():
            if column.dtype is not None:
                column.coerce = True
        if not cls._lossless_provider_columns:
            return schema
        if cls._provider_source_prefix is None:
            raise TypeError(f"{cls.__name__} omitted its provider source prefix")
        existing = set(schema.columns)
        duplicate_columns = existing.intersection(cls._lossless_provider_columns)
        if duplicate_columns:
            raise TypeError(
                f"{cls.__name__} repeats typed provider columns: {sorted(duplicate_columns)}"
            )
        return schema.add_columns(
            {
                column_name: pa.Column(
                    None,
                    nullable=True,
                    required=True,
                    coerce=False,
                    metadata={
                        "source": (
                            f"{cls._provider_source_prefix}."
                            f"{cls._provider_column_name(column_name)}"
                        ),
                        "description": (
                            "Lossless provider field; physical dtype is retained from the "
                            "observed response"
                        ),
                    },
                )
                for column_name in cls._lossless_provider_columns
            }
        )

    @classmethod
    def validate(cls, data, *args, **kwargs):
        return pa.DataFrameModel.validate.__func__(cls, data, *args, **kwargs)


class _AllTimeLeaderBaseSchema(_OpenStagingSchema):
    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Player display name"},
    )


class StagingAllTimeAstSchema(_AllTimeLeaderBaseSchema):
    ast: int | None = pa.Field(nullable=True, ge=0)
    ast_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeBlkSchema(_AllTimeLeaderBaseSchema):
    blk: int | None = pa.Field(nullable=True, ge=0)
    blk_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeDrebSchema(_AllTimeLeaderBaseSchema):
    dreb: int | None = pa.Field(nullable=True, ge=0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFg3ASchema(_AllTimeLeaderBaseSchema):
    fg3a: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFg3MSchema(_AllTimeLeaderBaseSchema):
    fg3m: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFg3PctSchema(_AllTimeLeaderBaseSchema):
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFgaSchema(_AllTimeLeaderBaseSchema):
    fga: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFgmSchema(_AllTimeLeaderBaseSchema):
    fgm: int | None = pa.Field(nullable=True, ge=0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFgPctSchema(_AllTimeLeaderBaseSchema):
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFtaSchema(_AllTimeLeaderBaseSchema):
    fta: int | None = pa.Field(nullable=True, ge=0)
    fta_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFtmSchema(_AllTimeLeaderBaseSchema):
    ftm: int | None = pa.Field(nullable=True, ge=0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeFtPctSchema(_AllTimeLeaderBaseSchema):
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeGpSchema(_AllTimeLeaderBaseSchema):
    gp: int | None = pa.Field(nullable=True, ge=0)
    gp_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeOrebSchema(_AllTimeLeaderBaseSchema):
    oreb: int | None = pa.Field(nullable=True, ge=0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimePfSchema(_AllTimeLeaderBaseSchema):
    pf: int | None = pa.Field(nullable=True, ge=0)
    pf_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimePtsSchema(_AllTimeLeaderBaseSchema):
    pts: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeRebSchema(_AllTimeLeaderBaseSchema):
    reb: int | None = pa.Field(nullable=True, ge=0)
    reb_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeStlSchema(_AllTimeLeaderBaseSchema):
    stl: int | None = pa.Field(nullable=True, ge=0)
    stl_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingAllTimeTovSchema(_AllTimeLeaderBaseSchema):
    tov: int | None = pa.Field(nullable=True, ge=0)
    tov_rank: int | None = pa.Field(nullable=True, ge=1)


class StagingLeagueLeadersSchema(_OpenStagingSchema):
    _provider_source_prefix = "LeagueLeaders.LeagueLeaders"
    _lossless_provider_columns = (
        "gp",
        "min",
        "fgm",
        "fga",
        "fg_pct",
        "fg3m",
        "fg3a",
        "fg3_pct",
        "ftm",
        "fta",
        "ft_pct",
        "oreb",
        "dreb",
        "reb",
        "ast",
        "stl",
        "blk",
        "tov",
        "pf",
        "eff",
        "ast_tov",
        "stl_tov",
    )

    player_id: int = pa.Field(gt=0)
    rank: int | None = pa.Field(nullable=True, ge=1)
    player: str | None = pa.Field(nullable=True)
    team: str | None = pa.Field(nullable=True)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class _RankedTeamBaseSchema(_OpenStagingSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)


class _RankedSeasonTeamBaseSchema(_RankedTeamBaseSchema):
    season_type: str | None = pa.Field(nullable=True)


class StagingAssistLeadersSchema(_RankedTeamBaseSchema):
    ast: float | None = pa.Field(nullable=True, ge=0.0)


class StagingAssistTrackerSchema(_OpenStagingSchema):
    assists: float | None = pa.Field(nullable=True, ge=0.0)


class StagingDunkScoreLeadersSchema(_OpenStagingSchema):
    _provider_source_prefix = "DunkScoreLeaders.Dunks"
    _lossless_provider_columns = (
        "game_id",
        "game_date",
        "matchup",
        "period",
        "game_clock_time",
        "event_num",
        "player_name",
        "first_name",
        "last_name",
        "team_id",
        "team_name",
        "team_city",
        "team_abbreviation",
        "jump_subscore",
        "power_subscore",
        "style_subscore",
        "defensive_contest_subscore",
        "max_ball_height",
        "ball_speed_through_rim",
        "player_vertical",
        "hang_time",
        "takeoff_distance",
        "reverse_dunk",
        "dunk_360",
        "through_the_legs",
        "alley_oop",
        "tip_in",
        "self_oop",
        "player_rotation",
        "player_lateral_speed",
        "ball_distance_traveled",
        "ball_reach_back",
        "total_ball_acceleration",
        "dunking_hand",
        "jumping_foot",
        "pass_length",
        "catching_hand",
        "catch_distance",
        "lateral_catch_distance",
        "passer_id",
        "passer_name",
        "passer_first_name",
        "passer_last_name",
        "pass_release_point",
        "shooter_id",
        "shooter_name",
        "shooter_first_name",
        "shooter_last_name",
        "shot_release_point",
        "shot_length",
        "defensive_contest_level",
        "possible_attempted_charge",
        "video_available",
    )

    player_id: int = pa.Field(gt=0)
    dunk_score: float | None = pa.Field(nullable=True, ge=0.0)


class StagingGravityLeadersSchema(_OpenStagingSchema):
    _provider_source_prefix = "GravityLeaders.leaders"
    _compact_provider_column_names = True
    _lossless_provider_columns = (
        "firstname",
        "lastname",
        "teamid",
        "teamabbreviation",
        "teamname",
        "teamcity",
        "frames",
        "avggravityscore",
        "onballperimeterframes",
        "onballperimetergravityscore",
        "avgonballperimetergravityscore",
        "offballperimeterframes",
        "offballperimetergravityscore",
        "avgoffballperimetergravityscore",
        "onballinteriorframes",
        "onballinteriorgravityscore",
        "avgonballinteriorgravityscore",
        "offballinteriorframes",
        "offballinteriorgravityscore",
        "avgoffballinteriorgravityscore",
        "gamesplayed",
        "minutes",
        "pts",
        "reb",
        "ast",
    )

    playerid: int = pa.Field(gt=0)
    gravityscore: float | None = pa.Field(nullable=True)


class StagingHomepageLeadersSchema(_RankedSeasonTeamBaseSchema):
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ts_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    pts_per48: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageLeadersLeagueAvgSchema(_OpenStagingSchema):
    season_type: str | None = pa.Field(nullable=True)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    efg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ts_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    pts_per48: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageLeadersLeagueMaxSchema(StagingHomepageLeadersLeagueAvgSchema):
    pass


class StagingHomepageV2Schema(_RankedSeasonTeamBaseSchema):
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageV2Stat2Schema(_RankedSeasonTeamBaseSchema):
    reb: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageV2Stat3Schema(_RankedSeasonTeamBaseSchema):
    ast: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageV2Stat4Schema(_RankedSeasonTeamBaseSchema):
    stl: float | None = pa.Field(nullable=True, ge=0.0)


class StagingHomepageV2Stat5Schema(_RankedSeasonTeamBaseSchema):
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingHomepageV2Stat6Schema(_RankedSeasonTeamBaseSchema):
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingHomepageV2Stat7Schema(_RankedSeasonTeamBaseSchema):
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingHomepageV2Stat8Schema(_RankedSeasonTeamBaseSchema):
    blk: float | None = pa.Field(nullable=True, ge=0.0)


class _TeamPacketBaseSchema(_OpenStagingSchema):
    team_id: int = pa.Field(gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)


class StagingLeadersTilesSchema(_TeamPacketBaseSchema):
    season_year: str | None = pa.Field(nullable=True)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class StagingLeadersTilesLastSeasonSchema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class StagingLeadersTilesMainSchema(StagingLeadersTilesLastSeasonSchema):
    pass


class StagingLeadersTilesLowSeasonSchema(_TeamPacketBaseSchema):
    season_year: str | None = pa.Field(nullable=True)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class StagingDefenseHubStat1Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)


class StagingDefenseHubStat10Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)


class StagingDefenseHubStat2Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    stl: float | None = pa.Field(nullable=True, ge=0.0)


class StagingDefenseHubStat3Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    blk: float | None = pa.Field(nullable=True, ge=0.0)


class StagingDefenseHubStat4Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    tm_def_rating: float | None = pa.Field(nullable=True)


class StagingDefenseHubStat5Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    overall_pm: float | None = pa.Field(nullable=True)


class StagingDefenseHubStat6Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    threep_dfgpct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingDefenseHubStat7Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    twop_dfgpct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingDefenseHubStat8Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=0)
    fifeteenf_dfgpct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingDefenseHubStat9Schema(_TeamPacketBaseSchema):
    rank: int | None = pa.Field(nullable=True, ge=1)
    def_rim_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingCumePlayerGameByGameSchema(_OpenStagingSchema):
    _provider_source_prefix = "CumeStatsPlayer.GameByGameStats"
    _lossless_provider_columns = (
        "gs",
        "actual_minutes",
        "actual_seconds",
        "fg",
        "fga",
        "fg_pct",
        "fg3",
        "fg3a",
        "fg3_pct",
        "ft",
        "fta",
        "ft_pct",
        "off_reb",
        "def_reb",
        "tot_reb",
        "avg_tot_reb",
        "ast",
        "pf",
        "dq",
        "stl",
        "turnovers",
        "blk",
        "pts",
        "avg_pts",
    )

    date_est: str | None = pa.Field(nullable=True)
    visitor_team: str | None = pa.Field(nullable=True)
    home_team: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumePlayerTotalsSchema(_OpenStagingSchema):
    _provider_source_prefix = "CumeStatsPlayer.TotalPlayerStats"
    _lossless_provider_columns = (
        "jersey_num",
        "gs",
        "actual_minutes",
        "actual_seconds",
        "fg",
        "fga",
        "fg_pct",
        "fg3",
        "fg3a",
        "fg3_pct",
        "ft",
        "fta",
        "ft_pct",
        "off_reb",
        "def_reb",
        "tot_reb",
        "ast",
        "pf",
        "dq",
        "stl",
        "turnovers",
        "blk",
        "pts",
        "max_actual_minutes",
        "max_actual_seconds",
        "max_reb",
        "max_ast",
        "max_stl",
        "max_turnovers",
        "max_blk",
        "max_pts",
        "avg_actual_minutes",
        "avg_actual_seconds",
        "avg_tot_reb",
        "avg_ast",
        "avg_stl",
        "avg_turnovers",
        "avg_blk",
        "avg_pts",
        "per_min_tot_reb",
        "per_min_ast",
        "per_min_stl",
        "per_min_turnovers",
        "per_min_blk",
        "per_min_pts",
    )

    display_fi_last: str | None = pa.Field(nullable=True)
    person_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumePlayerGamesSchema(_OpenStagingSchema):
    matchup: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field()


class StagingCumeTeamGameByGameSchema(_OpenStagingSchema):
    _provider_source_prefix = "CumeStatsTeam.GameByGameStats"
    _lossless_provider_columns = (
        "jersey_num",
        "gs",
        "actual_minutes",
        "actual_seconds",
        "fg",
        "fga",
        "fg_pct",
        "fg3",
        "fg3a",
        "fg3_pct",
        "ft",
        "fta",
        "ft_pct",
        "off_reb",
        "def_reb",
        "tot_reb",
        "ast",
        "pf",
        "dq",
        "stl",
        "turnovers",
        "blk",
        "pts",
        "max_actual_minutes",
        "max_actual_seconds",
        "max_reb",
        "max_ast",
        "max_stl",
        "max_turnovers",
        "max_blkp",
        "max_pts",
        "avg_actual_minutes",
        "avg_actual_seconds",
        "avg_reb",
        "avg_ast",
        "avg_stl",
        "avg_turnovers",
        "avg_blkp",
        "avg_pts",
        "per_min_reb",
        "per_min_ast",
        "per_min_stl",
        "per_min_turnovers",
        "per_min_blk",
        "per_min_pts",
    )

    player: str | None = pa.Field(nullable=True)
    person_id: int | None = pa.Field(nullable=True, gt=0)
    team_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumeTeamTotalsSchema(_OpenStagingSchema):
    _provider_source_prefix = "CumeStatsTeam.TotalTeamStats"
    _lossless_provider_columns = (
        "w",
        "l",
        "w_home",
        "l_home",
        "w_road",
        "l_road",
        "team_turnovers",
        "team_rebounds",
        "gs",
        "actual_minutes",
        "actual_seconds",
        "fg",
        "fga",
        "fg_pct",
        "fg3",
        "fg3a",
        "fg3_pct",
        "ft",
        "fta",
        "ft_pct",
        "off_reb",
        "def_reb",
        "tot_reb",
        "ast",
        "pf",
        "stl",
        "total_turnovers",
        "blk",
        "pts",
        "avg_reb",
        "avg_pts",
        "dq",
    )

    city: str | None = pa.Field(nullable=True)
    nickname: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumeTeamGamesSchema(_OpenStagingSchema):
    matchup: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field()


class StagingDraftBoardSchema(_OpenStagingSchema):
    _provider_source_prefix = "DraftBoard.DraftBoard"
    _lossless_provider_columns = (
        "round_number",
        "round_pick",
        "team_id",
        "team_city",
        "team_name",
        "team_abbreviation",
        "organization",
        "organization_type",
        "height",
        "weight",
        "position",
        "jersey_number",
        "birthdate",
        "age",
    )

    person_id: int = pa.Field(gt=0)
    player_name: str | None = pa.Field(nullable=True)
    season: int | None = pa.Field(nullable=True, ge=1946)
    overall_pick: int | None = pa.Field(nullable=True, ge=1)
