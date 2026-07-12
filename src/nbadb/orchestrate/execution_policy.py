from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nbadb.core.config import NbaDbSettings

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
        "video_details_asset",
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
    concurrency_ceiling: int
    rate_limit: float
    timeout_seconds: int
    retry_budget: int
    breaker_sensitivity: str
    lane_split_preference: str


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
    settings: NbaDbSettings | None = None,
    category: str | None = None,
    pattern: str | None = None,
    avg_duration_seconds: float = 0.0,
    retry_rate: float = 0.0,
    error_rate: float = 0.0,
) -> EndpointExecutionPolicy:
    family = endpoint_family(endpoint_name, category)
    tier = throughput_tier(
        endpoint_name,
        pattern=pattern,
        avg_duration_seconds=avg_duration_seconds,
        retry_rate=retry_rate,
        error_rate=error_rate,
    )
    semaphore_tiers = getattr(settings, "semaphore_tiers", {}) if settings is not None else {}
    endpoint_semaphore_limits = (
        getattr(settings, "endpoint_semaphore_limits", {}) if settings is not None else {}
    )
    family_semaphore_limits = (
        getattr(settings, "family_semaphore_limits", {}) if settings is not None else {}
    )
    endpoint_rate_limits = (
        getattr(settings, "endpoint_rate_limits", {}) if settings is not None else {}
    )
    family_rate_limits = getattr(settings, "family_rate_limits", {}) if settings is not None else {}
    endpoint_request_timeouts = (
        getattr(settings, "endpoint_request_timeouts", {}) if settings is not None else {}
    )
    endpoint_retry_budgets = (
        getattr(settings, "endpoint_retry_budgets", {}) if settings is not None else {}
    )
    retry_budget = (
        int(
            endpoint_retry_budgets.get(
                endpoint_name,
                getattr(settings, "extract_max_retries", 0),
            )
        )
        if settings is not None
        else 0
    )
    concurrency_ceiling = int(
        endpoint_semaphore_limits.get(
            endpoint_name,
            family_semaphore_limits.get(
                family,
                semaphore_tiers.get(category or family, semaphore_tiers.get("default", 10)),
            ),
        )
    )
    rate_limit = float(
        endpoint_rate_limits.get(
            endpoint_name,
            family_rate_limits.get(
                family,
                getattr(settings, "rate_limit", 10.0) if settings else 10.0,
            ),
        )
    )
    timeout_seconds = int(endpoint_request_timeouts.get(endpoint_name, 60))
    breaker_sensitivity = "standard"
    if tier == "expensive_flaky":
        breaker_sensitivity = "high"
    elif tier == "cheap_high_volume":
        breaker_sensitivity = "low"
    lane_split_preference = "default"
    if pattern == "player_team_season":
        lane_split_preference = "density_sensitive"
    elif tier in {"expensive_flaky", "expensive_stable"}:
        lane_split_preference = "narrow"
    return EndpointExecutionPolicy(
        endpoint_name=endpoint_name,
        family=family,
        throughput_tier=tier,
        concurrency_ceiling=concurrency_ceiling,
        rate_limit=rate_limit,
        timeout_seconds=timeout_seconds,
        retry_budget=retry_budget,
        breaker_sensitivity=breaker_sensitivity,
        lane_split_preference=lane_split_preference,
    )
