from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from loguru import logger

from nbadb.extract.registry import registry
from nbadb.orchestrate.discovery import EntityDiscovery
from nbadb.orchestrate.discovery_artifacts import DiscoveryArtifactScope, DiscoveryArtifactStore
from nbadb.orchestrate.seasons import season_range

PLAYER_DISCOVERY_PATTERNS = frozenset({"player", "player_season"})


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

    seeded: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []

    for scope in scopes:
        cached = store.load_ids(scope)
        if cached:
            skipped.append(
                {
                    "kind": scope.kind,
                    "seasons": list(scope.seasons),
                    "count": len(cached),
                    "reason": "already_cached",
                }
            )
            continue

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
            failures.append(
                {
                    "kind": scope.kind,
                    "seasons": list(scope.seasons),
                    "reason": "no_ids",
                }
            )
            continue
        stored = store.upsert_ids(scope, ids, provenance="workflow-discovery-seed")
        seeded.append(
            {
                "kind": scope.kind,
                "seasons": list(scope.seasons),
                "count": len(stored),
            }
        )

    return {
        "scope_count": len(scopes),
        "seeded_count": len(seeded),
        "skipped_count": len(skipped),
        "failure_count": len(failures),
        "seeded": seeded,
        "skipped": skipped,
        "failures": failures,
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
