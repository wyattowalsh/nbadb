from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl

if TYPE_CHECKING:
    import duckdb

    from nbadb.orchestrate.planning import PlanParams

_ARTIFACT_VERSION = 1
_ARTIFACT_KIND = "player_team_season_workload"
_ARTIFACT_SUFFIX = ".player-team-season-workload.parquet"
_MANIFEST_SUFFIX = ".player-team-season-workload.json"
_COLUMNS = ("player_id", "team_id", "season", "season_type")
_SCHEMA = {
    "player_id": pl.Int64,
    "team_id": pl.Int64,
    "season": pl.Utf8,
    "season_type": pl.Utf8,
}


@dataclass(frozen=True, slots=True)
class PlayerTeamSeasonWorkloadCoverage:
    counts_by_pair: dict[tuple[str, str], int]
    covered_pairs: set[tuple[str, str]]


class PlayerTeamSeasonWorkloadStore:
    """Persist and read the discovered player/team/season workload contract."""

    def __init__(self, artifact_path: Path | None) -> None:
        self._artifact_path = artifact_path
        self._manifest_path = (
            artifact_path.with_suffix(_MANIFEST_SUFFIX) if artifact_path is not None else None
        )

    @classmethod
    def from_duckdb_path(cls, duckdb_path: Path | None) -> PlayerTeamSeasonWorkloadStore:
        if duckdb_path is None:
            return cls(None)
        return cls(duckdb_path.with_name(f"{duckdb_path.stem}{_ARTIFACT_SUFFIX}"))

    @classmethod
    def from_connection(
        cls,
        conn: duckdb.DuckDBPyConnection,
    ) -> PlayerTeamSeasonWorkloadStore:
        row = conn.execute("PRAGMA database_list").fetchall()
        for _seq, name, file_path in row:
            if name != "main" or not file_path or file_path == ":memory:":
                continue
            return cls.from_duckdb_path(Path(file_path))
        return cls(None)

    @property
    def artifact_path(self) -> Path | None:
        return self._artifact_path

    @property
    def manifest_path(self) -> Path | None:
        return self._manifest_path

    def is_available(self) -> bool:
        return self._artifact_path is not None and self._manifest_path is not None

    def upsert(
        self,
        params: list[PlanParams],
        *,
        seasons: list[str],
        season_types: list[str],
    ) -> None:
        if not self.is_available():
            return

        artifact_path = self._artifact_path
        manifest_path = self._manifest_path
        assert artifact_path is not None
        assert manifest_path is not None

        target_pairs = self._normalized_pairs(seasons, season_types)
        existing = self._read_existing_frame()
        retained = self._exclude_pairs(existing, target_pairs)
        updated = self._normalize_params(params)
        combined = (
            pl.concat([retained, updated], how="vertical_relaxed")
            .unique(subset=list(_COLUMNS))
            .sort(["season", "season_type", "player_id", "team_id"])
        )

        artifact_path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = artifact_path.with_suffix(f"{artifact_path.suffix}.tmp")
        try:
            combined.write_parquet(temp_path)
            temp_path.replace(artifact_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

        manifest = self._read_manifest()
        previous_pairs = self._manifest_pairs(manifest)
        covered_pairs = sorted((previous_pairs - target_pairs) | target_pairs)
        manifest_payload = {
            "artifact_version": _ARTIFACT_VERSION,
            "artifact_kind": _ARTIFACT_KIND,
            "artifact_path": str(artifact_path),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_params": combined.height,
            "covered_pairs": [
                {"season": season, "season_type": season_type}
                for season, season_type in covered_pairs
            ],
            "covered_seasons": sorted({season for season, _season_type in covered_pairs}),
            "covered_season_types": sorted(
                {season_type for _season, season_type in covered_pairs}
            ),
        }
        manifest_path.write_text(json.dumps(manifest_payload, indent=2) + "\n", encoding="utf-8")

    def load_params(
        self,
        *,
        seasons: list[str] | None = None,
        season_types: list[str] | None = None,
    ) -> list[PlanParams]:
        frame = self._filtered_frame(seasons=seasons, season_types=season_types)
        if frame is None or frame.is_empty():
            return []
        return [
            {
                "player_id": int(row["player_id"]),
                "team_id": int(row["team_id"]),
                "season": str(row["season"]),
                "season_type": str(row["season_type"]),
            }
            for row in frame.to_dicts()
        ]

    def load_coverage(
        self,
        *,
        seasons: list[str] | None = None,
        season_types: list[str] | None = None,
    ) -> PlayerTeamSeasonWorkloadCoverage:
        manifest = self._read_manifest()
        all_pairs = self._manifest_pairs(manifest)
        filtered_pairs = {
            pair
            for pair in all_pairs
            if (seasons is None or pair[0] in seasons)
            and (season_types is None or pair[1] in season_types)
        }

        frame = self._filtered_frame(seasons=seasons, season_types=season_types)
        if frame is None or frame.is_empty():
            return PlayerTeamSeasonWorkloadCoverage(
                counts_by_pair={},
                covered_pairs=filtered_pairs,
            )

        grouped = (
            frame.group_by(["season", "season_type"])
            .len(name="count")
            .sort(["season", "season_type"])
        )
        counts_by_pair = {
            (str(row["season"]), str(row["season_type"])): int(row["count"])
            for row in grouped.to_dicts()
        }
        return PlayerTeamSeasonWorkloadCoverage(
            counts_by_pair=counts_by_pair,
            covered_pairs=filtered_pairs,
        )

    def _filtered_frame(
        self,
        *,
        seasons: list[str] | None,
        season_types: list[str] | None,
    ) -> pl.DataFrame | None:
        if not self.is_available():
            return None

        artifact_path = self._artifact_path
        assert artifact_path is not None
        if not artifact_path.exists():
            return None

        lazy = pl.scan_parquet(artifact_path)
        if seasons is not None:
            lazy = lazy.filter(pl.col("season").is_in(seasons))
        if season_types is not None:
            lazy = lazy.filter(pl.col("season_type").is_in(season_types))
        return cast(
            "pl.DataFrame",
            lazy.select(
                pl.col("player_id"),
                pl.col("team_id"),
                pl.col("season"),
                pl.col("season_type"),
            ).collect(),
        )

    def _read_existing_frame(self) -> pl.DataFrame:
        frame = self._filtered_frame(seasons=None, season_types=None)
        if frame is not None:
            return frame
        return pl.DataFrame(schema=_SCHEMA)

    def _read_manifest(self) -> dict[str, object]:
        if not self.is_available():
            return {}
        manifest_path = self._manifest_path
        assert manifest_path is not None
        if not manifest_path.exists():
            return {}
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    @staticmethod
    def _manifest_pairs(manifest: dict[str, object]) -> set[tuple[str, str]]:
        rows = manifest.get("covered_pairs", [])
        if not isinstance(rows, list):
            return set()
        pairs: set[tuple[str, str]] = set()
        for row in rows:
            if not isinstance(row, dict):
                continue
            mapping = cast("dict[str, object]", row)
            season = mapping.get("season")
            season_type = mapping.get("season_type")
            if season is None or season_type is None:
                continue
            pairs.add((str(season), str(season_type)))
        return pairs

    @staticmethod
    def _normalized_pairs(seasons: list[str], season_types: list[str]) -> set[tuple[str, str]]:
        return {
            (str(season), str(season_type))
            for season in seasons
            for season_type in season_types
        }

    @staticmethod
    def _exclude_pairs(
        frame: pl.DataFrame,
        pairs: set[tuple[str, str]],
    ) -> pl.DataFrame:
        if frame.is_empty() or not pairs:
            return frame
        mask = pl.struct("season", "season_type").is_in(
            [{"season": season, "season_type": season_type} for season, season_type in pairs]
        )
        return frame.filter(~mask)

    @staticmethod
    def _normalize_params(params: list[PlanParams]) -> pl.DataFrame:
        if not params:
            return pl.DataFrame(schema=_SCHEMA)
        frame = pl.DataFrame(params, strict=False)
        if frame.is_empty():
            return pl.DataFrame(schema=_SCHEMA)
        return frame.select(
            pl.col("player_id").cast(pl.Int64, strict=False),
            pl.col("team_id").cast(pl.Int64, strict=False),
            pl.col("season").cast(pl.Utf8, strict=False),
            pl.col("season_type").cast(pl.Utf8, strict=False),
        ).drop_nulls().unique(subset=list(_COLUMNS))
