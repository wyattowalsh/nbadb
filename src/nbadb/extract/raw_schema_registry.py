"""Raw schema lookup for extractors.

Uses the shared schema registry as the source of truth and only keeps the
minimal endpoint-to-table aliases needed where extractor names do not match
the discovered raw schema table names exactly.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nbadb.schemas.base import BaseSchema

from nbadb.schemas.registry import _raw_schema_registry

_RAW_SCHEMA_TABLE_ALIASES: dict[str, tuple[str, ...]] = {
    "box_score_traditional": ("raw_box_score_traditional_player",),
    "box_score_advanced": ("raw_box_score_advanced_player",),
    "box_score_misc": ("raw_box_score_misc_player",),
    "box_score_scoring": ("raw_box_score_scoring_player",),
    "box_score_usage": ("raw_box_score_usage_player",),
    "box_score_four_factors": ("raw_box_score_four_factors_player",),
    "box_score_hustle": ("raw_box_score_hustle_player",),
    "box_score_player_track": ("raw_box_score_player_track",),
    "box_score_defensive": ("raw_box_score_defensive_player",),
    "league_standings": ("raw_league_standings_v3",),
    "schedule": ("raw_schedule_league_v2",),
    "play_by_play": ("raw_play_by_play_v2",),
    "team_info_common": ("raw_team_info_common",),
    "live_box_score.home_team_stats": ("raw_live_box_score_team_stats",),
    "live_box_score.away_team_stats": ("raw_live_box_score_team_stats",),
    "live_box_score.home_team_player_stats": ("raw_live_box_score_player_stats",),
    "live_box_score.away_team_player_stats": ("raw_live_box_score_player_stats",),
}


def _schema_candidates(endpoint_name: str) -> list[str]:
    normalized = endpoint_name.replace(".", "_")
    candidates: list[str] = []
    if endpoint_name.startswith("raw_"):
        candidates.append(endpoint_name)
    candidates.append(f"raw_{normalized}")
    candidates.extend(_RAW_SCHEMA_TABLE_ALIASES.get(endpoint_name, ()))

    seen: set[str] = set()
    deduped: list[str] = []
    for candidate in candidates:
        if candidate not in seen:
            seen.add(candidate)
            deduped.append(candidate)
    return deduped


def get_raw_schema(endpoint_name: str) -> type[BaseSchema] | None:
    """Get the raw schema for an extractor endpoint or raw table name."""
    registry = _raw_schema_registry()
    for candidate in _schema_candidates(endpoint_name):
        if schema := registry.get(candidate):
            return schema
    return None
