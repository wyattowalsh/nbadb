"""Default consumer metadata inference for star-schema agent export."""

from __future__ import annotations

from typing import Any

_SCD2_TABLES = frozenset({"dim_player", "dim_team_history"})
_SCD2_NOTE = "Filter is_current = TRUE when joining for present-day identity."

_ANALYTICS_METADATA: dict[str, dict[str, Any]] = {
    "analytics_clutch_performance": {
        "grain": "player-season-clutch",
        "agent_intents": ["clutch", "clutch_performance"],
    },
    "analytics_draft_value": {
        "grain": "draft-pick",
        "agent_intents": ["draft", "draft_value"],
    },
    "analytics_game_summary": {
        "grain": "game",
        "agent_intents": ["game_summary"],
    },
    "analytics_head_to_head": {
        "grain": "team-opponent-season",
        "agent_intents": ["head_to_head", "h2h"],
    },
    "analytics_league_benchmarks": {
        "grain": "league-season",
        "agent_intents": ["league_benchmarks"],
    },
    "analytics_player_game_complete": {
        "grain": "player-game",
        "agent_intents": ["player_game_log", "game_log"],
    },
    "analytics_player_general_splits": {
        "grain": "player-split",
        "agent_intents": ["player_splits"],
    },
    "analytics_player_impact": {
        "grain": "player-season",
        "agent_intents": ["player_impact"],
    },
    "analytics_player_matchup": {
        "grain": "player-vs-player-season",
        "agent_intents": ["matchups", "player_matchups"],
    },
    "analytics_player_season_complete": {
        "grain": "player-season",
        "agent_intents": ["player_season", "player_season_complete"],
    },
    "analytics_shooting_efficiency": {
        "grain": "player-season-shot-profile",
        "agent_intents": ["shot_chart", "shooting_efficiency"],
    },
    "analytics_team_game_complete": {
        "grain": "team-game",
        "agent_intents": ["team_game_log"],
    },
    "analytics_team_general_splits": {
        "grain": "team-split",
        "agent_intents": ["team_splits"],
    },
    "analytics_team_season_summary": {
        "grain": "team-season",
        "agent_intents": ["team_season"],
    },
}

_AGG_METADATA: dict[str, dict[str, Any]] = {
    "agg_player_season": {
        "grain": "player-season",
        "agent_intents": ["scoring", "assists", "rebounds", "player_season"],
    },
    "agg_clutch_stats": {
        "grain": "player-season-clutch",
        "agent_intents": ["clutch"],
    },
    "agg_team_pace_and_efficiency": {
        "grain": "team-season",
        "agent_intents": ["pace", "team_pace"],
    },
    "agg_team_franchise": {
        "grain": "franchise",
        "agent_intents": ["franchise_history", "championships"],
    },
    "agg_team_season": {
        "grain": "team-season",
        "agent_intents": ["team_season"],
    },
    "agg_all_time_leaders": {
        "grain": "player-career",
        "agent_intents": ["all_time_leaders"],
    },
    "agg_league_leaders": {
        "grain": "league-season",
        "agent_intents": ["league_leaders"],
    },
    "agg_player_career": {
        "grain": "player-career",
        "agent_intents": ["player_career"],
    },
    "agg_shot_location_season": {
        "grain": "player-season-shot-zone",
        "agent_intents": ["shot_chart", "shot_locations"],
    },
}

_DIM_JOIN_HINTS: dict[str, str] = {
    "dim_player": "Join on player_id with is_current = TRUE for current names.",
    "dim_team_history": "Join on team_id with is_current = TRUE for current team identity.",
    "dim_all_players": "Type-1 player lookup; prefer dim_player for SCD2-aware joins.",
}


def _dim_grain(table_name: str) -> str:
    if table_name in _SCD2_TABLES:
        return "dimension-scd2"
    return "dimension-type1"


def _dim_intents(table_name: str) -> list[str]:
    stem = table_name.removeprefix("dim_")
    return [stem.replace("_", "-"), "dimension_lookup"]


def _fact_grain(table_name: str) -> str:
    if "game" in table_name:
        return "fact-game"
    if "season" in table_name:
        return "fact-season"
    if "player" in table_name:
        return "fact-player"
    if "team" in table_name:
        return "fact-team"
    return "fact-event"


def _fact_intents(table_name: str) -> list[str]:
    stem = table_name.removeprefix("fact_")
    return [stem.replace("_", "-")]


def _merge_metadata(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = dict(base)
    for key, value in override.items():
        if key == "agent_intents":
            existing = list(merged.get("agent_intents", ()))
            incoming = list(value) if isinstance(value, list | tuple) else [str(value)]
            merged["agent_intents"] = tuple(dict.fromkeys([*existing, *incoming]))
            continue
        if key == "join_hints" and isinstance(value, dict):
            hints = dict(merged.get("join_hints", {}) or {})
            hints.update(value)
            merged["join_hints"] = hints
            continue
        if value not in (None, "", (), {}):
            merged[key] = value
    return merged


def infer_consumer_metadata(
    table_name: str,
    *,
    schema_doc: str = "",
    explicit: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return merged explicit and inferred consumer metadata for a star table."""
    inferred: dict[str, Any] = {}

    if table_name in _ANALYTICS_METADATA:
        inferred.update(_ANALYTICS_METADATA[table_name])
    elif table_name in _AGG_METADATA:
        inferred.update(_AGG_METADATA[table_name])
    elif table_name.startswith("dim_"):
        inferred["grain"] = _dim_grain(table_name)
        inferred["agent_intents"] = _dim_intents(table_name)
        if table_name in _DIM_JOIN_HINTS:
            inferred["join_hints"] = {table_name: _DIM_JOIN_HINTS[table_name]}
    elif table_name.startswith("fact_"):
        inferred["grain"] = _fact_grain(table_name)
        inferred["agent_intents"] = _fact_intents(table_name)
        if table_name == "fact_standings":
            inferred["agent_intents"] = ("standings", "team_standings")
        if table_name == "fact_shot_chart":
            inferred["agent_intents"] = ("shot_chart", "shot_locations")
    elif table_name.startswith("bridge_"):
        inferred["grain"] = "bridge"
        inferred["agent_intents"] = (table_name.removeprefix("bridge_").replace("_", "-"),)
    elif table_name.startswith("agg_"):
        inferred["grain"] = table_name.removeprefix("agg_").replace("_", "-")
        inferred["agent_intents"] = (table_name.removeprefix("agg_").replace("_", "-"),)

    if table_name in _SCD2_TABLES:
        inferred.setdefault("scd2_notes", _SCD2_NOTE)

    if schema_doc and "scd2" in schema_doc.casefold() and "scd2_notes" not in inferred:
        inferred.setdefault("scd2_notes", _SCD2_NOTE)

    return _merge_metadata(inferred, explicit or {})
