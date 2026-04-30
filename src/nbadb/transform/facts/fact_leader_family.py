from __future__ import annotations

from nbadb.transform.base import make_passthrough

FactLeagueLeadersTransformer = make_passthrough(
    "fact_league_leaders",
    "stg_league_leaders",
)
FactAssistLeadersTransformer = make_passthrough(
    "fact_assist_leaders",
    "stg_assist_leaders",
)
FactAssistTrackerTransformer = make_passthrough(
    "fact_assist_tracker",
    "stg_assist_tracker",
)
FactDunkScoreLeadersTransformer = make_passthrough(
    "fact_dunk_score_leaders",
    "stg_dunk_score_leaders",
)
FactGravityLeadersTransformer = make_passthrough(
    "fact_gravity_leaders",
    "stg_gravity_leaders",
)
