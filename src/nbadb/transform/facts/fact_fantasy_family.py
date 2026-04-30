from __future__ import annotations

from nbadb.transform.base import make_passthrough

FactFantasyWidgetTransformer = make_passthrough(
    "fact_fantasy_widget",
    "stg_fantasy_widget",
)
FactInfographicFanduelPlayerTransformer = make_passthrough(
    "fact_infographic_fanduel_player",
    "stg_fanduel_player",
)
FactPlayerFantasyProfileLastFiveGamesAvgTransformer = make_passthrough(
    "fact_player_fantasy_profile_last_five_games_avg",
    "stg_player_fantasy_profile_last_five_games_avg",
)
FactPlayerFantasyProfileSeasonAvgTransformer = make_passthrough(
    "fact_player_fantasy_profile_season_avg",
    "stg_player_fantasy_profile_season_avg",
)
