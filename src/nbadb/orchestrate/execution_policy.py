from __future__ import annotations

from dataclasses import dataclass

_PLAYER_HISTORY_ENDPOINTS = frozenset(
    {
        "common_player_info",
        "player_awards",
        "player_career_stats",
        "player_compare",
        "player_dashboard_clutch",
        "player_dash_game_splits",
        "player_dash_general_splits",
        "player_dash_last_n_games",
        "player_dash_shooting_splits",
        "player_dash_team_perf",
        "player_dash_yoy",
        "player_next_games",
        "player_profile_v2",
        "player_streak_finder",
        "shot_chart_detail",
    }
)
_TEAM_HISTORY_ENDPOINTS = frozenset(
    {
        "franchise_leaders",
        "franchise_players",
        "team_details",
        "team_historical_leaders",
        "team_info_common",
        "team_year_by_year",
    }
)
_PLAY_BY_PLAY_ENDPOINTS = frozenset(
    {
        "play_by_play",
        "play_by_play_v2",
        "scoreboard_v2",
        "scoreboard_v3",
        "win_probability",
    }
)


@dataclass(frozen=True, slots=True)
class EndpointExecutionPolicy:
    endpoint_name: str
    family: str
    throughput_tier: str


def endpoint_family(endpoint_name: str, category: str | None = None) -> str:
    if endpoint_name in _PLAYER_HISTORY_ENDPOINTS:
        return "player_history"
    if endpoint_name in _TEAM_HISTORY_ENDPOINTS:
        return "team_history"
    if endpoint_name in _PLAY_BY_PLAY_ENDPOINTS:
        return "play_by_play"
    if endpoint_name.startswith("box_score_"):
        return "box_score"
    if category:
        normalized = category.strip().lower().replace(" ", "_")
        if normalized:
            return normalized
    return "default"


def throughput_tier(
    endpoint_name: str,
    *,
    pattern: str | None = None,
    avg_duration_seconds: float = 0.0,
    retry_rate: float = 0.0,
    error_rate: float = 0.0,
) -> str:
    if pattern == "player_team_season":
        return "discovery_bound_cross_product"
    if endpoint_name in _PLAYER_HISTORY_ENDPOINTS or endpoint_name in _TEAM_HISTORY_ENDPOINTS:
        if retry_rate >= 0.1 or error_rate >= 0.05:
            return "expensive_flaky"
        return "expensive_stable"
    if avg_duration_seconds >= 20.0:
        return "expensive_flaky" if retry_rate >= 0.1 or error_rate >= 0.05 else "expensive_stable"
    return "cheap_high_volume"


def build_execution_policy(
    endpoint_name: str,
    *,
    category: str | None = None,
    pattern: str | None = None,
    avg_duration_seconds: float = 0.0,
    retry_rate: float = 0.0,
    error_rate: float = 0.0,
) -> EndpointExecutionPolicy:
    return EndpointExecutionPolicy(
        endpoint_name=endpoint_name,
        family=endpoint_family(endpoint_name, category),
        throughput_tier=throughput_tier(
            endpoint_name,
            pattern=pattern,
            avg_duration_seconds=avg_duration_seconds,
            retry_rate=retry_rate,
            error_rate=error_rate,
        ),
    )
