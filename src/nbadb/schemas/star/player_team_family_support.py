from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.staging.league_stats import (
    StagingLeagueDashTeamStatsSchema,
)
from nbadb.schemas.staging.player_dashboard import (
    StagingPlayerDashboardClutchSchema,
    StagingPlayerDashboardGameSplitsSchema,
    StagingPlayerDashboardGeneralSplitsSchema,
    StagingPlayerDashboardLastNGamesSchema,
    StagingPlayerDashboardYearOverYearSchema,
    StagingPlayerPerfPtsScoredSchema,
)
from nbadb.schemas.staging.player_team_family_support import (
    StagingBoxScoreHustleTeamSchema,
    StagingFranchiseLeadersSchema,
    StagingFranchisePlayersSchema,
    StagingGlAlumBoxScoreSimilarityScoreSchema,
    StagingPlayerAvailableSeasonsSchema,
    StagingPlayerHeadlineStatsSchema,
    _TeamDashboardDaysRestMixin,
    _TeamDashboardLocationMixin,
    _TeamDashboardMonthMixin,
    _TeamDashboardPlayerIdentityMixin,
    _TeamDashboardResultMixin,
    _TeamDashboardSeasonYearNullableMixin,
    _TeamDashboardSegmentMixin,
)
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


class FactPlayerAvailableSeasonsSchema(StagingPlayerAvailableSeasonsSchema):
    pass


class FactPlayerHeadlineStatsSchema(StagingPlayerHeadlineStatsSchema):
    pass


class FactGlAlumSimilaritySchema(StagingGlAlumBoxScoreSimilarityScoreSchema):
    pass


class FactLeagueDashTeamStatsSchema(StagingLeagueDashTeamStatsSchema):
    pass


class FactTeamGameHustleSchema(StagingBoxScoreHustleTeamSchema):
    pass


class FactFantasySchema(BaseSchema):
    player_id: int = pa.Field(gt=0, nullable=False)
    player_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_name: str | None = pa.Field(nullable=True)
    team_abbreviation: str | None = pa.Field(nullable=True)
    jersey_num: str | None = pa.Field(nullable=True)
    player_position: str | None = pa.Field(nullable=True)
    location: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fan_duel_pts: float | None = pa.Field(nullable=True, ge=0.0)
    nba_fantasy_pts: float | None = pa.Field(nullable=True, ge=0.0)
    usg_pct: float | None = pa.Field(nullable=True, ge=0.0)
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
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    blka: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pfd: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    plus_minus: float | None = pa.Field(nullable=True)
    season_type: str | None = pa.Field(nullable=True)
    fantasy_source: str = pa.Field(
        nullable=False,
        isin=[
            "infographic_fanduel_player",
            "fantasy_widget",
            "player_fantasy_profile_last_five_games_avg",
            "player_fantasy_profile_season_avg",
        ],
    )


class FactFranchiseDetailSchema(BaseSchema):
    team_id: int = pa.Field(gt=0, nullable=False)
    league_id: str | None = pa.Field(nullable=True)
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
    pts_person_id: int | None = pa.Field(nullable=True, gt=0)
    pts_player: str | None = pa.Field(nullable=True)
    ast_person_id: int | None = pa.Field(nullable=True, gt=0)
    ast_player: str | None = pa.Field(nullable=True)
    reb_person_id: int | None = pa.Field(nullable=True, gt=0)
    reb_player: str | None = pa.Field(nullable=True)
    blk_person_id: int | None = pa.Field(nullable=True, gt=0)
    blk_player: str | None = pa.Field(nullable=True)
    stl_person_id: int | None = pa.Field(nullable=True, gt=0)
    stl_player: str | None = pa.Field(nullable=True)
    detail_type: str = pa.Field(nullable=False, isin=["leaders", "players"])


class FactFranchiseLeadersSchema(StagingFranchiseLeadersSchema):
    pass


class FactFranchisePlayersSchema(StagingFranchisePlayersSchema):
    pass


class FactHustleAvailabilitySchema(BaseSchema):
    game_id: str = pa.Field(nullable=False)
    hustle_status: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_city: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
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
    hustle_type: str = pa.Field(nullable=False, isin=["availability", "box_score"])


class FactPlayerClutchDetailSchema(StagingPlayerDashboardClutchSchema):
    clutch_window: str = pa.Field(nullable=False)


class FactPlayerGameSplitsDetailSchema(StagingPlayerDashboardGameSplitsSchema):
    split_type: str = pa.Field(nullable=False)


class FactPlayerGeneralSplitsDetailSchema(StagingPlayerDashboardGeneralSplitsSchema):
    split_type: str = pa.Field(nullable=False)


class FactPlayerLastNDetailSchema(StagingPlayerDashboardLastNGamesSchema):
    window_size: str = pa.Field(nullable=False)


class FactPlayerTeamPerfDetailSchema(StagingPlayerPerfPtsScoredSchema):
    perf_context: str = pa.Field(nullable=False)


class FactPlayerYoyDetailSchema(StagingPlayerDashboardYearOverYearSchema):
    yoy_type: str = pa.Field(nullable=False)


class FactTeamGeneralSplitsDetailSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardSeasonYearNullableMixin,
    _TeamDashboardDaysRestMixin,
    _TeamDashboardLocationMixin,
    _TeamDashboardMonthMixin,
    _TeamDashboardSegmentMixin,
    _TeamDashboardResultMixin,
    _TeamDashboardStandardMetricsMixin,
    _TeamDashboardStandardRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    split_type: str = pa.Field(nullable=False)


class FactTeamShootingSplitsDetailSchema(
    _TeamDashboardSeasonTypeMixin,
    _TeamDashboardGroupingMixin,
    _TeamDashboardPlayerIdentityMixin,
    _TeamDashboardFieldGoalMetricsMixin,
    _TeamDashboardShootingExtensionsMixin,
    _TeamDashboardFieldGoalRanksMixin,
    _TeamDashboardShootingExtensionRanksMixin,
    _TeamDashboardReferenceMixin,
    BaseSchema,
):
    shooting_split: str = pa.Field(nullable=False)


derived_output_schema()(FactPlayerAvailableSeasonsSchema)
derived_output_schema()(FactPlayerHeadlineStatsSchema)
derived_output_schema()(FactGlAlumSimilaritySchema)
derived_output_schema()(FactLeagueDashTeamStatsSchema)
derived_output_schema()(FactTeamGameHustleSchema)
derived_output_schema(literal_fields={"fantasy_source"})(FactFantasySchema)
derived_output_schema(literal_fields={"detail_type"})(FactFranchiseDetailSchema)
derived_output_schema()(FactFranchiseLeadersSchema)
derived_output_schema()(FactFranchisePlayersSchema)
derived_output_schema(literal_fields={"hustle_type"})(FactHustleAvailabilitySchema)
derived_output_schema(literal_fields={"clutch_window"})(FactPlayerClutchDetailSchema)
derived_output_schema(literal_fields={"split_type"})(FactPlayerGameSplitsDetailSchema)
derived_output_schema(literal_fields={"split_type"})(FactPlayerGeneralSplitsDetailSchema)
derived_output_schema(literal_fields={"window_size"})(FactPlayerLastNDetailSchema)
derived_output_schema(literal_fields={"perf_context"})(FactPlayerTeamPerfDetailSchema)
derived_output_schema(literal_fields={"yoy_type"})(FactPlayerYoyDetailSchema)
derived_output_schema(literal_fields={"split_type"})(FactTeamGeneralSplitsDetailSchema)
derived_output_schema(literal_fields={"shooting_split"})(FactTeamShootingSplitsDetailSchema)
