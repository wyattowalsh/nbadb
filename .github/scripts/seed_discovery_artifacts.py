from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
from typing import Any

from loguru import logger

from nbadb.extract.registry import registry
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.player_directory_snapshot import player_ids_by_season_from_snapshot
from nbadb.orchestrate.seasons import season_range

PLAYER_DISCOVERY_PATTERNS = frozenset({"player", "player_season"})
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


async def _seed_scope(
    *,
    scope: DiscoveryArtifactScope,
    store: DiscoveryArtifactStore,
    discovery: EntityDiscovery,
) -> tuple[str, dict[str, Any]]:
    cached = store.load_ids(scope)
    if cached:
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
        per_season_ids = store.load_ids_for_seasons(
            kind="player_ids_all",
            seasons=scope.seasons,
            variant="historical",
        )
        if per_season_ids is None:
            per_season_ids = []
            for season in scope.seasons:
                season_scope = DiscoveryArtifactScope(
                    kind="player_ids_all",
                    seasons=(season,),
                    season_types=(),
                    variant="historical",
                )
                season_ids = store.load_ids(season_scope)
                if not season_ids:
                    season_ids = await discovery.discover_all_player_ids(season=season)
                    if season_ids:
                        store.upsert_ids(
                            season_scope,
                            season_ids,
                            provenance="workflow-discovery-seed",
                        )
                per_season_ids.extend(season_ids)
            per_season_ids = sorted({int(value) for value in per_season_ids})
        ids = per_season_ids

    if not ids:
        return (
            "failures",
            {
                "kind": scope.kind,
                "seasons": list(scope.seasons),
                "reason": "no_ids",
            },
        )

    stored = store.upsert_ids(scope, ids, provenance="workflow-discovery-seed")
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
) -> list[tuple[str, dict[str, Any]]]:
    if not scopes:
        return []

    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _run(scope: DiscoveryArtifactScope) -> tuple[str, dict[str, Any]]:
        async with semaphore:
            return await _seed_scope(scope=scope, store=store, discovery=discovery)

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
    store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    registry.discover()
    discovery = EntityDiscovery(registry)
    seed_concurrency = _seed_concurrency()

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
        if cached:
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

    bulk_results, fallback_single_season_scopes = await _seed_single_season_scopes_from_bulk(
        scopes=pending_single_season_scopes,
        store=store,
        discovery=discovery,
    )
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
    )
    results = [*cached_results, *bulk_results, *fallback_results]
    for scope in aggregate_scopes:
        results.append(await _seed_scope(scope=scope, store=store, discovery=discovery))

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
