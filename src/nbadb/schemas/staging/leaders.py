from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class _OpenStagingSchema(BaseSchema):
    """Preserve endpoint-specific passthrough columns for leaderboard packets."""

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
    player_id: int = pa.Field(gt=0)
    dunk_score: float | None = pa.Field(nullable=True, ge=0.0)


class StagingGravityLeadersSchema(_OpenStagingSchema):
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
    date_est: str | None = pa.Field(nullable=True)
    visitor_team: str | None = pa.Field(nullable=True)
    home_team: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumePlayerTotalsSchema(_OpenStagingSchema):
    display_fi_last: str | None = pa.Field(nullable=True)
    person_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumePlayerGamesSchema(_OpenStagingSchema):
    matchup: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field()


class StagingCumeTeamGameByGameSchema(_OpenStagingSchema):
    player: str | None = pa.Field(nullable=True)
    person_id: int | None = pa.Field(nullable=True, gt=0)
    team_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumeTeamTotalsSchema(_OpenStagingSchema):
    city: str | None = pa.Field(nullable=True)
    nickname: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0)
    gp: int | None = pa.Field(nullable=True, ge=0)


class StagingCumeTeamGamesSchema(_OpenStagingSchema):
    matchup: str | None = pa.Field(nullable=True)
    game_id: str = pa.Field()


class StagingDraftBoardSchema(_OpenStagingSchema):
    person_id: int = pa.Field(gt=0)
    player_name: str | None = pa.Field(nullable=True)
    season: int | None = pa.Field(nullable=True, ge=1946)
    overall_pick: int | None = pa.Field(nullable=True, ge=1)
