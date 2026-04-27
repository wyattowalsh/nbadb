from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

import polars as pl
from loguru import logger

from nbadb.orchestrate.persistence import atomic_write_path, atomic_write_text

ArtifactKind = Literal[
    "league_game_log",
    "player_ids_active",
    "player_ids_all",
    "team_ids",
    "current_team_ids",
]


@dataclass(frozen=True, slots=True)
class DiscoveryArtifactScope:
    kind: ArtifactKind
    seasons: tuple[str, ...] = ()
    season_types: tuple[str, ...] = ()
    variant: str = "default"

    def digest(self) -> str:
        payload = json.dumps(
            {
                "kind": self.kind,
                "seasons": list(self.seasons),
                "season_types": list(self.season_types),
                "variant": self.variant,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class DiscoveryArtifactStore:
    def __init__(self, root_dir: Path | None) -> None:
        self._root_dir = root_dir

    @classmethod
    def from_duckdb_path(cls, duckdb_path: Path | None) -> DiscoveryArtifactStore:
        if duckdb_path is None:
            return cls(None)
        return cls(duckdb_path.with_name(f"{duckdb_path.stem}.discovery-artifacts"))

    def is_available(self) -> bool:
        return self._root_dir is not None

    def load_frame(self, scope: DiscoveryArtifactScope) -> pl.DataFrame | None:
        if not self.is_available():
            return None
        artifact_path = self._artifact_path(scope)
        if not artifact_path.exists():
            return None
        return pl.read_parquet(artifact_path)

    def load_game_log_frame(self, scope: DiscoveryArtifactScope) -> pl.DataFrame | None:
        cached = self.load_frame(scope)
        if cached is not None:
            return cached
        if scope.kind != "league_game_log" or not scope.seasons or not scope.season_types:
            return None

        combo_frames: list[pl.DataFrame] = []
        for season in scope.seasons:
            for season_type in scope.season_types:
                combo_scope = DiscoveryArtifactScope(
                    kind="league_game_log",
                    seasons=(season,),
                    season_types=(season_type,),
                    variant=scope.variant,
                )
                combo_frame = self.load_frame(combo_scope)
                if combo_frame is None:
                    return None
                combo_frames.append(combo_frame)

        logger.info(
            (
                "reusing scoped league_game_log cache from {} combo artifacts "
                "for seasons={} season_types={}"
            ),
            len(combo_frames),
            list(scope.seasons),
            list(scope.season_types),
        )
        non_empty_frames = [frame for frame in combo_frames if not frame.is_empty()]
        if not non_empty_frames:
            return pl.DataFrame()
        return pl.concat(non_empty_frames, how="diagonal_relaxed")

    def upsert_frame(
        self,
        scope: DiscoveryArtifactScope,
        frame: pl.DataFrame,
        *,
        provenance: str,
    ) -> pl.DataFrame:
        if not self.is_available():
            return frame
        artifact_path = self._artifact_path(scope)
        manifest_path = self._manifest_path(scope)
        atomic_write_path(artifact_path, frame.write_parquet)
        manifest_payload = {
            "artifact_kind": scope.kind,
            "artifact_version": 1,
            "scope": {
                "seasons": list(scope.seasons),
                "season_types": list(scope.season_types),
                "variant": scope.variant,
            },
            "artifact_path": str(artifact_path),
            "updated_at": datetime.now(UTC).isoformat(),
            "row_count": frame.height,
            "provenance": provenance,
        }
        atomic_write_text(manifest_path, json.dumps(manifest_payload, indent=2) + "\n")
        return frame

    def load_ids(self, scope: DiscoveryArtifactScope, *, column: str = "value") -> list[int]:
        frame = self.load_frame(scope)
        if frame is None or frame.is_empty() or column not in frame.columns:
            return []
        return [
            int(value)
            for value in (
                frame.get_column(column).drop_nulls().cast(pl.Int64, strict=False).to_list()
            )
        ]

    def upsert_ids(
        self,
        scope: DiscoveryArtifactScope,
        values: list[int],
        *,
        provenance: str,
        column: str = "value",
    ) -> list[int]:
        frame = pl.DataFrame({column: sorted({int(value) for value in values})})
        self.upsert_frame(scope, frame, provenance=provenance)
        return frame.get_column(column).cast(pl.Int64, strict=False).to_list()

    def upsert_game_log_combo_frames(
        self,
        frames_by_combo: dict[tuple[str, str], pl.DataFrame],
        *,
        provenance: str,
    ) -> None:
        for (season, season_type), frame in frames_by_combo.items():
            self.upsert_frame(
                DiscoveryArtifactScope(
                    kind="league_game_log",
                    seasons=(season,),
                    season_types=(season_type,),
                ),
                frame,
                provenance=provenance,
            )

    def _artifact_path(self, scope: DiscoveryArtifactScope) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.parquet"

    def _manifest_path(self, scope: DiscoveryArtifactScope) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.json"
