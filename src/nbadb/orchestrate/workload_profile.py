from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import duckdb

from nbadb.orchestrate.execution_policy import build_execution_policy
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    from collections.abc import Iterable


@dataclass(frozen=True, slots=True)
class EndpointWorkloadProfile:
    endpoint_name: str
    endpoint_family: str
    throughput_tier: str
    avg_duration_seconds: float
    p95_duration_seconds: float
    retry_rate: float
    error_rate: float
    avg_rows_per_request: float
    lane_cost: float
    reference_batch_cost: float
    preferred_max_span: int | None


@dataclass(frozen=True, slots=True)
class WorkloadPlanningSnapshot:
    endpoint_profiles: dict[str, EndpointWorkloadProfile]
    cross_product_pair_counts: dict[tuple[str, str], int]


_DEFAULT_SPAN_BY_TIER = {
    "cheap_high_volume": None,
    "expensive_stable": 8,
    "expensive_flaky": 4,
    "discovery_bound_cross_product": 3,
}


def _safe_float(value: object, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _metrics_from_connection(
    conn: duckdb.DuckDBPyConnection,
) -> dict[str, dict[str, float]]:
    tables = {
        row[0]
        for row in conn.execute(
            "SELECT table_name FROM duckdb_tables() WHERE database_name = 'main' AND schema_name = 'main'"
        ).fetchall()
    }
    if "_pipeline_metrics" not in tables:
        return {}

    metrics_rows = conn.execute(
        """
        SELECT
            endpoint,
            COALESCE(AVG(duration_seconds), 0.0) AS avg_duration_seconds,
            COALESCE(quantile_cont(duration_seconds, 0.95), 0.0) AS p95_duration_seconds,
            COALESCE(AVG(rows_extracted), 0.0) AS avg_rows_per_request,
            COALESCE(AVG(CASE WHEN error_count > 0 THEN 1.0 ELSE 0.0 END), 0.0) AS error_rate
        FROM _pipeline_metrics
        GROUP BY endpoint
        """
    ).fetchall()
    metrics = {
        str(endpoint): {
            "avg_duration_seconds": _safe_float(avg_duration),
            "p95_duration_seconds": _safe_float(p95_duration),
            "avg_rows_per_request": _safe_float(avg_rows),
            "error_rate": _safe_float(error_rate),
        }
        for endpoint, avg_duration, p95_duration, avg_rows, error_rate in metrics_rows
    }

    if "_extraction_journal" not in tables:
        return metrics

    retry_rows = conn.execute(
        """
        SELECT
            endpoint,
            COALESCE(AVG(retry_count), 0.0) AS avg_retry_count,
            COALESCE(AVG(CASE WHEN retry_count > 0 THEN 1.0 ELSE 0.0 END), 0.0) AS retry_rate
        FROM _extraction_journal
        GROUP BY endpoint
        """
    ).fetchall()
    for endpoint, avg_retry_count, retry_rate in retry_rows:
        payload = metrics.setdefault(str(endpoint), {})
        payload["avg_retry_count"] = _safe_float(avg_retry_count)
        payload["retry_rate"] = _safe_float(retry_rate)
    return metrics


def _cross_product_counts_from_store(
    store: PlayerTeamSeasonWorkloadStore,
) -> dict[tuple[str, str], int]:
    coverage = store.load_coverage()
    return dict(coverage.counts_by_pair)


def _tier_lane_cost(
    tier: str,
    *,
    avg_duration_seconds: float,
    p95_duration_seconds: float,
    retry_rate: float,
    error_rate: float,
    avg_rows_per_request: float,
) -> float:
    base = 1.0
    if tier == "expensive_stable":
        base = 2.5
    elif tier == "expensive_flaky":
        base = 4.0
    elif tier == "discovery_bound_cross_product":
        base = 6.0
    return (
        base
        + min(avg_duration_seconds / 10.0, 4.0)
        + min(p95_duration_seconds / 20.0, 4.0)
        + retry_rate * 5.0
        + error_rate * 5.0
        + min(avg_rows_per_request / 10_000.0, 2.0)
    )


def build_workload_planning_snapshot(
    support_matrix_rows: list[dict[str, Any]],
    *,
    duckdb_path: Path | None = None,
) -> WorkloadPlanningSnapshot:
    metrics: dict[str, dict[str, float]] = {}
    cross_product_pair_counts: dict[tuple[str, str], int] = {}
    if duckdb_path is not None and duckdb_path.exists():
        conn = duckdb.connect(str(duckdb_path), read_only=True)
        try:
            metrics = _metrics_from_connection(conn)
            cross_product_pair_counts = _cross_product_counts_from_store(
                PlayerTeamSeasonWorkloadStore.from_connection(conn)
            )
        finally:
            conn.close()

    endpoint_profiles: dict[str, EndpointWorkloadProfile] = {}
    for row in support_matrix_rows:
        endpoint_name = str(row.get("endpoint_name", "")).strip()
        if not endpoint_name:
            continue
        patterns = [str(value) for value in row.get("param_patterns", []) if str(value)]
        primary_pattern = patterns[0] if patterns else None
        metric = metrics.get(endpoint_name, {})
        policy = build_execution_policy(
            endpoint_name,
            pattern=primary_pattern,
            avg_duration_seconds=_safe_float(metric.get("avg_duration_seconds")),
            retry_rate=_safe_float(metric.get("retry_rate")),
            error_rate=_safe_float(metric.get("error_rate")),
        )
        lane_cost = _tier_lane_cost(
            policy.throughput_tier,
            avg_duration_seconds=_safe_float(metric.get("avg_duration_seconds")),
            p95_duration_seconds=_safe_float(metric.get("p95_duration_seconds")),
            retry_rate=_safe_float(metric.get("retry_rate")),
            error_rate=_safe_float(metric.get("error_rate")),
            avg_rows_per_request=_safe_float(metric.get("avg_rows_per_request")),
        )
        endpoint_profiles[endpoint_name] = EndpointWorkloadProfile(
            endpoint_name=endpoint_name,
            endpoint_family=policy.family,
            throughput_tier=policy.throughput_tier,
            avg_duration_seconds=_safe_float(metric.get("avg_duration_seconds")),
            p95_duration_seconds=_safe_float(metric.get("p95_duration_seconds")),
            retry_rate=_safe_float(metric.get("retry_rate")),
            error_rate=_safe_float(metric.get("error_rate")),
            avg_rows_per_request=_safe_float(metric.get("avg_rows_per_request")),
            lane_cost=lane_cost,
            reference_batch_cost=max(1.0, lane_cost),
            preferred_max_span=_DEFAULT_SPAN_BY_TIER.get(policy.throughput_tier),
        )
    return WorkloadPlanningSnapshot(
        endpoint_profiles=endpoint_profiles,
        cross_product_pair_counts=cross_product_pair_counts,
    )


def endpoint_cost(
    endpoint_profiles: dict[str, EndpointWorkloadProfile] | None,
    endpoint_names: Iterable[str],
) -> float:
    if not endpoint_profiles:
        return float(len(tuple(endpoint_names)))
    cost = 0.0
    for endpoint_name in endpoint_names:
        profile = endpoint_profiles.get(endpoint_name)
        cost += profile.lane_cost if profile is not None else 1.0
    return max(cost, 1.0)


def preferred_max_span(
    endpoint_profiles: dict[str, EndpointWorkloadProfile] | None,
    endpoint_names: Iterable[str],
) -> int | None:
    if not endpoint_profiles:
        return None
    spans = [
        profile.preferred_max_span
        for endpoint_name in endpoint_names
        if (profile := endpoint_profiles.get(endpoint_name)) is not None
        and profile.preferred_max_span is not None
    ]
    if not spans:
        return None
    return max(1, min(_safe_int(span, 1) for span in spans))
