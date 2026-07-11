from __future__ import annotations

import argparse
import asyncio
import json
import os
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
) -> dict[str, list[int]]:
    semaphore = asyncio.Semaphore(_seed_concurrency())

    async def _discover(season: str) -> tuple[str, list[int]]:
        async with semaphore:
            return season, await discovery.discover_all_player_ids(season=season)

    results = await asyncio.gather(*(_discover(season) for season in seasons))
    return {season: ids for season, ids in results if ids}


async def _seed_scope(
    *,
    scope: DiscoveryArtifactScope,
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    refresh_seasons: frozenset[str] = frozenset(),
) -> tuple[str, dict[str, Any]]:
    cached = store.load_ids(scope)
    scoped_refresh_seasons = refresh_seasons & frozenset(scope.seasons)
    if cached and len(scope.seasons) == 1 and not scoped_refresh_seasons:
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
        ids = await discovery.discover_all_player_ids(season=season)
    else:
        logger.info(
            "seeding aggregate historical player discovery for {} seasons",
            len(scope.seasons),
        )
        snapshot_ids_by_season = player_ids_by_season_from_snapshot(list(scope.seasons))
        ids_by_season: dict[str, list[int]] = {}
        sources_by_season: dict[str, set[str]] = {}

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

        if scoped_refresh_seasons:
            refresh_targets = [
                season for season in scope.seasons if season in scoped_refresh_seasons
            ]
            logger.info(
                "target-refreshing {} mutable aggregate player discovery seasons",
                len(refresh_targets),
            )
            refreshed_ids_by_season = await _discover_targeted_ids_by_season(
                discovery=discovery,
                seasons=refresh_targets,
            )
            for season in refresh_targets:
                refreshed_ids = refreshed_ids_by_season.get(season, [])
                if not refreshed_ids:
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
                store.upsert_ids(
                    _player_season_scope(season),
                    season_ids,
                    provenance="workflow-discovery-seed-bulk",
                )

        missing_seasons = [season for season in scope.seasons if not ids_by_season.get(season)]
        targeted_missing_seasons = [
            season for season in missing_seasons if season not in scoped_refresh_seasons
        ]
        if targeted_missing_seasons:
            logger.info(
                "target-seeding {} unresolved aggregate player discovery seasons",
                len(targeted_missing_seasons),
            )
            targeted_ids_by_season = await _discover_targeted_ids_by_season(
                discovery=discovery,
                seasons=targeted_missing_seasons,
            )
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
            },
        )

    if cached == ids:
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
) -> list[tuple[str, dict[str, Any]]]:
    if not scopes:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(scope: DiscoveryArtifactScope) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            return await _seed_scope(
                scope=scope,
                store=store,
                discovery=discovery,
                refresh_seasons=force_refresh_seasons,
            )

    return await asyncio.gather(*(_run(scope) for scope in scopes))


def _seed_scopes_from_ids_by_season(
    *,
    scopes: list[DiscoveryArtifactScope],
    store: DiscoveryArtifactStore,
    ids_by_season: dict[str, list[int]],
    provenance: str,
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
) -> tuple[list[tuple[str, dict[str, Any]]], list[DiscoveryArtifactScope]]:
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
    )
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
    )
    return [*snapshot_results, *bulk_results], fallback_scopes


def _combo_scope(season: str, season_type: str) -> DiscoveryArtifactScope:
    return DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=(season,),
        season_types=(season_type,),
    )


def _pair_summary_rows(pairs: set[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"season": season, "season_type": season_type} for season, season_type in sorted(pairs)]


async def _seed_game_discovery_pairs(
    *,
    requested_pairs: set[tuple[str, str]],
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
    refresh_seasons: frozenset[str] = frozenset(),
) -> list[tuple[str, dict[str, Any]]]:
    if not requested_pairs:
        return []

    cached_pairs = {
        pair
        for pair in requested_pairs
        if pair[0] not in refresh_seasons
        and store.load_game_log_frame(_combo_scope(*pair)) is not None
    }
    missing_pairs = requested_pairs - cached_pairs
    grouped_scopes = _group_exact_pairs(missing_pairs)
    persisted_pairs: set[tuple[str, str]] = set()
    discovery_errors: list[str] = []

    for seasons, season_types in grouped_scopes:
        expected_pairs = {
            (season, season_type) for season in seasons for season_type in season_types
        }
        logger.info(
            "seeding exact game discovery for {} combos across {} seasons",
            len(expected_pairs),
            len(seasons),
        )
        try:
            result = await discovery.discover_game_ids_result(
                list(seasons),
                season_types=list(season_types),
            )
        except Exception as exc:
            logger.error(
                "exact game discovery failed for seasons={} season_types={}: {}",
                list(seasons),
                list(season_types),
                type(exc).__name__,
            )
            discovery_errors.append(type(exc).__name__)
            continue

        complete_frames = {
            pair: frame
            for pair, frame in result.frames_by_combo.items()
            if pair in expected_pairs and pair in result.covered_combos
        }
        if complete_frames:
            store.upsert_game_log_combo_frames(
                complete_frames,
                provenance="workflow-discovery-seed",
            )
            persisted_pairs.update(complete_frames)

    resolved_pairs = cached_pairs | persisted_pairs
    unresolved_pairs = requested_pairs - resolved_pairs
    summary = {
        "kind": "league_game_log",
        "seasons": sorted({season for season, _season_type in requested_pairs}),
        "season_types": list(
            _ordered_season_types({season_type for _season, season_type in requested_pairs})
        ),
        "requested_combo_count": len(requested_pairs),
        "cached_combo_count": len(cached_pairs),
        "persisted_combo_count": len(persisted_pairs),
        "refreshed_combo_count": len(
            {pair for pair in requested_pairs if pair[0] in refresh_seasons}
        ),
        "grouped_scope_count": len(grouped_scopes),
    }
    if unresolved_pairs:
        return [
            (
                "failures",
                {
                    **summary,
                    "reason": "incomplete_combo_coverage",
                    "missing_combos": _pair_summary_rows(unresolved_pairs),
                    "discovery_errors": discovery_errors,
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
    missing_pairs = requested_pairs - cached_pairs
    grouped_scopes = _group_exact_pairs(missing_pairs)
    persisted_pairs: set[tuple[str, str]] = set()
    persisted_param_count = 0
    discovery_errors: list[str] = []

    for seasons, season_types in grouped_scopes:
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
            logger.error(
                "exact player/team discovery failed for seasons={} season_types={}: {}",
                list(seasons),
                list(season_types),
                type(exc).__name__,
            )
            discovery_errors.append(type(exc).__name__)
            continue

        covered_pairs = expected_pairs & set(result.covered_pairs)
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

    resolved_pairs = cached_pairs | persisted_pairs
    unresolved_pairs = requested_pairs - resolved_pairs
    summary = {
        "kind": "player_team_season_workload",
        "seasons": requested_seasons,
        "season_types": requested_season_types,
        "requested_pair_count": len(requested_pairs),
        "requested_unique_season_count": len(requested_seasons),
        "cached_pair_count": len(cached_pairs),
        "persisted_pair_count": len(persisted_pairs),
        "persisted_param_count": persisted_param_count,
        "refreshed_pair_count": len(
            {pair for pair in requested_pairs if pair[0] in refresh_seasons}
        ),
        "grouped_scope_count": len(grouped_scopes),
    }
    if unresolved_pairs:
        return [
            (
                "failures",
                {
                    **summary,
                    "reason": "incomplete_pair_coverage",
                    "missing_pairs": _pair_summary_rows(unresolved_pairs),
                    "discovery_errors": discovery_errors,
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


async def seed_player_discovery_artifacts(
    *,
    manifest_path: Path,
    duckdb_path: Path,
) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    scopes = player_discovery_scopes(manifest)
    requested_game_pairs = set(game_discovery_pairs(manifest))
    requested_player_team_pairs = set(player_team_season_pairs(manifest))
    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
    registry.discover()
    discovery = EntityDiscovery(registry)
    seed_concurrency = _seed_concurrency()
    mutable_season = current_season()
    refresh_seasons = frozenset({mutable_season})

    seeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    single_season_scopes = [scope for scope in scopes if len(scope.seasons) == 1]
    aggregate_scopes = [scope for scope in scopes if len(scope.seasons) != 1]

    logger.info(
        "seeding {} single-season discovery scopes; fallback concurrency {}",
        len(single_season_scopes),
        seed_concurrency,
    )
    cached_results: list[tuple[str, dict[str, Any]]] = []
    pending_single_season_scopes: list[DiscoveryArtifactScope] = []
    for scope in single_season_scopes:
        cached = store.load_ids(scope)
        if cached and scope.seasons[0] != mutable_season:
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

    mutable_single_season_scopes = [
        scope for scope in pending_single_season_scopes if scope.seasons[0] == mutable_season
    ]
    stable_single_season_scopes = [
        scope for scope in pending_single_season_scopes if scope.seasons[0] != mutable_season
    ]
    bulk_results, fallback_single_season_scopes = await _seed_single_season_scopes_from_bulk(
        scopes=stable_single_season_scopes,
        store=store,
        discovery=discovery,
    )
    fallback_single_season_scopes.extend(mutable_single_season_scopes)
    if fallback_single_season_scopes:
        logger.info(
            "falling back to targeted discovery for {} single-season scopes with concurrency {}",
            len(fallback_single_season_scopes),
            seed_concurrency,
        )
    fallback_results = await _seed_scopes_concurrently(
        scopes=fallback_single_season_scopes,
        store=store,
        discovery=discovery,
        concurrency=seed_concurrency,
        force_refresh_seasons=refresh_seasons,
    )
    results = [*cached_results, *bulk_results, *fallback_results]
    pending_aggregate_refresh_seasons = set(refresh_seasons) - {
        scope.seasons[0] for scope in mutable_single_season_scopes
    }
    for scope in aggregate_scopes:
        scope_refresh_seasons = frozenset(scope.seasons) & pending_aggregate_refresh_seasons
        results.append(
            await _seed_scope(
                scope=scope,
                store=store,
                discovery=discovery,
                refresh_seasons=frozenset(scope_refresh_seasons),
            )
        )
        pending_aggregate_refresh_seasons -= scope_refresh_seasons
    results.extend(
        await _seed_game_discovery_pairs(
            requested_pairs=requested_game_pairs,
            store=store,
            discovery=discovery,
            refresh_seasons=refresh_seasons,
        )
    )
    results.extend(
        await _seed_player_team_season_pairs(
            requested_pairs=requested_player_team_pairs,
            store=workload_store,
            discovery=discovery,
            refresh_seasons=refresh_seasons,
        )
    )

    for bucket, item in results:
        if bucket == "seeded":
            seeded.append(item)
        elif bucket == "skipped":
            skipped.append(item)
        elif bucket == "failures":
            failures.append(item)
        else:
            raise RuntimeError(f"unexpected discovery seed result bucket: {bucket}")

    return {
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
        "failure_count": len(failures),
        "seeded": _sort_summary_items(seeded),
        "skipped": _sort_summary_items(skipped),
        "failures": _sort_summary_items(failures),
    }


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
        )
    )
    args.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary, sort_keys=True))
    return 1 if int(summary["failure_count"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())
