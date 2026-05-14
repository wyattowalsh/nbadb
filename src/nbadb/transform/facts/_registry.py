"""Factory-generated transforms (pilot batch).

Each module-level name is a concrete ``SqlTransformer`` subclass created via
:func:`~nbadb.transform.base.make_passthrough` or
:func:`~nbadb.transform.base.make_union`.  ``discover_all_transformers()``
picks them up automatically because they are ``BaseTransformer`` subclasses
living inside the ``nbadb.transform.facts`` package.
"""

from __future__ import annotations

from nbadb.transform.base import make_passthrough, make_union

# ---------------------------------------------------------------------------
# Passthrough transforms
# ---------------------------------------------------------------------------
FactTeamRetiredTransformer = make_passthrough("fact_team_retired", "stg_team_retired")
FactTeamHofTransformer = make_passthrough("fact_team_hof", "stg_team_hof")
FactTeamSocialSitesTransformer = make_passthrough("fact_team_social_sites", "stg_team_social_sites")
FactTeamAwardsConfTransformer = make_passthrough("fact_team_awards_conf", "stg_team_awards_conf")
FactTeamAwardsDivTransformer = make_passthrough("fact_team_awards_div", "stg_team_awards_div")
FactTeamAwardsChampionshipsTransformer = make_passthrough(
    "fact_team_awards_championships", "stg_team_awards_championships"
)
FactScoreboardAvailableTransformer = make_passthrough(
    "fact_scoreboard_available", "stg_scoreboard_available"
)

# ---------------------------------------------------------------------------
# Union transforms
# ---------------------------------------------------------------------------
FactHustleAvailabilityTransformer = make_union(
    "fact_hustle_availability",
    "hustle_type",
    {"availability": "stg_hustle_stats_available", "box_score": "stg_box_score_hustle_box"},
)
FactDraftHistoryTransformer = make_passthrough("fact_draft_history", "stg_draft")
FactDraftCombineStatsTransformer = make_passthrough(
    "fact_draft_combine_stats",
    "stg_draft_combine",
)
FactDraftCombineDrillResultsTransformer = make_passthrough(
    "fact_draft_combine_drill_results",
    "stg_draft_combine_drills",
)
FactDraftCombineNonStationaryShootingTransformer = make_passthrough(
    "fact_draft_combine_non_stationary_shooting",
    "stg_draft_combine_nonstat_shooting",
)
FactDraftCombinePlayerAnthroTransformer = make_passthrough(
    "fact_draft_combine_player_anthro",
    "stg_draft_combine_anthro",
)
FactDraftCombineSpotShootingTransformer = make_passthrough(
    "fact_draft_combine_spot_shooting",
    "stg_draft_combine_spot_shooting",
)
FactLineupStatsTransformer = make_union(
    "fact_lineup_stats",
    "lineup_source",
    {"league": "stg_lineup", "team": "stg_team_lineups"},
)
FactFranchiseDetailTransformer = make_union(
    "fact_franchise_detail",
    "detail_type",
    {"leaders": "stg_franchise_leaders", "players": "stg_franchise_players"},
)
FactFranchiseLeadersTransformer = make_passthrough(
    "fact_franchise_leaders",
    "stg_franchise_leaders",
)
FactFranchisePlayersTransformer = make_passthrough(
    "fact_franchise_players",
    "stg_franchise_players",
)
FactPlayerSeasonRanksTransformer = make_union(
    "fact_player_season_ranks",
    "rank_type",
    {
        "regular": "stg_player_season_ranks_regular",
        "postseason": "stg_player_season_ranks_postseason",
    },
)
FactPlayerYoyDetailTransformer = make_union(
    "fact_player_yoy_detail",
    "yoy_type",
    {"by_year": "stg_player_yoy_by_year", "overall": "stg_player_yoy_overall"},
)
