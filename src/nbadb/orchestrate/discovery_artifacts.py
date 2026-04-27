from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal

if TYPE_CHECKING:
    from pathlib import Path

import polars as pl

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
        return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


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
        manifest_path = self._manifest_path(scope)
        if not artifact_path.exists() or not manifest_path.exists():
            return None
        return pl.read_parquet(artifact_path)

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
        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = artifact_path.with_suffix(f"{artifact_path.suffix}.tmp")
        try:
            frame.write_parquet(temp_path)
            temp_path.replace(artifact_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()
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
        manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")
        return frame

    def load_ids(self, scope: DiscoveryArtifactScope, *, column: str = "value") -> list[int]:
        frame = self.load_frame(scope)
        if frame is None or frame.is_empty() or column not in frame.columns:
            return []
        return [
            int(value)
            for value in (
                frame.get_column(column)
                .drop_nulls()
                .cast(pl.Int64, strict=False)
                .to_list()
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

    def _artifact_path(self, scope: DiscoveryArtifactScope) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.parquet"

    def _manifest_path(self, scope: DiscoveryArtifactScope) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.json"
