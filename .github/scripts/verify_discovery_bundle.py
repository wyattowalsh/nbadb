from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, cast

from nbadb.core.types import SeasonType
from nbadb.orchestrate.discovery_artifacts import (
    ArtifactKind,
    DiscoveryArtifactScope,
    DiscoveryArtifactStore,
)
from nbadb.orchestrate.seasons import season_range
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

_PLAYER_DISCOVERY_PATTERNS = frozenset({"player", "player_season"})
_GAME_DISCOVERY_PATTERNS = frozenset({"game", "date"})
_PLAYER_TEAM_SEASON_PATTERN = "player_team_season"
_DEFAULT_SEASON_TYPES = tuple(season_type.value for season_type in SeasonType)


class DiscoveryBundleVerificationError(RuntimeError):
    """Raised when a discovery bundle cannot prove complete exact coverage."""


def _read_object(path: Path, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise DiscoveryBundleVerificationError(f"{label} is unreadable: {path}") from exc
    if not isinstance(payload, dict):
        raise DiscoveryBundleVerificationError(f"{label} must be a JSON object: {path}")
    return payload


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoveryBundleVerificationError(message)


def _mapping(value: object, *, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise DiscoveryBundleVerificationError(f"{label} must be an object")
    return cast("dict[str, Any]", value)


def _rows(value: object, *, label: str) -> list[dict[str, Any]]:
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise DiscoveryBundleVerificationError(f"{label} must be an array of objects")
    return cast("list[dict[str, Any]]", value)


def _strings(value: object, *, label: str) -> tuple[str, ...]:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item for item in value):
        raise DiscoveryBundleVerificationError(f"{label} must be an array of non-empty strings")
    return tuple(cast("list[str]", value))


def _split_csv(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return tuple(part.strip() for part in value.split(",") if part.strip())
    if isinstance(value, list | tuple):
        return tuple(str(part).strip() for part in value if str(part).strip())
    return ()


def _manifest_lanes(manifest: dict[str, Any]) -> list[dict[str, Any]]:
    matrix = manifest.get("github_matrix")
    if isinstance(matrix, dict):
        include = matrix.get("include")
        if isinstance(include, list):
            return [row for row in include if isinstance(row, dict)]
    lanes = manifest.get("lanes")
    if isinstance(lanes, list):
        return [row for row in lanes if isinstance(row, dict)]
    return []


def _lane_seasons(lane: dict[str, Any]) -> tuple[str, ...]:
    start = lane.get("season_start")
    end = lane.get("season_end")
    if start in (None, "") or end in (None, ""):
        return tuple(season_range())
    return tuple(season_range(int(start), int(end)))


def _lane_season_types(lane: dict[str, Any]) -> tuple[str, ...]:
    configured = _split_csv(lane.get("season_types"))
    values = set(configured or _DEFAULT_SEASON_TYPES)
    order = {value: index for index, value in enumerate(_DEFAULT_SEASON_TYPES)}
    return tuple(sorted(values, key=lambda value: (order.get(value, len(order)), value)))


def _lane_requests(lane: dict[str, Any], patterns: frozenset[str]) -> bool:
    configured = set(_split_csv(lane.get("patterns")))
    return not configured or bool(configured & patterns)


def _expected_manifest_units(
    manifest: dict[str, Any],
) -> tuple[
    set[DiscoveryArtifactScope],
    set[DiscoveryArtifactScope],
    set[DiscoveryArtifactScope],
    set[tuple[str, str]],
]:
    player_scopes: set[DiscoveryArtifactScope] = set()
    game_scopes: set[DiscoveryArtifactScope] = set()
    workload_pairs: set[tuple[str, str]] = set()
    for lane in _manifest_lanes(manifest):
        if lane.get("resume_only"):
            continue
        patterns = set(_split_csv(lane.get("patterns")))
        seasons = _lane_seasons(lane)
        season_types = _lane_season_types(lane)
        if patterns & _PLAYER_DISCOVERY_PATTERNS and seasons:
            if "player_season" in patterns:
                player_scopes.update(
                    DiscoveryArtifactScope(
                        kind="player_ids_all",
                        seasons=(season,),
                        season_types=(),
                        variant="historical",
                    )
                    for season in seasons
                )
            player_scopes.add(
                DiscoveryArtifactScope(
                    kind="player_ids_all",
                    seasons=seasons,
                    season_types=(),
                    variant="historical",
                )
            )
        if _lane_requests(lane, _GAME_DISCOVERY_PATTERNS):
            game_scopes.update(
                DiscoveryArtifactScope(
                    kind="league_game_log",
                    seasons=(season,),
                    season_types=(season_type,),
                )
                for season in seasons
                for season_type in season_types
            )
        if _lane_requests(lane, frozenset({_PLAYER_TEAM_SEASON_PATTERN})):
            workload_pairs.update(
                (season, season_type) for season in seasons for season_type in season_types
            )
    player_season_scopes = {
        DiscoveryArtifactScope(
            kind="player_ids_all",
            seasons=(season,),
            season_types=(),
            variant="historical",
        )
        for scope in player_scopes
        for season in scope.seasons
    }
    return player_scopes, player_season_scopes, game_scopes, workload_pairs


def _sha256_path(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise DiscoveryBundleVerificationError(f"manifest is unreadable: {path}") from exc


def _player_scope(row: dict[str, Any], *, label: str) -> DiscoveryArtifactScope:
    kind = row.get("kind")
    _require(kind in {"player_ids_active", "player_ids_all"}, f"{label} has invalid kind")
    seasons = _strings(row.get("seasons"), label=f"{label}.seasons")
    _require(bool(seasons), f"{label}.seasons must not be empty")
    season_types = _strings(row.get("season_types"), label=f"{label}.season_types")
    variant = row.get("variant")
    _require(isinstance(variant, str) and bool(variant), f"{label}.variant is invalid")
    scope = DiscoveryArtifactScope(
        kind=cast("ArtifactKind", kind),
        seasons=seasons,
        season_types=season_types,
        variant=cast("str", variant),
    )
    _require(row.get("scope_digest") == scope.digest(), f"{label} scope digest mismatch")
    return scope


def _game_scope(row: dict[str, Any], *, label: str) -> DiscoveryArtifactScope:
    season = row.get("season")
    season_type = row.get("season_type")
    _require(isinstance(season, str) and bool(season), f"{label}.season is invalid")
    _require(
        isinstance(season_type, str) and bool(season_type),
        f"{label}.season_type is invalid",
    )
    return DiscoveryArtifactScope(
        kind="league_game_log",
        seasons=(cast("str", season),),
        season_types=(cast("str", season_type),),
    )


def _player_season_scope(row: dict[str, Any], *, label: str) -> DiscoveryArtifactScope:
    season = row.get("season")
    _require(isinstance(season, str) and bool(season), f"{label}.season is invalid")
    return DiscoveryArtifactScope(
        kind="player_ids_all",
        seasons=(cast("str", season),),
        season_types=(),
        variant="historical",
    )


def _pair(row: dict[str, Any], *, label: str) -> tuple[str, str]:
    season = row.get("season")
    season_type = row.get("season_type")
    _require(isinstance(season, str) and bool(season), f"{label}.season is invalid")
    _require(
        isinstance(season_type, str) and bool(season_type),
        f"{label}.season_type is invalid",
    )
    return cast("str", season), cast("str", season_type)


def _verify_scope_attestations(
    *,
    rows: list[dict[str, Any]],
    scopes: set[DiscoveryArtifactScope],
    artifact_root: Path,
    label: str,
) -> None:
    _require(len(rows) == len(scopes), f"{label} count does not match requested scopes")
    rows_by_digest: dict[str, dict[str, Any]] = {}
    for index, row in enumerate(rows):
        digest = row.get("scope_digest")
        _require(isinstance(digest, str) and bool(digest), f"{label}[{index}] digest is invalid")
        digest = cast("str", digest)
        _require(digest not in rows_by_digest, f"{label} contains a duplicate scope digest")
        rows_by_digest[digest] = row

    for scope in scopes:
        digest = scope.digest()
        row = rows_by_digest.get(digest)
        _require(row is not None, f"{label} is missing scope {digest}")
        row = cast("dict[str, Any]", row)
        _require(row.get("kind") == scope.kind, f"{label} kind mismatch for {digest}")
        _require(row.get("seasons") == list(scope.seasons), f"{label} season mismatch for {digest}")
        _require(
            row.get("season_types") == list(scope.season_types),
            f"{label} season-type mismatch for {digest}",
        )
        _require(row.get("variant") == scope.variant, f"{label} variant mismatch for {digest}")

        manifest_path = artifact_root / f"{scope.kind}.{digest}.json"
        manifest = _read_object(manifest_path, label=f"{label} manifest")
        content = _mapping(manifest.get("content"), label=f"{label} manifest content")
        generation_name = content.get("path")
        content_sha256 = content.get("sha256")
        _require(
            isinstance(generation_name, str)
            and Path(generation_name).name == generation_name
            and (artifact_root / generation_name).is_file(),
            f"{label} generation is missing for {digest}",
        )
        _require(
            isinstance(content_sha256, str)
            and len(content_sha256) == 64
            and row.get("content_sha256") == content_sha256,
            f"{label} content digest mismatch for {digest}",
        )
        recorded_artifact_path = row.get("artifact_path")
        recorded_manifest_path = row.get("manifest_path")
        _require(
            isinstance(recorded_artifact_path, str)
            and Path(recorded_artifact_path).name == generation_name,
            f"{label} artifact path mismatch for {digest}",
        )
        _require(
            isinstance(recorded_manifest_path, str)
            and Path(recorded_manifest_path).name == manifest_path.name,
            f"{label} manifest path mismatch for {digest}",
        )


def verify_discovery_bundle(
    *,
    summary_path: Path,
    manifest_path: Path,
    duckdb_path: Path,
) -> dict[str, int]:
    summary = _read_object(summary_path, label="discovery seed summary")
    manifest = _read_object(manifest_path, label="lane manifest")
    manifest_lanes = _manifest_lanes(manifest)
    _require(bool(manifest_lanes), "lane manifest has no matrix lanes")
    _require(
        any(not lane.get("resume_only") for lane in manifest_lanes),
        "lane manifest has no active matrix lanes",
    )
    manifest_sha256 = _sha256_path(manifest_path)
    _require(summary.get("manifest_sha256") == manifest_sha256, "lane manifest digest mismatch")
    _require(
        isinstance(summary.get("manifest_path"), str)
        and Path(summary["manifest_path"]).name == manifest_path.name,
        "lane manifest path mismatch",
    )
    _require(summary.get("summary_schema_version") == 2, "unsupported seed summary version")
    _require(summary.get("status") == "complete", "seed summary status is not complete")
    _require(summary.get("phase") == "complete", "seed summary phase is not complete")
    _require(summary.get("failure_type") is None, "complete seed summary has a failure type")
    _require(summary.get("failure_types") == [], "complete seed summary has failure types")
    _require(summary.get("failure_count") == 0, "complete seed summary has failures")
    _require(
        summary.get("missing_exact_unit_count") == 0,
        "seed summary reports missing exact units",
    )

    coverage = _mapping(summary.get("coverage"), label="coverage")
    requested_counts = _mapping(coverage.get("requested"), label="coverage.requested")
    covered_counts = _mapping(coverage.get("covered"), label="coverage.covered")
    missing_counts = _mapping(coverage.get("missing"), label="coverage.missing")
    for key, value in missing_counts.items():
        _require(type(value) is int and value == 0, f"coverage.missing.{key} must be zero")

    requested = _mapping(summary.get("requested_units"), label="requested_units")
    player_scope_rows = _rows(
        requested.get("player_scopes"),
        label="requested_units.player_scopes",
    )
    player_season_rows = _rows(
        requested.get("player_seasons"),
        label="requested_units.player_seasons",
    )
    game_rows = _rows(requested.get("game_combos"), label="requested_units.game_combos")
    workload_rows = _rows(
        requested.get("player_team_season_pairs"),
        label="requested_units.player_team_season_pairs",
    )

    discovery_store = DiscoveryArtifactStore.from_duckdb_path(duckdb_path)
    player_scopes = {
        _player_scope(row, label=f"requested player scope {index}")
        for index, row in enumerate(player_scope_rows)
    }
    player_season_scopes = {
        _player_season_scope(row, label=f"requested player season {index}")
        for index, row in enumerate(player_season_rows)
    }
    game_scopes = {
        _game_scope(row, label=f"requested game combo {index}")
        for index, row in enumerate(game_rows)
    }

    for scope in sorted(
        player_scopes | player_season_scopes | game_scopes,
        key=lambda item: (item.kind, item.seasons, item.season_types, item.variant),
    ):
        frame = discovery_store.load_frame(scope)
        if frame is None:
            raise DiscoveryBundleVerificationError(
                f"missing or invalid discovery artifact for {scope}"
            )
        if scope.kind in {"player_ids_active", "player_ids_all"}:
            _require(not frame.is_empty(), f"player-ID discovery artifact is empty for {scope}")

    artifact_root = duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts")
    artifact_attestation = _mapping(summary.get("artifacts"), label="artifacts")
    recorded_root = artifact_attestation.get("discovery_artifact_dir")
    _require(
        isinstance(recorded_root, str) and Path(recorded_root).name == artifact_root.name,
        "discovery artifact directory attestation mismatch",
    )
    _verify_scope_attestations(
        rows=_rows(
            artifact_attestation.get("player_scope_artifacts"),
            label="artifacts.player_scope_artifacts",
        ),
        scopes=player_scopes,
        artifact_root=artifact_root,
        label="player scope artifact attestation",
    )
    _verify_scope_attestations(
        rows=_rows(
            artifact_attestation.get("player_season_artifacts"),
            label="artifacts.player_season_artifacts",
        ),
        scopes=player_season_scopes,
        artifact_root=artifact_root,
        label="player season artifact attestation",
    )
    _verify_scope_attestations(
        rows=_rows(
            artifact_attestation.get("game_combo_artifacts"),
            label="artifacts.game_combo_artifacts",
        ),
        scopes=game_scopes,
        artifact_root=artifact_root,
        label="game combo artifact attestation",
    )

    workload_pairs = {
        _pair(row, label=f"requested player/team pair {index}")
        for index, row in enumerate(workload_rows)
    }
    (
        expected_player_scopes,
        expected_player_season_scopes,
        expected_game_scopes,
        expected_workload_pairs,
    ) = _expected_manifest_units(manifest)
    _require(player_scopes == expected_player_scopes, "player scopes do not match lane manifest")
    _require(
        player_season_scopes == expected_player_season_scopes,
        "player seasons do not match lane manifest",
    )
    _require(game_scopes == expected_game_scopes, "game combos do not match lane manifest")
    _require(
        workload_pairs == expected_workload_pairs,
        "player/team workload pairs do not match lane manifest",
    )
    _require(len(player_scopes) == len(player_scope_rows), "duplicate requested player scopes")
    _require(
        len(player_season_scopes) == len(player_season_rows),
        "duplicate requested player seasons",
    )
    _require(len(game_scopes) == len(game_rows), "duplicate requested game combos")
    _require(
        len(workload_pairs) == len(workload_rows),
        "duplicate requested player/team workload pairs",
    )
    if workload_pairs:
        workload_store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(duckdb_path)
        _require(
            workload_store.artifact_path is not None
            and workload_store.artifact_path.is_file()
            and workload_store.manifest_path is not None
            and workload_store.manifest_path.is_file(),
            "player/team workload artifact pair is missing",
        )
        seasons = sorted({season for season, _season_type in workload_pairs})
        season_types = sorted({season_type for _season, season_type in workload_pairs})
        try:
            workload_coverage = workload_store.load_coverage(
                seasons=seasons,
                season_types=season_types,
            )
        except Exception as exc:
            raise DiscoveryBundleVerificationError(
                "player/team workload artifact is unreadable or malformed"
            ) from exc
        _require(
            not (workload_pairs & workload_coverage.invalid_pairs),
            "player/team workload artifact has invalid requested pairs",
        )
        _require(
            workload_pairs <= workload_coverage.covered_pairs,
            "player/team workload artifact is missing requested pairs",
        )
        current_integrity = workload_store.integrity_attestation()
        _require(
            current_integrity is not None,
            "player/team workload integrity attestation is unavailable",
        )
        current_integrity = cast("dict[str, Any]", current_integrity)
        workload_attestation = _mapping(
            artifact_attestation.get("player_team_season_workload"),
            label="artifacts.player_team_season_workload",
        )
        recorded_integrity = _mapping(
            workload_attestation.get("integrity"),
            label="artifacts.player_team_season_workload.integrity",
        )
        _require(
            recorded_integrity == current_integrity,
            "player/team workload integrity attestation mismatch",
        )
        _require(
            workload_attestation.get("covered_pair_count") == len(workload_pairs),
            "player/team workload attested pair count mismatch",
        )
        attested_pairs = {
            _pair(row, label=f"attested player/team pair {index}")
            for index, row in enumerate(
                _rows(
                    workload_attestation.get("covered_pairs"),
                    label="artifacts.player_team_season_workload.covered_pairs",
                )
            )
        }
        _require(attested_pairs == workload_pairs, "player/team workload attested pairs mismatch")
        _require(
            isinstance(workload_attestation.get("artifact_path"), str)
            and workload_store.artifact_path is not None
            and Path(workload_attestation["artifact_path"]).name
            == current_integrity["generation_basename"],
            "player/team workload attested artifact path mismatch",
        )
        _require(
            isinstance(workload_attestation.get("manifest_path"), str)
            and workload_store.manifest_path is not None
            and Path(workload_attestation["manifest_path"]).name
            == workload_store.manifest_path.name,
            "player/team workload attested manifest path mismatch",
        )
    else:
        _require(
            artifact_attestation.get("player_team_season_workload") is None,
            "unexpected player/team workload attestation",
        )

    expected_exact_count = len(player_season_scopes) + len(game_scopes) + len(workload_pairs)
    expected_counts = {
        "player_scope_count": len(player_scopes),
        "player_season_count": len(player_season_scopes),
        "game_combo_count": len(game_scopes),
        "player_team_season_pair_count": len(workload_pairs),
        "exact_unit_count": expected_exact_count,
    }
    _require(requested_counts == expected_counts, "requested coverage counts do not match units")
    _require(covered_counts == expected_counts, "covered coverage counts do not match units")
    _require(summary.get("scope_count") == len(player_scopes), "player scope count mismatch")
    _require(summary.get("game_combo_count") == len(game_scopes), "game combo count mismatch")
    _require(
        summary.get("player_team_season_pair_count") == len(workload_pairs),
        "player/team workload pair count mismatch",
    )
    _require(
        summary.get("player_team_season_unique_season_count")
        == len({season for season, _season_type in workload_pairs}),
        "player/team workload unique-season count mismatch",
    )
    _require(
        summary.get("total_scope_count")
        == len(player_scopes) + len(game_scopes) + len(workload_pairs),
        "total scope count mismatch",
    )
    _require(
        summary.get("requested_exact_unit_count") == expected_exact_count,
        "requested exact-unit count does not match the attested units",
    )
    _require(
        summary.get("covered_exact_unit_count") == expected_exact_count,
        "covered exact-unit count does not match the attested units",
    )
    return {
        "player_scopes": len(player_scopes),
        "player_seasons": len(player_season_scopes),
        "game_combos": len(game_scopes),
        "player_team_season_pairs": len(workload_pairs),
        "exact_units": expected_exact_count,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a complete discovery seed bundle.")
    parser.add_argument("--summary-path", type=Path, required=True)
    parser.add_argument("--manifest-path", type=Path, required=True)
    parser.add_argument("--duckdb-path", type=Path, default=Path("data/nbadb/nba.duckdb"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        counts = verify_discovery_bundle(
            summary_path=args.summary_path,
            manifest_path=args.manifest_path,
            duckdb_path=args.duckdb_path,
        )
    except DiscoveryBundleVerificationError as exc:
        print(f"::error::Discovery bundle verification failed: {exc}")
        return 1
    print(json.dumps({"status": "complete", **counts}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
