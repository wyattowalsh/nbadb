from __future__ import annotations

from nbadb.schemas.star.bridge_game_official import BridgeGameOfficialSchema
from nbadb.schemas.star.bridge_play_player import BridgePlayPlayerSchema
from nbadb.schemas.star.dim_arena import DimArenaSchema
from nbadb.schemas.star.dim_coach import DimCoachSchema
from nbadb.schemas.star.dim_college import DimCollegeSchema
from nbadb.schemas.star.dim_date import DimDateSchema
from nbadb.schemas.star.dim_game import DimGameSchema
from nbadb.schemas.star.dim_official import DimOfficialSchema
from nbadb.schemas.star.dim_play_event_type import DimPlayEventTypeSchema
from nbadb.schemas.star.dim_player import DimPlayerSchema
from nbadb.schemas.star.dim_season import DimSeasonSchema
from nbadb.schemas.star.dim_season_phase import DimSeasonPhaseSchema
from nbadb.schemas.star.dim_shot_zone import DimShotZoneSchema
from nbadb.schemas.star.dim_team import DimTeamSchema
from nbadb.schemas.star.dim_team_history import DimTeamHistorySchema
from nbadb.schemas.star.fact_draft import FactDraftSchema
from nbadb.schemas.star.fact_estimated_metrics import (
    FactPlayerEstimatedMetricsSchema,
    FactTeamEstimatedMetricsSchema,
)
from nbadb.schemas.star.fact_game_result import FactGameResultSchema
from nbadb.schemas.star.fact_game_scoring import FactGameScoringSchema
from nbadb.schemas.star.fact_lineup_stats import FactLineupStatsSchema
from nbadb.schemas.star.fact_matchup import FactMatchupSchema
from nbadb.schemas.star.fact_play_by_play import FactPlayByPlaySchema
from nbadb.schemas.star.fact_player_awards import FactPlayerAwardsSchema
from nbadb.schemas.star.fact_player_game_advanced import FactPlayerGameAdvancedSchema
from nbadb.schemas.star.fact_player_game_hustle import FactPlayerGameHustleSchema
from nbadb.schemas.star.fact_player_game_misc import FactPlayerGameMiscSchema
from nbadb.schemas.star.fact_player_game_tracking import FactPlayerGameTrackingSchema
from nbadb.schemas.star.fact_player_game_traditional import FactPlayerGameTraditionalSchema
from nbadb.schemas.star.fact_rotation import FactRotationSchema
from nbadb.schemas.star.fact_shot_chart import FactShotChartSchema
from nbadb.schemas.star.fact_standings import FactStandingsSchema
from nbadb.schemas.star.fact_synergy import FactSynergySchema
from nbadb.schemas.star.fact_team_game import FactTeamGameSchema
from nbadb.schemas.star.fact_tracking_defense import FactTrackingDefenseSchema
from nbadb.schemas.star.fact_win_probability import FactWinProbabilitySchema

__all__ = [
    "BridgeGameOfficialSchema",
    "BridgePlayPlayerSchema",
    "DimArenaSchema",
    "DimCoachSchema",
    "DimCollegeSchema",
    "DimDateSchema",
    "DimGameSchema",
    "DimOfficialSchema",
    "DimPlayEventTypeSchema",
    "DimPlayerSchema",
    "DimSeasonSchema",
    "DimSeasonPhaseSchema",
    "DimShotZoneSchema",
    "DimTeamSchema",
    "DimTeamHistorySchema",
    "FactDraftSchema",
    "FactPlayerEstimatedMetricsSchema",
    "FactTeamEstimatedMetricsSchema",
    "FactGameResultSchema",
    "FactGameScoringSchema",
    "FactLineupStatsSchema",
    "FactMatchupSchema",
    "FactPlayByPlaySchema",
    "FactPlayerAwardsSchema",
    "FactPlayerGameAdvancedSchema",
    "FactPlayerGameHustleSchema",
    "FactPlayerGameMiscSchema",
    "FactPlayerGameTrackingSchema",
    "FactPlayerGameTraditionalSchema",
    "FactRotationSchema",
    "FactShotChartSchema",
    "FactStandingsSchema",
    "FactSynergySchema",
    "FactTeamGameSchema",
    "FactTrackingDefenseSchema",
    "FactWinProbabilitySchema",
]
