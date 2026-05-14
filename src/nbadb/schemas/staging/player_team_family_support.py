from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas._player_dashboard_common import (
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardReferenceMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
)
from nbadb.schemas.base import BaseSchema
from nbadb.schemas.star.fact_team_dashboard import (
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardReferenceMixin,
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
)


class StagingPlayerAvailableSeasonsSchema(BaseSchema):
    season_id: str = pa.Field(
        nullable=False,
        metadata={
            "source": ("CommonPlayerInfo.AvailableSeasons.SEASON_ID"),
            "description": "Available season identifier",
        },
    )


class StagingPlayerHeadlineStatsSchema(BaseSchema):
    player_id: int = pa.Field(
        gt=0,
        nullable=False,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.PLAYER_ID"),
            "description": "Unique player identifier",
        },
    )
    player_name: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.PLAYER_NAME"),
            "description": "Player display name",
        },
    )
    time_frame: str | None = pa.Field(
        nullable=True,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.TimeFrame"),
            "description": "Headline-stat timeframe label",
        },
    )
    pts: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.PTS"),
            "description": "Points per game",
        },
    )
    ast: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.AST"),
            "description": "Assists per game",
        },
    )
    reb: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.REB"),
            "description": "Rebounds per game",
        },
    )
    pie: float | None = pa.Field(
        nullable=True,
        ge=0.0,
        metadata={
            "source": ("CommonPlayerInfo.PlayerHeadlineStats.PIE"),
            "description": "Player impact estimate",
        },
    )


class _FantasyCoreMixin(BaseSchema):
    player_id: int = pa.Field(gt=0, nullable=False)
    player_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    fan_duel_pts: float | None = pa.Field(nullable=True, ge=0.0)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)


class StagingFantasyWidgetSchema(_FantasyCoreMixin, BaseSchema):
    player_position: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    season_type: str = pa.Field(
        nullable=False,
        metadata={"description": "Injected season type used for the widget query"},
    )


class StagingPlayerFantasyProfileLastFiveGamesAvgSchema(_FantasyCoreMixin, BaseSchema):
    pass


class StagingPlayerFantasyProfileSeasonAvgSchema(_FantasyCoreMixin, BaseSchema):
    pass


class StagingFanduelPlayerSchema(_FantasyCoreMixin, BaseSchema):
    team_name: str | None = pa.Field(nullable=True)
    jersey_num: str | None = pa.Field(nullable=True)
    player_position: str | None = pa.Field(nullable=True)
    location: str | None = pa.Field(nullable=True)
    usg_pct: float | None = pa.Field(nullable=True, ge=0.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)


class StagingDefunctTeamsSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_city: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    start_year: int | None = pa.Field(nullable=True, gt=0)
    end_year: int | None = pa.Field(nullable=True, gt=0)
    years: int | None = pa.Field(nullable=True, ge=0)
    games: int | None = pa.Field(nullable=True, ge=0)
    wins: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0)
    win_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    po_appearances: int | None = pa.Field(nullable=True, ge=0)
    div_titles: int | None = pa.Field(nullable=True, ge=0)
    conf_titles: int | None = pa.Field(nullable=True, ge=0)
    league_titles: int | None = pa.Field(nullable=True, ge=0)


class StagingFranchiseLeadersSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    pts_person_id: int | None = pa.Field(nullable=True, gt=0)
    pts_player: str | None = pa.Field(nullable=True)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    ast_person_id: int | None = pa.Field(nullable=True, gt=0)
    ast_player: str | None = pa.Field(nullable=True)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    reb_person_id: int | None = pa.Field(nullable=True, gt=0)
    reb_player: str | None = pa.Field(nullable=True)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blk_person_id: int | None = pa.Field(nullable=True, gt=0)
    blk_player: str | None = pa.Field(nullable=True)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    stl_person_id: int | None = pa.Field(nullable=True, gt=0)
    stl_player: str | None = pa.Field(nullable=True)


class StagingFranchisePlayersSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team: str | None = pa.Field(nullable=True)
    person_id: int | None = pa.Field(nullable=True, gt=0)
    player: str | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)
    active_with_team: int | None = pa.Field(nullable=True, isin=[0, 1])
    gp: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)


class StagingGlAlumBoxScoreSimilarityScoreSchema(BaseSchema):
    person_2_id: int = pa.Field(gt=0, nullable=False)
    person_2: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    similarity_score: float | None = pa.Field(nullable=True)


class StagingHustleStatsAvailableSchema(BaseSchema):
    game_id: str = pa.Field(nullable=False)
    hustle_status: str | None = pa.Field(nullable=True)


class StagingBoxScoreHustleBoxSchema(BaseSchema):
    game_id: str = pa.Field(nullable=False)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_city: str | None = pa.Field(nullable=True)
    player_id: int = pa.Field(gt=0, nullable=False)
    player_name: str | None = pa.Field(nullable=True)
    start_position: str | None = pa.Field(nullable=True)
    comment: str | None = pa.Field(nullable=True)
    minutes: str | None = pa.Field(nullable=True)
    pts: int | None = pa.Field(nullable=True, ge=0)
    contested_shots: int | None = pa.Field(nullable=True, ge=0)
    contested_shots_2pt: int | None = pa.Field(nullable=True, ge=0)
    contested_shots_3pt: int | None = pa.Field(nullable=True, ge=0)
    deflections: int | None = pa.Field(nullable=True, ge=0)
    charges_drawn: int | None = pa.Field(nullable=True, ge=0)
    screen_assists: int | None = pa.Field(nullable=True, ge=0)
    screen_ast_pts: int | None = pa.Field(nullable=True, ge=0)
    off_loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    def_loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    off_boxouts: int | None = pa.Field(nullable=True, ge=0)
    def_boxouts: int | None = pa.Field(nullable=True, ge=0)
    box_out_player_team_rebs: int | None = pa.Field(nullable=True, ge=0)
    box_out_player_rebs: int | None = pa.Field(nullable=True, ge=0)
    box_outs: int | None = pa.Field(nullable=True, ge=0)


class StagingBoxScoreHustleTeamSchema(BaseSchema):
    game_id: str = pa.Field(nullable=False)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_name: str | None = pa.Field(nullable=True)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_city: str | None = pa.Field(nullable=True)
    minutes: str | None = pa.Field(nullable=True)
    pts: int | None = pa.Field(nullable=True, ge=0)
    contested_shots: int | None = pa.Field(nullable=True, ge=0)
    contested_shots_2pt: int | None = pa.Field(nullable=True, ge=0)
    contested_shots_3pt: int | None = pa.Field(nullable=True, ge=0)
    deflections: int | None = pa.Field(nullable=True, ge=0)
    charges_drawn: int | None = pa.Field(nullable=True, ge=0)
    screen_assists: int | None = pa.Field(nullable=True, ge=0)
    screen_ast_pts: int | None = pa.Field(nullable=True, ge=0)
    off_loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    def_loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    loose_balls_recovered: int | None = pa.Field(nullable=True, ge=0)
    off_boxouts: int | None = pa.Field(nullable=True, ge=0)
    def_boxouts: int | None = pa.Field(nullable=True, ge=0)
    box_out_player_team_rebs: int | None = pa.Field(nullable=True, ge=0)
    box_out_player_rebs: int | None = pa.Field(nullable=True, ge=0)
    box_outs: int | None = pa.Field(nullable=True, ge=0)


class StagingLineupSchema(BaseSchema):
    group_set: str = pa.Field(nullable=False)
    group_id: str = pa.Field(nullable=False)
    group_name: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0, nullable=False)
    team_abbreviation: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: int | None = pa.Field(nullable=True, ge=0)
    fga: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: int | None = pa.Field(nullable=True, ge=0)
    fg3a: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: int | None = pa.Field(nullable=True, ge=0)
    fta: int | None = pa.Field(nullable=True, ge=0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: int | None = pa.Field(nullable=True, ge=0)
    dreb: int | None = pa.Field(nullable=True, ge=0)
    reb: int | None = pa.Field(nullable=True, ge=0)
    ast: int | None = pa.Field(nullable=True, ge=0)
    tov: int | None = pa.Field(nullable=True, ge=0)
    stl: int | None = pa.Field(nullable=True, ge=0)
    blk: int | None = pa.Field(nullable=True, ge=0)
    blka: int | None = pa.Field(nullable=True, ge=0)
    pf: int | None = pa.Field(nullable=True, ge=0)
    pfd: int | None = pa.Field(nullable=True, ge=0)
    pts: int | None = pa.Field(nullable=True, ge=0)
    plus_minus: float | None = pa.Field(nullable=True)
    gp_rank: int | None = pa.Field(nullable=True, ge=0)
    w_rank: int | None = pa.Field(nullable=True, ge=0)
    l_rank: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    min_rank: int | None = pa.Field(nullable=True, ge=0)
    fgm_rank: int | None = pa.Field(nullable=True, ge=0)
    fga_rank: int | None = pa.Field(nullable=True, ge=0)
    fg_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3m_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3a_rank: int | None = pa.Field(nullable=True, ge=0)
    fg3_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    ftm_rank: int | None = pa.Field(nullable=True, ge=0)
    fta_rank: int | None = pa.Field(nullable=True, ge=0)
    ft_pct_rank: int | None = pa.Field(nullable=True, ge=0)
    oreb_rank: int | None = pa.Field(nullable=True, ge=0)
    dreb_rank: int | None = pa.Field(nullable=True, ge=0)
    reb_rank: int | None = pa.Field(nullable=True, ge=0)
    ast_rank: int | None = pa.Field(nullable=True, ge=0)
    tov_rank: int | None = pa.Field(nullable=True, ge=0)
    stl_rank: int | None = pa.Field(nullable=True, ge=0)
    blk_rank: int | None = pa.Field(nullable=True, ge=0)
    blka_rank: int | None = pa.Field(nullable=True, ge=0)
    pf_rank: int | None = pa.Field(nullable=True, ge=0)
    pfd_rank: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int | None = pa.Field(nullable=True, ge=0)
    plus_minus_rank: int | None = pa.Field(nullable=True, ge=0)
    season_year: str = pa.Field(nullable=False)


class _PlayerDashboardLastnDetailSchema(
    _PlayerDashboardContextMixin,
    _PlayerDashboardGroupingMixin,
    _PlayerDashboardStandardMetricsMixin,
    _PlayerDashboardStandardRanksMixin,
    _PlayerDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingPlayerLastnGameNumberSchema(_PlayerDashboardLastnDetailSchema):
    pass


class StagingPlayerLastnLast10Schema(_PlayerDashboardLastnDetailSchema):
    pass


class StagingPlayerLastnLast15Schema(_PlayerDashboardLastnDetailSchema):
    pass


class StagingPlayerLastnLast20Schema(_PlayerDashboardLastnDetailSchema):
    pass


class StagingPlayerLastnLast5Schema(_PlayerDashboardLastnDetailSchema):
    pass


class StagingPlayerLastnOverallSchema(_PlayerDashboardLastnDetailSchema):
    pass


class _TeamDashboardSeasonYearMixin(BaseSchema):
    season_year: str = pa.Field(nullable=False)


class _TeamDashboardSeasonYearNullableMixin(BaseSchema):
    season_year: str | None = pa.Field(nullable=True)


class _TeamDashboardDaysRestMixin(BaseSchema):
    team_days_rest_range: str | None = pa.Field(nullable=True)


class _TeamDashboardLocationMixin(BaseSchema):
    team_game_location: str | None = pa.Field(nullable=True)


class _TeamDashboardMonthMixin(BaseSchema):
    season_month_name: str | None = pa.Field(nullable=True)


class _TeamDashboardSegmentMixin(BaseSchema):
    season_segment: str | None = pa.Field(nullable=True)


class _TeamDashboardResultMixin(BaseSchema):
    game_result: str | None = pa.Field(nullable=True)


class _TeamDashboardPlayerIdentityMixin(BaseSchema):
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)


class StagingTeamDashGeneralSplitsSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardSeasonYearMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    team_days_rest_range: str | None = pa.Field(nullable=True)


class StagingTeamSplitDaysRestSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardDaysRestMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamSplitLocationSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardLocationMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamSplitMonthSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardMonthMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamSplitGeneralOverallSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardSeasonYearMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamSplitPrePostAllstarSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardSegmentMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamSplitWinsLossesSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardResultMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamDashShootingSplitsSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    player_id: int | None = pa.Field(nullable=True, gt=0)
    player_name: str | None = pa.Field(nullable=True)


class StagingTeamShootAssistedBySchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardPlayerIdentityMixin,
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    group_set: str = pa.Field(nullable=False)


class StagingTeamShootAssistedShotSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    pass


class StagingTeamShootOverallSchema(StagingTeamDashShootingSplitsSchema):
    pass


class StagingTeamShoot5FtSchema(StagingTeamDashShootingSplitsSchema):
    pass


class StagingTeamShoot8FtSchema(StagingTeamDashShootingSplitsSchema):
    pass


class StagingTeamShootAreaSchema(StagingTeamDashShootingSplitsSchema):
    pass


class StagingTeamShootTypeSchema(StagingTeamDashShootingSplitsSchema):
    pass
