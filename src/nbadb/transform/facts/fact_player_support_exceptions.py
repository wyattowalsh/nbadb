from __future__ import annotations

from nbadb.transform.base import make_passthrough, make_union

FactPlayerIndexTransformer = make_passthrough("fact_player_index", "stg_player_index")
FactPlayerMatchupsPlayerInfoTransformer = make_union(
    "fact_player_matchups_player_info",
    "player_role",
    {
        "player": "stg_pvp_player_info",
        "vs_player": "stg_pvp_vs_player_info",
    },
)
