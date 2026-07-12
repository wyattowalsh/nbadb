from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import math
import os
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from loguru import logger

from nbadb.core.types import SeasonType
from nbadb.extract.registry import registry
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.player_directory_snapshot import player_ids_by_season_from_snapshot
from nbadb.orchestrate.seasons import current_season, season_range
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

PLAYER_DISCOVERY_PATTERNS = frozenset({"player", "player_season"})
GAME_DISCOVERY_PATTERNS = frozenset({"game", "date"})
PLAYER_TEAM_SEASON_PATTERN = "player_team_season"
DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)
DEFAULT_DISCOVERY_SEED_CONCURRENCY = 8
DISCOVERY_SEED_CONCURRENCY_ENV = "NBADB_DISCOVERY_SEED_CONCURRENCY"
DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS = 90 * 60
DISCOVERY_SEED_DEADLINE_ENV = "NBADB_DISCOVERY_SEED_DEADLINE_SECONDS"

type SeedResult = tuple[str, dict[str, Any]]
CheckpointCallback = Callable[[str], None]
SeedResultCallback = Callable[[SeedResult], None]


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        with temporary_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def _split_csv(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _lane_seasons(lane: dict[str, Any]) -> tuple[str, ...]:
    raw_start = lane.get("season_start")
    raw_end = lane.get("season_end")
    if raw_start in (None, "") or raw_end in (None, ""):
        return tuple(season_range())
    return tuple(season_range(int(raw_start), int(raw_end)))


def _ordered_season_types(values: tuple[str, ...] | set[str]) -> tuple[str, ...]:
    unique = set(values)
    default_order = {value: index for index, value in enumerate(DEFAULT_SEASON_TYPES)}
    return tuple(
        sorted(
            unique,
            key=lambda value: (default_order.get(value, len(default_order)), value),
        )
    )


def _lane_season_types(lane: dict[str, Any]) -> tuple[str, ...]:
    configured = _split_csv(lane.get("season_types"))
    return _ordered_season_types(configured or DEFAULT_SEASON_TYPES)


def _lane_requests_patterns(lane: dict[str, Any], requested: frozenset[str]) -> bool:
    patterns = set(_split_csv(lane.get("patterns")))
    return not patterns or bool(patterns & requested)


def _seed_concurrency() -> int:
    raw_value = os.environ.get(
        DISCOVERY_SEED_CONCURRENCY_ENV,
        str(DEFAULT_DISCOVERY_SEED_CONCURRENCY),
    )
    try:
        return max(1, int(raw_value))
    except ValueError:
        logger.warning(
            "invalid {}={!r}; using {}",
            DISCOVERY_SEED_CONCURRENCY_ENV,
            raw_value,
            DEFAULT_DISCOVERY_SEED_CONCURRENCY,
        )
        return DEFAULT_DISCOVERY_SEED_CONCURRENCY


def _seed_deadline_seconds() -> float:
    raw_value = os.environ.get(
        DISCOVERY_SEED_DEADLINE_ENV,
        str(DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS),
    )
    try:
        value = float(raw_value)
    except ValueError:
        value = 0.0
    if not math.isfinite(value) or value <= 0:
        logger.warning(
            "invalid {}={!r}; using {}",
            DISCOVERY_SEED_DEADLINE_ENV,
            raw_value,
            DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS,
        )
        return float(DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS)
    return min(value, float(DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS))


def _seed_lanes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = manifest.get("github_matrix")
    if isinstance(matrix, dict):
        matrix_lanes = matrix.get("include")
        if isinstance(matrix_lanes, list):
            return [lane for lane in matrix_lanes if isinstance(lane, dict)]
    lanes = manifest.get("lanes", [])
    if isinstance(lanes, list):
        return [lane for lane in lanes if isinstance(lane, dict)]
    return []


def _discovery_pairs(
    manifest: dict[str, Any],
    *,
    patterns: frozenset[str],
) -> tuple[tuple[str, str], ...]:
    pairs: set[tuple[str, str]] = set()
    for lane in _seed_lanes(manifest):
        if lane.get("resume_only") or not _lane_requests_patterns(lane, patterns):
            continue
        for season in _lane_seasons(lane):
            for season_type in _lane_season_types(lane):
                pairs.add((season, season_type))
    default_order = {value: index for index, value in enumerate(DEFAULT_SEASON_TYPES)}
    return tuple(
        sorted(
            pairs,
            key=lambda pair: (
                pair[0],
                default_order.get(pair[1], len(default_order)),
                pair[1],
            ),
        )
    )


def game_discovery_pairs(manifest: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return exact game/date season and season-type pairs for the current matrix wave."""
    return _discovery_pairs(manifest, patterns=GAME_DISCOVERY_PATTERNS)


def player_team_season_pairs(manifest: dict[str, Any]) -> tuple[tuple[str, str], ...]:
    """Return exact player/team workload pairs for the current matrix wave."""
    return _discovery_pairs(manifest, patterns=frozenset({PLAYER_TEAM_SEASON_PATTERN}))


def _group_exact_pairs(
    pairs: set[tuple[str, str]],
) -> tuple[tuple[tuple[str, ...], tuple[str, ...]], ...]:
    """Group seasons sharing the same exact season-type set without adding a cross product."""
    season_types_by_season: dict[str, set[str]] = {}
    for season, season_type in pairs:
        season_types_by_season.setdefault(season, set()).add(season_type)

    seasons_by_types: dict[tuple[str, ...], list[str]] = {}
    for season, season_types in season_types_by_season.items():
        ordered_types = _ordered_season_types(season_types)
        seasons_by_types.setdefault(ordered_types, []).append(season)

    return tuple(
        (tuple(sorted(seasons)), season_types)
        for season_types, seasons in sorted(seasons_by_types.items())
    )


def player_discovery_scopes(manifest: dict[str, Any]) -> tuple[DiscoveryArtifactScope, ...]:
    """Return required historical player-ID cache scopes for this matrix wave."""
    scopes: set[DiscoveryArtifactScope] = set()
    for lane in _seed_lanes(manifest):
        if lane.get("resume_only"):
            continue
        patterns = set(_split_csv(lane.get("patterns")))
        if not patterns & PLAYER_DISCOVERY_PATTERNS:
            continue
        seasons = _lane_seasons(lane)
        if not seasons:
            continue
        if "player_season" in patterns:
            for season in seasons:
                scopes.add(
                    DiscoveryArtifactScope(
                        kind="player_ids_all",
                        seasons=(season,),
                        season_types=(),
                        variant="historical",
                    )
                )
        scopes.add(
            DiscoveryArtifactScope(
                kind="player_ids_all",
                seasons=seasons,
                season_types=(),
                variant="historical",
            )
        )
    return tuple(sorted(scopes, key=lambda scope: (len(scope.seasons), scope.seasons)))


def _player_season_scope(season: str) -> DiscoveryArtifactScope:
    return DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=(season,),
        season_types=(),
        variant="historical",
    )


async def _discover_targeted_ids_by_season(
    *,
    discovery: EntityDiscovery,
    seasons: list[str],
) -> tuple[dict[str, list[int]], dict[str, str]]:
    semaphore = asyncio.Semaphore(_seed_concurrency())

    async def _discover(season: str) -> tuple[str, list[int], str | None]:
        async with semaphore:
            result_method = getattr(discovery, "discover_all_player_ids_result", None)
            if callable(result_method):
                result = await result_method(season=season)
                ids = [int(value) for value in result.ids]
                failure_kind = result.failure_kind
            else:
                ids = [
                    int(value) for value in await discovery.discover_all_player_ids(season=season)
                ]
                failure_kind = None if ids else "no_data"
            return season, ids, failure_kind

    tasks = [asyncio.create_task(_discover(season)) for season in seasons]
    try:
        results = await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return (
        {season: ids for season, ids, _failure_kind in results if ids},
        {
            season: str(failure_kind)
            for season, ids, failure_kind in results
            if not ids and failure_kind is not None
        },
    )


def _player_failure_summary_rows(
    failures: dict[str, str],
    *,
    seasons: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, str]]:
    included_seasons = set(seasons) if seasons is not None else set(failures)
    return [
        {"season": season, "failure_kind": failure_kind}
        for season, failure_kind in sorted(failures.items())
        if season in included_seasons
    ]


def _player_failure_details(
    failures: dict[str, str],
    *,
    seasons: list[str] | tuple[str, ...],
) -> dict[str, Any]:
    rows = _player_failure_summary_rows(failures, seasons=seasons)
    return {
        "discovery_errors": sorted({row["failure_kind"] for row in rows}),
        "discovery_failures": rows,
    }


async def _seed_scope(
    *,
    scope: DiscoveryArtifactScope,
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    refresh_seasons: frozenset[str] = frozenset(),
    progress: _SeedProgress | None = None,
) -> tuple[str, dict[str, Any]]:
    cached = store.load_ids(scope)
    player_discovery_failures: dict[str, str] = {}
    scoped_refresh_seasons = refresh_seasons & frozenset(scope.seasons)
    if cached and len(scope.seasons) == 1 and not scoped_refresh_seasons:
        if progress is not None:
            progress.mark_player_scope(scope)
        return (
            "skipped",
            {
                "kind": scope.kind,
                "seasons": list(scope.seasons),
                "count": len(cached),
                "reason": "already_cached",
            },
        )

    if len(scope.seasons) == 1:
        season = scope.seasons[0]
        logger.info("seeding historical player discovery for {}", season)
        ids_by_season, player_discovery_failures = await _discover_targeted_ids_by_season(
            discovery=discovery,
            seasons=[season],
        )
        ids = ids_by_season.get(season, [])
        if progress is not None:
            for failure_kind in player_discovery_failures.values():
                progress.record_failure_type(failure_kind)
    else:
        logger.info(
            "seeding aggregate historical player discovery for {} seasons",
            len(scope.seasons),
        )
        snapshot_ids_by_season = player_ids_by_season_from_snapshot(list(scope.seasons))
        ids_by_season: dict[str, list[int]] = {}
        sources_by_season: dict[str, set[str]] = {}
        missing_refresh_seasons: list[str] = []

        for season in scope.seasons:
            season_scope = _player_season_scope(season)
            cached_ids = store.load_ids(season_scope)
            snapshot_ids = snapshot_ids_by_season.get(season, [])
            season_ids = sorted({int(value) for value in [*cached_ids, *snapshot_ids]})
            sources = set()
            if cached_ids:
                sources.add("cache")
            if snapshot_ids:
                sources.add("snapshot")
            if not season_ids:
                continue
            ids_by_season[season] = season_ids
            sources_by_season[season] = sources
            if season_ids != sorted({int(value) for value in cached_ids}):
                store.upsert_ids(
                    season_scope,
                    season_ids,
                    provenance=f"workflow-discovery-seed-{'-'.join(sorted(sources))}",
                )
            if progress is not None and season not in scoped_refresh_seasons:
                progress.mark_player_season(season)

        if scoped_refresh_seasons:
            refresh_targets = [
                season for season in scope.seasons if season in scoped_refresh_seasons
            ]
            logger.info(
                "target-refreshing {} mutable aggregate player discovery seasons",
                len(refresh_targets),
            )
            (
                refreshed_ids_by_season,
                refresh_discovery_failures,
            ) = await _discover_targeted_ids_by_season(
                discovery=discovery,
                seasons=refresh_targets,
            )
            player_discovery_failures.update(refresh_discovery_failures)
            if progress is not None:
                for failure_kind in refresh_discovery_failures.values():
                    progress.record_failure_type(failure_kind)
            for season in refresh_targets:
                refreshed_ids = refreshed_ids_by_season.get(season, [])
                if not refreshed_ids:
                    missing_refresh_seasons.append(season)
                    continue
                season_ids = sorted(
                    {int(value) for value in [*ids_by_season.get(season, []), *refreshed_ids]}
                )
                ids_by_season[season] = season_ids
                sources_by_season.setdefault(season, set()).add("targeted")
                store.upsert_ids(
                    _player_season_scope(season),
                    season_ids,
                    provenance="workflow-discovery-seed-targeted-refresh",
                )
                if progress is not None:
                    progress.mark_player_season(season)

        missing_seasons = [season for season in scope.seasons if not ids_by_season.get(season)]
        bulk_discover = getattr(discovery, "discover_all_player_ids_by_season", None)
        if missing_seasons and callable(bulk_discover):
            logger.info(
                "bulk-seeding {} unresolved aggregate player discovery seasons",
                len(missing_seasons),
            )
            bulk_ids_by_season = await bulk_discover(missing_seasons)
            for season in missing_seasons:
                season_ids = sorted({int(value) for value in bulk_ids_by_season.get(season, [])})
                if not season_ids:
                    continue
                ids_by_season[season] = season_ids
                sources_by_season[season] = {"bulk"}
                if season in missing_refresh_seasons:
                    missing_refresh_seasons.remove(season)
                store.upsert_ids(
                    _player_season_scope(season),
                    season_ids,
                    provenance="workflow-discovery-seed-bulk",
                )
                if progress is not None:
                    progress.mark_player_season(season)

        missing_seasons = [season for season in scope.seasons if not ids_by_season.get(season)]
        targeted_missing_seasons = [
            season for season in missing_seasons if season not in scoped_refresh_seasons
        ]
        if targeted_missing_seasons:
            logger.info(
                "target-seeding {} unresolved aggregate player discovery seasons",
                len(targeted_missing_seasons),
            )
            (
                targeted_ids_by_season,
                targeted_discovery_failures,
            ) = await _discover_targeted_ids_by_season(
                discovery=discovery,
                seasons=targeted_missing_seasons,
            )
            player_discovery_failures.update(targeted_discovery_failures)
            if progress is not None:
                for failure_kind in targeted_discovery_failures.values():
                    progress.record_failure_type(failure_kind)
            for season in targeted_missing_seasons:
                season_ids = sorted(
                    {int(value) for value in targeted_ids_by_season.get(season, [])}
                )
                if not season_ids:
                    continue
                ids_by_season[season] = season_ids
                sources_by_season[season] = {"targeted"}
                store.upsert_ids(
                    _player_season_scope(season),
                    season_ids,
                    provenance="workflow-discovery-seed-targeted",
                )
                if progress is not None:
                    progress.mark_player_season(season)

        missing_seasons = [season for season in scope.seasons if not ids_by_season.get(season)]
        if missing_seasons:
            return (
                "failures",
                {
                    "kind": scope.kind,
                    "seasons": list(scope.seasons),
                    "reason": "incomplete_season_coverage",
                    "missing_seasons": missing_seasons,
                    "resolved_season_count": len(ids_by_season),
                    "requested_season_count": len(scope.seasons),
                    **_player_failure_details(
                        player_discovery_failures,
                        seasons=missing_seasons,
                    ),
                },
            )
        if missing_refresh_seasons:
            return (
                "failures",
                {
                    "kind": scope.kind,
                    "seasons": list(scope.seasons),
                    "reason": "incomplete_refresh_coverage",
                    "missing_seasons": missing_refresh_seasons,
                    "resolved_season_count": len(scope.seasons) - len(missing_refresh_seasons),
                    "requested_season_count": len(scope.seasons),
                    **_player_failure_details(
                        player_discovery_failures,
                        seasons=missing_refresh_seasons,
                    ),
                },
            )

        ids = sorted({int(value) for season_ids in ids_by_season.values() for value in season_ids})

    if not ids:
        return (
            "failures",
            {
                "kind": scope.kind,
                "seasons": list(scope.seasons),
                "reason": "no_ids",
                **_player_failure_details(
                    player_discovery_failures,
                    seasons=list(scope.seasons),
                ),
            },
        )

    if cached == ids:
        if progress is not None:
            progress.mark_player_scope(scope)
        return (
            "skipped",
            {
                "kind": scope.kind,
                "seasons": list(scope.seasons),
                "count": len(cached),
                "reason": "already_cached_complete",
            },
        )

    provenance = "workflow-discovery-seed"
    if len(scope.seasons) > 1:
        aggregate_sources = sorted(
            {source for season_sources in sources_by_season.values() for source in season_sources}
        )
        provenance = f"workflow-discovery-seed-aggregate-{'-'.join(aggregate_sources)}"
    stored = store.upsert_ids(scope, ids, provenance=provenance)
    if progress is not None:
        progress.mark_player_scope(scope)
    return (
        "seeded",
        {
            "kind": scope.kind,
            "seasons": list(scope.seasons),
            "count": len(stored),
        },
    )


async def _seed_scopes_concurrently(
    *,
    scopes: list[DiscoveryArtifactScope],
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    concurrency: int,
    force_refresh_seasons: frozenset[str] = frozenset(),
    progress: _SeedProgress | None = None,
    checkpoint: CheckpointCallback | None = None,
    on_result: SeedResultCallback | None = None,
) -> list[SeedResult]:
    if not scopes:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(
        scope: DiscoveryArtifactScope,
        batch_index: int,
    ) -> SeedResult:
        async with semaphore:
            result = await _seed_scope(
                scope=scope,
                store=store,
                discovery=discovery,
                refresh_seasons=force_refresh_seasons,
                progress=progress,
            )
            if on_result is not None:
                on_result(result)
            if checkpoint is not None:
                checkpoint(f"player_targeted_{batch_index}_of_{len(scopes)}")
            return result

    tasks = [
        asyncio.create_task(_run(scope, batch_index))
        for batch_index, scope in enumerate(scopes, start=1)
    ]
    try:
        return await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise


def _seed_scopes_from_ids_by_season(
    *,
    scopes: list[DiscoveryArtifactScope],
    store: DiscoveryArtifactStore,
    ids_by_season: dict[str, list[int]],
    provenance: str,
    progress: _SeedProgress | None = None,
) -> tuple[list[tuple[str, dict[str, Any]]], list[DiscoveryArtifactScope]]:
    results: list[tuple[str, dict[str, Any]]] = []
    missing_scopes: list[DiscoveryArtifactScope] = []
    for scope in scopes:
        season = scope.seasons[0]
        ids = ids_by_season.get(season, [])
        if not ids:
            missing_scopes.append(scope)
            continue
        stored = store.upsert_ids(scope, ids, provenance=provenance)
        if progress is not None:
            progress.mark_player_scope(scope)
        results.append(
            (
                "seeded",
                {
                    "kind": scope.kind,
                    "seasons": list(scope.seasons),
                    "count": len(stored),
                },
            )
        )
    return results, missing_scopes


async def _seed_single_season_scopes_from_bulk(
    *,
    scopes: list[DiscoveryArtifactScope],
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    progress: _SeedProgress | None = None,
    checkpoint: CheckpointCallback | None = None,
    on_result: SeedResultCallback | None = None,
) -> tuple[list[SeedResult], list[DiscoveryArtifactScope]]:
    if not scopes:
        return [], []

    seasons = [scope.seasons[0] for scope in scopes]
    logger.info(
        "snapshot-seeding {} historical player discovery seasons",
        len(set(seasons)),
    )
    snapshot_results, live_scopes = _seed_scopes_from_ids_by_season(
        scopes=scopes,
        store=store,
        ids_by_season=player_ids_by_season_from_snapshot(seasons),
        provenance="workflow-discovery-seed-snapshot",
        progress=progress,
    )
    if on_result is not None:
        for result in snapshot_results:
            on_result(result)
    if checkpoint is not None:
        checkpoint("player_snapshot")
    if not live_scopes:
        return snapshot_results, []

    bulk_discover = getattr(discovery, "discover_all_player_ids_by_season", None)
    ids_by_season: dict[str, list[int]] = {}
    if callable(bulk_discover):
        logger.info(
            "bulk-seeding {} historical player discovery seasons from common_all_players",
            len({scope.seasons[0] for scope in live_scopes}),
        )
        ids_by_season = await bulk_discover([scope.seasons[0] for scope in live_scopes])

    bulk_results, fallback_scopes = _seed_scopes_from_ids_by_season(
        scopes=live_scopes,
        store=store,
        ids_by_season=ids_by_season,
        provenance="workflow-discovery-seed-bulk",
        progress=progress,
    )
    if on_result is not None:
        for result in bulk_results:
            on_result(result)
    if checkpoint is not None:
        checkpoint("player_bulk_batch")
    return [*snapshot_results, *bulk_results], fallback_scopes


def _combo_scope(season: str, season_type: str) -> DiscoveryArtifactScope:
    return DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=(season,),
        season_types=(season_type,),
    )


def _pair_summary_rows(pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"season": season, "season_type": season_type} for season, season_type in sorted(pairs)]


def _pair_failure_summary_rows(
    failures: Mapping[tuple[str, str], str],
) -> list[dict[str, str]]:
    return [
        {
            "season": season,
            "season_type": season_type,
            "failure_kind": failure_kind,
        }
        for (season, season_type), failure_kind in sorted(failures.items())
    ]


def _scope_summary_row(scope: DiscoveryArtifactScope) -> dict[str, Any]:
    return {
        "kind": scope.kind,
        "seasons": list(scope.seasons),
        "season_types": list(scope.season_types),
        "variant": scope.variant,
        "scope_digest": scope.digest(),
    }


class _SeedProgress:
    def __init__(
        self,
        *,
        scopes: tuple[DiscoveryArtifactScope, ...],
        game_pairs: set[tuple[str, str]],
        player_team_pairs: set[tuple[str, str]],
        duckdb_path: Path,
        workload_store: PlayerTeamSeasonWorkloadStore,
    ) -> None:
        self.requested_player_scopes = frozenset(scopes)
        self.requested_player_seasons = frozenset(
            season for scope in scopes for season in scope.seasons
        )
        self.requested_game_pairs = frozenset(game_pairs)
        self.requested_player_team_pairs = frozenset(player_team_pairs)
        self.covered_player_scopes: set[DiscoveryArtifactScope] = set()
        self.covered_player_seasons: set[str] = set()
        self.covered_game_pairs: set[tuple[str, str]] = set()
        self.covered_player_team_pairs: set[tuple[str, str]] = set()
        self.observed_failure_types: set[str] = set()
        self._artifact_root = duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
        self._workload_store = workload_store

    def mark_player_season(self, season: str) -> None:
        if season in self.requested_player_seasons:
            self.covered_player_seasons.add(season)

    def mark_player_scope(self, scope: DiscoveryArtifactScope) -> None:
        if scope in self.requested_player_scopes:
            self.covered_player_scopes.add(scope)
        self.covered_player_seasons.update(
            season for season in scope.seasons if season in self.requested_player_seasons
        )

    def mark_game_pairs(self, pairs: set[tuple[str, str]]) -> None:
        self.covered_game_pairs.update(pairs & self.requested_game_pairs)

    def mark_player_team_pairs(self, pairs: set[tuple[str, str]]) -> None:
        self.covered_player_team_pairs.update(pairs & self.requested_player_team_pairs)

    def record_failure_type(self, failure_type: str) -> None:
        self.observed_failure_types.add(failure_type)

    def is_complete(self) -> bool:
        return (
            self.requested_player_scopes <= self.covered_player_scopes
            and self.requested_player_seasons <= self.covered_player_seasons
            and self.requested_game_pairs <= self.covered_game_pairs
            and self.requested_player_team_pairs <= self.covered_player_team_pairs
            and (
                not self.requested_player_team_pairs
                or self._workload_store.integrity_attestation() is not None
            )
        )

    def _artifact_row(self, scope: DiscoveryArtifactScope) -> dict[str, Any]:
        stem = f"{scope.kind}.{scope.digest()}"
        manifest_path = self._artifact_root / f"{stem}.json"
        artifact_path = self._artifact_root / f"{stem}.parquet"
        content_sha256: str | None = None
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            manifest = None
        if isinstance(manifest, dict):
            content = manifest.get("content")
            if isinstance(content, dict):
                generation_name = content.get("path")
                if (
                    isinstance(generation_name, str)
                    and Path(generation_name).name == generation_name
                ):
                    artifact_path = self._artifact_root / generation_name
                recorded_sha256 = content.get("sha256")
                if isinstance(recorded_sha256, str):
                    content_sha256 = recorded_sha256
        return {
            **_scope_summary_row(scope),
            "artifact_path": str(artifact_path),
            "manifest_path": str(manifest_path),
            "content_sha256": content_sha256,
        }

    def attestation(self) -> dict[str, Any]:
        covered_player_scopes = self.covered_player_scopes & self.requested_player_scopes
        covered_player_seasons = self.covered_player_seasons & self.requested_player_seasons
        covered_game_pairs = self.covered_game_pairs & self.requested_game_pairs
        covered_player_team_pairs = (
            self.covered_player_team_pairs & self.requested_player_team_pairs
        )
        missing_player_scopes = self.requested_player_scopes - covered_player_scopes
        missing_player_seasons = self.requested_player_seasons - covered_player_seasons
        missing_game_pairs = self.requested_game_pairs - covered_game_pairs
        missing_player_team_pairs = self.requested_player_team_pairs - covered_player_team_pairs

        requested_exact_count = (
            len(self.requested_player_seasons)
            + len(self.requested_game_pairs)
            + len(self.requested_player_team_pairs)
        )
        covered_exact_count = (
            len(covered_player_seasons) + len(covered_game_pairs) + len(covered_player_team_pairs)
        )
        missing_exact_count = requested_exact_count - covered_exact_count

        requested_counts = {
            "player_scope_count": len(self.requested_player_scopes),
            "player_season_count": len(self.requested_player_seasons),
            "game_combo_count": len(self.requested_game_pairs),
            "player_team_season_pair_count": len(self.requested_player_team_pairs),
            "exact_unit_count": requested_exact_count,
        }
        covered_counts = {
            "player_scope_count": len(covered_player_scopes),
            "player_season_count": len(covered_player_seasons),
            "game_combo_count": len(covered_game_pairs),
            "player_team_season_pair_count": len(covered_player_team_pairs),
            "exact_unit_count": covered_exact_count,
        }
        missing_counts = {
            "player_scope_count": len(missing_player_scopes),
            "player_season_count": len(missing_player_seasons),
            "game_combo_count": len(missing_game_pairs),
            "player_team_season_pair_count": len(missing_player_team_pairs),
            "exact_unit_count": missing_exact_count,
        }

        workload_artifact: dict[str, Any] | None = None
        if covered_player_team_pairs:
            integrity = self._workload_store.integrity_attestation()
            workload_artifact = {
                "artifact_path": str(self._workload_store.artifact_path),
                "manifest_path": str(self._workload_store.manifest_path),
                "covered_pair_count": len(covered_player_team_pairs),
                "covered_pairs": _pair_summary_rows(set(covered_player_team_pairs)),
                "integrity": integrity,
            }

        return {
            "requested_exact_unit_count": requested_exact_count,
            "covered_exact_unit_count": covered_exact_count,
            "missing_exact_unit_count": missing_exact_count,
            "coverage": {
                "requested": requested_counts,
                "covered": covered_counts,
                "missing": missing_counts,
            },
            "requested_units": {
                "player_scopes": [
                    _scope_summary_row(scope)
                    for scope in sorted(
                        self.requested_player_scopes,
                        key=lambda item: (len(item.seasons), item.seasons),
                    )
                ],
                "player_seasons": [
                    {"season": season} for season in sorted(self.requested_player_seasons)
                ],
                "game_combos": _pair_summary_rows(set(self.requested_game_pairs)),
                "player_team_season_pairs": _pair_summary_rows(
                    set(self.requested_player_team_pairs)
                ),
            },
            "covered_units": {
                "player_scopes": [
                    _scope_summary_row(scope)
                    for scope in sorted(
                        covered_player_scopes,
                        key=lambda item: (len(item.seasons), item.seasons),
                    )
                ],
                "player_seasons": [{"season": season} for season in sorted(covered_player_seasons)],
                "game_combos": _pair_summary_rows(set(covered_game_pairs)),
                "player_team_season_pairs": _pair_summary_rows(set(covered_player_team_pairs)),
            },
            "missing_units": {
                "player_scopes": [
                    _scope_summary_row(scope)
                    for scope in sorted(
                        missing_player_scopes,
                        key=lambda item: (len(item.seasons), item.seasons),
                    )
                ],
                "player_seasons": [{"season": season} for season in sorted(missing_player_seasons)],
                "game_combos": _pair_summary_rows(set(missing_game_pairs)),
                "player_team_season_pairs": _pair_summary_rows(set(missing_player_team_pairs)),
            },
            "artifacts": {
                "discovery_artifact_dir": str(self._artifact_root),
                "player_scope_artifacts": [
                    self._artifact_row(scope)
                    for scope in sorted(
                        covered_player_scopes,
                        key=lambda item: (len(item.seasons), item.seasons),
                    )
                ],
                "player_season_artifacts": [
                    self._artifact_row(_player_season_scope(season))
                    for season in sorted(covered_player_seasons)
                ],
                "game_combo_artifacts": [
                    self._artifact_row(_combo_scope(season, season_type))
                    for season, season_type in sorted(covered_game_pairs)
                ],
                "player_team_season_workload": workload_artifact,
            },
        }


async def _seed_game_discovery_pairs(
    *,
    requested_pairs: set[tuple[str, str]],
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    refresh_seasons: frozenset[str] = frozenset(),
    progress: _SeedProgress | None = None,
    checkpoint: CheckpointCallback | None = None,
    on_result: SeedResultCallback | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if not requested_pairs:
        return []

    cached_pairs = {
        pair
        for pair in requested_pairs
        if pair[0] not in refresh_seasons
        and store.load_game_log_frame(_combo_scope(*pair)) is not None
    }
    if progress is not None:
        progress.mark_game_pairs(cached_pairs)
    if checkpoint is not None:
        checkpoint("game_cache")
    missing_pairs = requested_pairs - cached_pairs
    grouped_scopes = _group_exact_pairs(missing_pairs)
    persisted_pairs: set[tuple[str, str]] = set()
    discovery_errors: list[str] = []
    discovery_failures: dict[tuple[str, str], str] = {}

    for batch_index, (seasons, season_types) in enumerate(grouped_scopes, start=1):
        expected_pairs = {
            (season, season_type) for season in seasons for season_type in season_types
        }
        batch_persisted_pairs: set[tuple[str, str]] = set()

        def _persist_combo(
            pair: tuple[str, str],
            frame: Any,
            *,
            expected: set[tuple[str, str]] = expected_pairs,
            batch_persisted: set[tuple[str, str]] = batch_persisted_pairs,
            current_batch_index: int = batch_index,
        ) -> None:
            if pair not in expected or pair in batch_persisted:
                return
            store.upsert_game_log_combo_frames(
                {pair: frame},
                provenance="workflow-discovery-seed",
            )
            batch_persisted.add(pair)
            persisted_pairs.add(pair)
            if progress is not None:
                progress.mark_game_pairs({pair})
            if checkpoint is not None:
                checkpoint(
                    f"game_batch_{current_batch_index}_combo_{len(batch_persisted)}"
                    f"_of_{len(expected)}"
                )

        logger.info(
            "seeding exact game discovery for {} combos across {} seasons",
            len(expected_pairs),
            len(seasons),
        )
        try:
            result = await discovery.discover_game_ids_result(
                list(seasons),
                season_types=list(season_types),
                on_combo_covered=_persist_combo,
            )
        except Exception as exc:
            failure_type = type(exc).__name__
            logger.error(
                "exact game discovery failed for seasons={} season_types={}: {}",
                list(seasons),
                list(season_types),
                failure_type,
            )
            discovery_errors.append(failure_type)
            if progress is not None:
                progress.record_failure_type(failure_type)
            if on_result is not None:
                on_result(
                    (
                        "failures",
                        {
                            "kind": "league_game_log",
                            "seasons": list(seasons),
                            "season_types": list(season_types),
                            "requested_combo_count": len(expected_pairs),
                            "covered_combo_count": 0,
                            "cached_combo_count": 0,
                            "persisted_combo_count": 0,
                            "refreshed_combo_count": 0,
                            "grouped_scope_count": 1,
                            "reason": "incomplete_combo_coverage",
                            "missing_combos": _pair_summary_rows(expected_pairs),
                            "discovery_errors": [failure_type],
                            "discovery_failures": [],
                        },
                    )
                )
            if checkpoint is not None:
                checkpoint(f"game_batch_{batch_index}_of_{len(grouped_scopes)}")
            continue

        complete_frames = {
            pair: frame
            for pair, frame in result.frames_by_combo.items()
            if pair in expected_pairs and pair in result.covered_combos
        }
        batch_failures = {
            pair: failure_kind
            for pair, failure_kind in result.failures_by_combo.items()
            if pair in expected_pairs and pair not in complete_frames
        }
        discovery_failures.update(batch_failures)
        discovery_errors.extend(batch_failures.values())
        if progress is not None:
            for failure_kind in batch_failures.values():
                progress.record_failure_type(failure_kind)
        if complete_frames:
            for pair, frame in sorted(complete_frames.items()):
                _persist_combo(pair, frame)
        if on_result is not None:
            batch_summary = {
                "kind": "league_game_log",
                "seasons": list(seasons),
                "season_types": list(season_types),
                "requested_combo_count": len(expected_pairs),
                "covered_combo_count": len(complete_frames),
                "cached_combo_count": 0,
                "persisted_combo_count": len(complete_frames),
                "refreshed_combo_count": len(
                    {pair for pair in complete_frames if pair[0] in refresh_seasons}
                ),
                "grouped_scope_count": 1,
            }
            if complete_frames:
                on_result(("seeded", batch_summary))
            unresolved_batch_pairs = expected_pairs - set(complete_frames)
            if unresolved_batch_pairs:
                on_result(
                    (
                        "failures",
                        {
                            **batch_summary,
                            "reason": "incomplete_combo_coverage",
                            "missing_combos": _pair_summary_rows(unresolved_batch_pairs),
                            "discovery_errors": sorted(set(batch_failures.values())),
                            "discovery_failures": _pair_failure_summary_rows(batch_failures),
                        },
                    )
                )
        if checkpoint is not None:
            checkpoint(f"game_batch_{batch_index}_of_{len(grouped_scopes)}")

    resolved_pairs = cached_pairs | persisted_pairs
    unresolved_pairs = requested_pairs - resolved_pairs
    summary = {
        "kind": "league_game_log",
        "seasons": sorted({season for season, _season_type in requested_pairs}),
        "season_types": list(
            _ordered_season_types({season_type for _season, season_type in requested_pairs})
        ),
        "requested_combo_count": len(requested_pairs),
        "covered_combo_count": len(resolved_pairs),
        "cached_combo_count": len(cached_pairs),
        "persisted_combo_count": len(persisted_pairs),
        "refreshed_combo_count": len(
            {pair for pair in persisted_pairs if pair[0] in refresh_seasons}
        ),
        "grouped_scope_count": len(grouped_scopes),
    }
    if on_result is not None:
        if not grouped_scopes:
            on_result(("skipped", {**summary, "reason": "already_cached_complete"}))
        return []
    if unresolved_pairs:
        return [
            (
                "failures",
                {
                    **summary,
                    "reason": "incomplete_combo_coverage",
                    "missing_combos": _pair_summary_rows(unresolved_pairs),
                    "discovery_errors": sorted(set(discovery_errors)),
                    "discovery_failures": _pair_failure_summary_rows(
                        {
                            pair: failure_kind
                            for pair, failure_kind in discovery_failures.items()
                            if pair in unresolved_pairs
                        }
                    ),
                },
            )
        ]
    if persisted_pairs:
        return [("seeded", summary)]
    return [("skipped", {**summary, "reason": "already_cached_complete"})]


async def _seed_player_team_season_pairs(
    *,
    requested_pairs: set[tuple[str, str]],
    store: PlayerTeamSeasonWorkloadStore,
    discovery: EntityDiscovery,
    refresh_seasons: frozenset[str] = frozenset(),
    progress: _SeedProgress | None = None,
    checkpoint: CheckpointCallback | None = None,
    on_result: SeedResultCallback | None = None,
) -> list[tuple[str, dict[str, Any]]]:
    if not requested_pairs:
        return []

    requested_seasons = sorted({season for season, _season_type in requested_pairs})
    requested_season_types = list(
        _ordered_season_types({season_type for _season, season_type in requested_pairs})
    )
    cached_coverage = store.load_coverage(
        seasons=requested_seasons,
        season_types=requested_season_types,
    )
    cached_pairs = {
        pair
        for pair in requested_pairs & cached_coverage.covered_pairs
        if pair[0] not in refresh_seasons
    }
    if progress is not None:
        progress.mark_player_team_pairs(cached_pairs)
    if checkpoint is not None:
        checkpoint("player_team_cache")
    missing_pairs = requested_pairs - cached_pairs
    grouped_scopes = _group_exact_pairs(missing_pairs)
    persisted_pairs: set[tuple[str, str]] = set()
    persisted_param_count = 0
    discovery_errors: list[str] = []
    discovery_failures: dict[tuple[str, str], str] = {}

    for batch_index, (seasons, season_types) in enumerate(grouped_scopes, start=1):
        expected_pairs = {
            (season, season_type) for season in seasons for season_type in season_types
        }
        logger.info(
            "seeding exact player/team workload for {} pairs across {} unique seasons",
            len(expected_pairs),
            len(seasons),
        )
        try:
            result = await discovery.discover_player_team_season_params_result(
                list(seasons),
                season_types=list(season_types),
            )
        except Exception as exc:
            failure_type = type(exc).__name__
            logger.error(
                "exact player/team discovery failed for seasons={} season_types={}: {}",
                list(seasons),
                list(season_types),
                failure_type,
            )
            discovery_errors.append(failure_type)
            if progress is not None:
                progress.record_failure_type(failure_type)
            if on_result is not None:
                on_result(
                    (
                        "failures",
                        {
                            "kind": "player_team_season_workload",
                            "seasons": list(seasons),
                            "season_types": list(season_types),
                            "requested_pair_count": len(expected_pairs),
                            "covered_pair_count": 0,
                            "requested_unique_season_count": len(seasons),
                            "cached_pair_count": 0,
                            "persisted_pair_count": 0,
                            "persisted_param_count": 0,
                            "refreshed_pair_count": 0,
                            "grouped_scope_count": 1,
                            "reason": "incomplete_pair_coverage",
                            "missing_pairs": _pair_summary_rows(expected_pairs),
                            "discovery_errors": [failure_type],
                            "discovery_failures": [],
                        },
                    )
                )
            if checkpoint is not None:
                checkpoint(f"player_team_batch_{batch_index}_of_{len(grouped_scopes)}")
            continue

        covered_pairs = expected_pairs & set(result.covered_pairs)
        batch_failures = {
            pair: failure_kind
            for pair, failure_kind in result.failures_by_pair.items()
            if pair in expected_pairs and pair not in covered_pairs
        }
        discovery_failures.update(batch_failures)
        discovery_errors.extend(batch_failures.values())
        if progress is not None:
            for failure_kind in batch_failures.values():
                progress.record_failure_type(failure_kind)
        covered_params = [
            param
            for param in result.params
            if (str(param.get("season", "")), str(param.get("season_type", ""))) in covered_pairs
        ]
        if covered_pairs:
            store.upsert(
                covered_params,
                seasons=list(seasons),
                season_types=list(season_types),
                covered_pairs=covered_pairs,
            )
            persisted_pairs.update(covered_pairs)
            persisted_param_count += len(covered_params)
            if progress is not None:
                progress.mark_player_team_pairs(covered_pairs)
        if on_result is not None:
            batch_summary = {
                "kind": "player_team_season_workload",
                "seasons": list(seasons),
                "season_types": list(season_types),
                "requested_pair_count": len(expected_pairs),
                "covered_pair_count": len(covered_pairs),
                "requested_unique_season_count": len(seasons),
                "cached_pair_count": 0,
                "persisted_pair_count": len(covered_pairs),
                "persisted_param_count": len(covered_params),
                "refreshed_pair_count": len(
                    {pair for pair in covered_pairs if pair[0] in refresh_seasons}
                ),
                "grouped_scope_count": 1,
            }
            if covered_pairs:
                on_result(("seeded", batch_summary))
            unresolved_batch_pairs = expected_pairs - covered_pairs
            if unresolved_batch_pairs:
                on_result(
                    (
                        "failures",
                        {
                            **batch_summary,
                            "reason": "incomplete_pair_coverage",
                            "missing_pairs": _pair_summary_rows(unresolved_batch_pairs),
                            "discovery_errors": sorted(set(batch_failures.values())),
                            "discovery_failures": _pair_failure_summary_rows(batch_failures),
                        },
                    )
                )
        if checkpoint is not None:
            checkpoint(f"player_team_batch_{batch_index}_of_{len(grouped_scopes)}")

    resolved_pairs = cached_pairs | persisted_pairs
    unresolved_pairs = requested_pairs - resolved_pairs
    summary = {
        "kind": "player_team_season_workload",
        "seasons": requested_seasons,
        "season_types": requested_season_types,
        "requested_pair_count": len(requested_pairs),
        "covered_pair_count": len(resolved_pairs),
        "requested_unique_season_count": len(requested_seasons),
        "cached_pair_count": len(cached_pairs),
        "persisted_pair_count": len(persisted_pairs),
        "persisted_param_count": persisted_param_count,
        "refreshed_pair_count": len(
            {pair for pair in persisted_pairs if pair[0] in refresh_seasons}
        ),
        "grouped_scope_count": len(grouped_scopes),
    }
    if on_result is not None:
        if not grouped_scopes:
            on_result(("skipped", {**summary, "reason": "already_cached_complete"}))
        return []
    if unresolved_pairs:
        return [
            (
                "failures",
                {
                    **summary,
                    "reason": "incomplete_pair_coverage",
                    "missing_pairs": _pair_summary_rows(unresolved_pairs),
                    "discovery_errors": sorted(set(discovery_errors)),
                    "discovery_failures": _pair_failure_summary_rows(
                        {
                            pair: failure_kind
                            for pair, failure_kind in discovery_failures.items()
                            if pair in unresolved_pairs
                        }
                    ),
                },
            )
        ]
    if persisted_pairs:
        return [("seeded", summary)]
    return [("skipped", {**summary, "reason": "already_cached_complete"})]


def _sort_summary_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            str(item.get("kind", "")),
            tuple(str(value) for value in item.get("seasons", [])),
            str(item.get("reason", "")),
        ),
    )


def _failure_type_names(failures: list[dict[str, Any]]) -> list[str]:
    names: set[str] = set()
    for failure in failures:
        failure_type = failure.get("failure_type")
        if failure_type:
            names.add(str(failure_type))
        discovery_errors = failure.get("discovery_errors", [])
        if isinstance(discovery_errors, list):
            names.update(str(value) for value in discovery_errors if value)
    return sorted(names)


def _build_seed_summary(
    *,
    manifest_path: Path,
    manifest_sha256: str,
    scopes: tuple[DiscoveryArtifactScope, ...],
    requested_game_pairs: set[tuple[str, str]],
    requested_player_team_pairs: set[tuple[str, str]],
    seeded: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    failures: list[dict[str, Any]],
    progress: _SeedProgress,
    status: str,
    phase: str,
    checkpoint_sequence: int,
    deadline_seconds: float,
    failure_type: str | None = None,
    transient_failure: dict[str, Any] | None = None,
) -> dict[str, Any]:
    reported_failures = [*failures]
    if transient_failure is not None:
        reported_failures.append(transient_failure)
    failure_type_set = set(_failure_type_names(reported_failures))
    failure_type_set.update(progress.observed_failure_types)
    if failure_type is not None and failure_type != "MultipleFailures":
        failure_type_set.add(failure_type)
    failure_type_set.discard("MultipleFailures")
    substantive_failure_types = failure_type_set - {"InProgress", "NotStarted"}
    if substantive_failure_types:
        failure_type_set = substantive_failure_types
    failure_types = sorted(failure_type_set)

    if status == "complete":
        resolved_failure_type = None
        failure_types = []
    elif len(failure_types) == 1:
        resolved_failure_type = failure_types[0]
    elif failure_types:
        resolved_failure_type = "MultipleFailures"
    else:
        resolved_failure_type = failure_type or "CoverageIncomplete"

    return {
        "summary_schema_version": 2,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "status": status,
        "phase": phase,
        "checkpoint_sequence": checkpoint_sequence,
        "deadline_seconds": deadline_seconds,
        "failure_type": resolved_failure_type,
        "failure_types": failure_types,
        "scope_count": len(scopes),
        "game_combo_count": len(requested_game_pairs),
        "player_team_season_pair_count": len(requested_player_team_pairs),
        "player_team_season_unique_season_count": len(
            {season for season, _season_type in requested_player_team_pairs}
        ),
        "total_scope_count": (
            len(scopes) + len(requested_game_pairs) + len(requested_player_team_pairs)
        ),
        "seeded_count": len(seeded),
        "skipped_count": len(skipped),
        "failure_count": len(reported_failures),
        "seeded": _sort_summary_items(seeded),
        "skipped": _sort_summary_items(skipped),
        "failures": _sort_summary_items(reported_failures),
        **progress.attestation(),
    }


def _bootstrap_failure_summary(
    *,
    manifest_path: Path,
    manifest_sha256: str | None,
    duckdb_path: Path,
    deadline_seconds: float,
    failure_type: str,
) -> dict[str, Any]:
    failure = {
        "kind": "seed_run",
        "reason": "planning_failed",
        "phase": "planning",
        "failure_type": failure_type,
    }
    empty_counts = {
        "player_scope_count": 0,
        "player_season_count": 0,
        "game_combo_count": 0,
        "player_team_season_pair_count": 0,
        "exact_unit_count": 0,
    }
    empty_units = {
        "player_scopes": [],
        "player_seasons": [],
        "game_combos": [],
        "player_team_season_pairs": [],
    }
    return {
        "summary_schema_version": 2,
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "status": "incomplete",
        "phase": "planning",
        "checkpoint_sequence": 1,
        "deadline_seconds": deadline_seconds,
        "failure_type": failure_type,
        "failure_types": [failure_type],
        "requested_units_known": False,
        "duckdb_path": str(duckdb_path),
        "scope_count": 0,
        "game_combo_count": 0,
        "player_team_season_pair_count": 0,
        "player_team_season_unique_season_count": 0,
        "total_scope_count": 0,
        "seeded_count": 0,
        "skipped_count": 0,
        "failure_count": 1,
        "seeded": [],
        "skipped": [],
        "failures": [failure],
        "requested_exact_unit_count": 0,
        "covered_exact_unit_count": 0,
        "missing_exact_unit_count": 0,
        "coverage": {
            "requested": dict(empty_counts),
            "covered": dict(empty_counts),
            "missing": dict(empty_counts),
        },
        "requested_units": dict(empty_units),
        "covered_units": dict(empty_units),
        "missing_units": dict(empty_units),
        "artifacts": {
            "discovery_artifact_dir": str(
                duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
            ),
            "player_scope_artifacts": [],
            "player_season_artifacts": [],
            "game_combo_artifacts": [],
            "player_team_season_workload": None,
        },
    }


async def seed_player_discovery_artifacts(
    *,
    manifest_path: Path,
    duckdb_path: Path,
    summary_path: Path | None = None,
    deadline_seconds: float | None = None,
) -> dict[str, Any]:
    effective_deadline = _seed_deadline_seconds()
    if deadline_seconds is not None:
        if math.isfinite(deadline_seconds) and deadline_seconds > 0:
            effective_deadline = min(
                float(deadline_seconds),
                float(DEFAULT_DISCOVERY_SEED_DEADLINE_SECONDS),
            )
        else:
            logger.warning(
                "invalid discovery seed deadline {!r}; using {}",
                deadline_seconds,
                effective_deadline,
            )

    manifest_sha256: str | None = None
    try:
        manifest_bytes = manifest_path.read_bytes()
        manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
        manifest = json.loads(manifest_bytes)
        scopes = player_discovery_scopes(manifest)
        requested_game_pairs = set(game_discovery_pairs(manifest))
        requested_player_team_pairs = set(player_team_season_pairs(manifest))
        store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
        workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
        workload_store.promote_legacy_v3()
    except Exception as exc:
        summary = _bootstrap_failure_summary(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            duckdb_path=duckdb_path,
            deadline_seconds=effective_deadline,
            failure_type=type(exc).__name__,
        )
        if summary_path is not None:
            _atomic_write_json(summary_path, summary)
        return summary

    progress = _SeedProgress(
        scopes=scopes,
        game_pairs=requested_game_pairs,
        player_team_pairs=requested_player_team_pairs,
        duckdb_path=duckdb_path,
        workload_store=workload_store,
    )
    seeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    checkpoint_sequence = 0
    current_phase = "initialized"
    if manifest_sha256 is None:
        raise RuntimeError("readable extraction manifest did not produce a SHA-256")

    def _record_result(result: SeedResult) -> None:
        bucket, item = result
        if bucket == "seeded":
            seeded.append(item)
        elif bucket == "skipped":
            skipped.append(item)
        elif bucket == "failures":
            failures.append(item)
        else:
            raise RuntimeError(f"unexpected discovery seed result bucket: {bucket}")

    def _record_results(results: list[SeedResult]) -> None:
        for result in results:
            _record_result(result)

    def _write_checkpoint(phase: str) -> None:
        nonlocal checkpoint_sequence
        checkpoint_sequence += 1
        initial = checkpoint_sequence == 1
        observed_failure_types = sorted(progress.observed_failure_types)
        if initial:
            checkpoint_failure_type = "NotStarted"
            checkpoint_reason = "not_started"
        elif len(observed_failure_types) == 1:
            checkpoint_failure_type = observed_failure_types[0]
            checkpoint_reason = "batch_failed"
        elif observed_failure_types:
            checkpoint_failure_type = "MultipleFailures"
            checkpoint_reason = "batch_failed"
        else:
            checkpoint_failure_type = "InProgress"
            checkpoint_reason = "in_progress"
        transient_failure = {
            "kind": "seed_run",
            "reason": checkpoint_reason,
            "phase": phase,
            "failure_type": checkpoint_failure_type,
        }
        summary = _build_seed_summary(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            scopes=scopes,
            requested_game_pairs=requested_game_pairs,
            requested_player_team_pairs=requested_player_team_pairs,
            seeded=seeded,
            skipped=skipped,
            failures=failures,
            progress=progress,
            status="incomplete",
            phase=phase,
            checkpoint_sequence=checkpoint_sequence,
            deadline_seconds=effective_deadline,
            failure_type=checkpoint_failure_type,
            transient_failure=transient_failure,
        )
        if summary_path is not None:
            _atomic_write_json(summary_path, summary)

    def _write_final_summary(*, status: str, failure_type: str | None) -> dict[str, Any]:
        nonlocal checkpoint_sequence, current_phase
        current_phase = "complete" if status == "complete" else current_phase
        checkpoint_sequence += 1
        summary = _build_seed_summary(
            manifest_path=manifest_path,
            manifest_sha256=manifest_sha256,
            scopes=scopes,
            requested_game_pairs=requested_game_pairs,
            requested_player_team_pairs=requested_player_team_pairs,
            seeded=seeded,
            skipped=skipped,
            failures=failures,
            progress=progress,
            status=status,
            phase=current_phase,
            checkpoint_sequence=checkpoint_sequence,
            deadline_seconds=effective_deadline,
            failure_type=failure_type,
        )
        if summary_path is not None:
            _atomic_write_json(summary_path, summary)
        return summary

    _write_checkpoint("initialized")
    timeout_guard = asyncio.timeout(effective_deadline)
    try:
        async with timeout_guard:
            current_phase = "registry_discovery"
            registry.discover()
            discovery = EntityDiscovery(registry)
            seed_concurrency = _seed_concurrency()
            mutable_season = current_season()
            refresh_seasons = frozenset({mutable_season})

            single_season_scopes = [scope for scope in scopes if len(scope.seasons) == 1]
            aggregate_scopes = [scope for scope in scopes if len(scope.seasons) != 1]
            logger.info(
                "seeding {} single-season discovery scopes; fallback concurrency {}",
                len(single_season_scopes),
                seed_concurrency,
            )
            cached_results: list[SeedResult] = []
            pending_single_season_scopes: list[DiscoveryArtifactScope] = []
            for scope in single_season_scopes:
                cached = store.load_ids(scope)
                if cached and scope.seasons[0] != mutable_season:
                    progress.mark_player_scope(scope)
                    cached_results.append(
                        (
                            "skipped",
                            {
                                "kind": scope.kind,
                                "seasons": list(scope.seasons),
                                "count": len(cached),
                                "reason": "already_cached",
                            },
                        )
                    )
                else:
                    pending_single_season_scopes.append(scope)
            _record_results(cached_results)
            _write_checkpoint("player_cache")

            mutable_single_season_scopes = [
                scope
                for scope in pending_single_season_scopes
                if scope.seasons[0] == mutable_season
            ]
            stable_single_season_scopes = [
                scope
                for scope in pending_single_season_scopes
                if scope.seasons[0] != mutable_season
            ]
            current_phase = "player_bulk"
            (
                _bulk_results,
                fallback_single_season_scopes,
            ) = await _seed_single_season_scopes_from_bulk(
                scopes=stable_single_season_scopes,
                store=store,
                discovery=discovery,
                progress=progress,
                checkpoint=_write_checkpoint,
                on_result=_record_result,
            )
            _write_checkpoint("player_bulk")

            fallback_single_season_scopes.extend(mutable_single_season_scopes)
            if fallback_single_season_scopes:
                logger.info(
                    (
                        "falling back to targeted discovery for {} single-season scopes "
                        "with concurrency {}"
                    ),
                    len(fallback_single_season_scopes),
                    seed_concurrency,
                )
            current_phase = "player_fallback"
            _fallback_results = await _seed_scopes_concurrently(
                scopes=fallback_single_season_scopes,
                store=store,
                discovery=discovery,
                concurrency=seed_concurrency,
                force_refresh_seasons=refresh_seasons,
                progress=progress,
                checkpoint=_write_checkpoint,
                on_result=_record_result,
            )
            _write_checkpoint("player_fallback")

            pending_aggregate_refresh_seasons = set(refresh_seasons) - {
                scope.seasons[0] for scope in mutable_single_season_scopes
            }
            for aggregate_index, scope in enumerate(aggregate_scopes, start=1):
                current_phase = f"player_aggregate_{aggregate_index}_of_{len(aggregate_scopes)}"
                scope_refresh_seasons = frozenset(scope.seasons) & pending_aggregate_refresh_seasons
                result = await _seed_scope(
                    scope=scope,
                    store=store,
                    discovery=discovery,
                    refresh_seasons=frozenset(scope_refresh_seasons),
                    progress=progress,
                )
                _record_results([result])
                pending_aggregate_refresh_seasons -= scope_refresh_seasons
                _write_checkpoint(current_phase)

            current_phase = "game_discovery"
            game_results = await _seed_game_discovery_pairs(
                requested_pairs=requested_game_pairs,
                store=store,
                discovery=discovery,
                refresh_seasons=refresh_seasons,
                progress=progress,
                checkpoint=_write_checkpoint,
                on_result=_record_result,
            )
            _record_results(game_results)
            _write_checkpoint("game_complete")

            current_phase = "player_team_discovery"
            player_team_results = await _seed_player_team_season_pairs(
                requested_pairs=requested_player_team_pairs,
                store=workload_store,
                discovery=discovery,
                refresh_seasons=refresh_seasons,
                progress=progress,
                checkpoint=_write_checkpoint,
                on_result=_record_result,
            )
            _record_results(player_team_results)
            _write_checkpoint("player_team_complete")
    except TimeoutError as exc:
        deadline_expired = timeout_guard.expired()
        failure_type = type(exc).__name__
        failures.append(
            {
                "kind": "seed_run",
                "reason": "deadline_exceeded" if deadline_expired else "unhandled_exception",
                "phase": current_phase,
                "failure_type": failure_type,
            }
        )
        logger.error(
            "discovery seeding stopped in phase {} after {}",
            current_phase,
            failure_type,
        )
        return _write_final_summary(status="incomplete", failure_type=failure_type)
    except Exception as exc:
        failure_type = type(exc).__name__
        failures.append(
            {
                "kind": "seed_run",
                "reason": "unhandled_exception",
                "phase": current_phase,
                "failure_type": failure_type,
            }
        )
        logger.error(
            "discovery seeding stopped in phase {} after {}",
            current_phase,
            failure_type,
        )
        return _write_final_summary(status="incomplete", failure_type=failure_type)

    if failures or not progress.is_complete():
        if not failures:
            failures.append(
                {
                    "kind": "seed_run",
                    "reason": "incomplete_coverage",
                    "phase": current_phase,
                    "failure_type": "CoverageIncomplete",
                }
            )
        failure_types = _failure_type_names(failures)
        if not failure_types:
            final_failure_type = "CoverageIncomplete"
        elif len(failure_types) == 1:
            final_failure_type = failure_types[0]
        else:
            final_failure_type = "MultipleFailures"
        return _write_final_summary(
            status="incomplete",
            failure_type=final_failure_type,
        )
    return _write_final_summary(status="complete", failure_type=None)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed full-extraction discovery artifacts.")
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--duckdb-path", type=Path, default=Path("data/nbadb/nba.duckdb"))
    parser.add_argument(
        "--summary-path",
        type=Path,
        default=Path("artifacts/discovery/discovery-seed-summary.json"),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.duckdb_path.parent.mkdir(parents=True, exist_ok=True)
    args.summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary = asyncio.run(
        seed_player_discovery_artifacts(
            manifest_path=args.manifest_path,
            duckdb_path=args.duckdb_path,
            summary_path=args.summary_path,
        )
    )
    print(json.dumps(summary, sort_keys=True))
    return 0 if summary.get("status") == "complete" and not summary["failure_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
