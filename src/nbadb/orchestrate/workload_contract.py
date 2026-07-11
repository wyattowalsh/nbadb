from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

import polars as pl
from loguru import logger

from nbadb.orchestrate.persistence import atomic_write_path, atomic_write_text, read_json_object

if TYPE_CHECKING:
    import duckdb

    from nbadb.orchestrate.planning import PlanParams

_ARTIFACT_VERSION = 3
_ARTIFACT_KIND = "player_team_season_workload"
_ARTIFACT_SUFFIX = ".player-team-season-workload.parquet"
_MANIFEST_SUFFIX = ".player-team-season-workload.json"
_COLUMNS = ("player_id", "team_id", "season", "season_type")
_COVERED_SENTINEL_PLAYER_ID = 0
_COVERED_SENTINEL_TEAM_ID = 0
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
    invalid_pairs: set[tuple[str, str]]


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
        covered_pairs: set[tuple[str, str]] | None = None,
    ) -> None:
        if not self.is_available():
            return

        artifact_path = self._artifact_path
        manifest_path = self._manifest_path
        assert artifact_path is not None
        assert manifest_path is not None

        target_pairs: set[tuple[str, str]] = (
            {(str(pair[0]), str(pair[1])) for pair in covered_pairs}
            if covered_pairs is not None
            else self._normalized_pairs(seasons, season_types)
        )
        existing = self._read_existing_frame()
        retained = self._exclude_pairs(existing, target_pairs)
        updated = self._normalize_params(params)
        sentinel_pairs = target_pairs - self._frame_pairs(updated)
        sentinels = self._sentinel_frame(sentinel_pairs)
        combined = (
            pl.concat([retained, updated, sentinels], how="vertical_relaxed")
            .unique(subset=list(_COLUMNS))
            .sort(["season", "season_type", "player_id", "team_id"])
        )

        atomic_write_path(artifact_path, combined.write_parquet)

        self._read_manifest(repair=True)
        pair_evidence = self._frame_pair_evidence(combined)
        covered_pairs_list = sorted(pair_evidence)
        manifest_payload = {
            "artifact_version": _ARTIFACT_VERSION,
            "artifact_kind": _ARTIFACT_KIND,
            "artifact_path": str(artifact_path),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_params": self._drop_sentinels(combined).height,
            "covered_pairs": [
                {
                    "season": season,
                    "season_type": season_type,
                    "row_count": pair_evidence[(season, season_type)][0],
                }
                for season, season_type in covered_pairs_list
            ],
            "covered_seasons": sorted({season for season, _season_type in covered_pairs_list}),
            "covered_season_types": sorted(
                {season_type for _season, season_type in covered_pairs_list}
            ),
        }
        atomic_write_text(manifest_path, json.dumps(manifest_payload, indent=2) + "\n")

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
        manifest = self._read_manifest(repair=False)
        declared_counts = self._manifest_pair_counts(manifest)
        filtered_counts = {
            pair: count
            for pair, count in declared_counts.items()
            if (seasons is None or pair[0] in seasons)
            and (season_types is None or pair[1] in season_types)
        }

        frame = self._artifact_frame(seasons=seasons, season_types=season_types)
        if frame is None:
            return PlayerTeamSeasonWorkloadCoverage(
                counts_by_pair={},
                covered_pairs=set(),
                invalid_pairs=set(filtered_counts),
            )

        artifact_evidence = self._frame_pair_evidence(frame)
        counts_by_pair: dict[tuple[str, str], int] = {}
        covered_pairs: set[tuple[str, str]] = set()
        invalid_pairs: set[tuple[str, str]] = set()
        for pair, declared_count in filtered_counts.items():
            actual_count, sentinel_count = artifact_evidence.get(pair, (0, 0))
            if declared_count is None:
                valid = (actual_count > 0 and sentinel_count == 0) or (
                    actual_count == 0 and sentinel_count == 1
                )
            else:
                valid = actual_count == declared_count and (
                    (declared_count > 0 and sentinel_count == 0)
                    or (declared_count == 0 and sentinel_count == 1)
                )
            if not valid:
                invalid_pairs.add(pair)
                continue
            covered_pairs.add(pair)
            if actual_count:
                counts_by_pair[pair] = actual_count

        return PlayerTeamSeasonWorkloadCoverage(
            counts_by_pair=counts_by_pair,
            covered_pairs=covered_pairs,
            invalid_pairs=invalid_pairs,
        )

    def _filtered_frame(
        self,
        *,
        seasons: list[str] | None,
        season_types: list[str] | None,
    ) -> pl.DataFrame | None:
        frame = self._artifact_frame(
            seasons=seasons,
            season_types=season_types,
        )
        if frame is None:
            return None
        return self._drop_sentinels(frame)

    def _artifact_frame(
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
        return lazy.select(
            pl.col("player_id"),
            pl.col("team_id"),
            pl.col("season"),
            pl.col("season_type"),
        ).collect()

    def _read_existing_frame(self) -> pl.DataFrame:
        frame = self._artifact_frame(seasons=None, season_types=None)
        if frame is not None:
            return frame
        return pl.DataFrame(schema=_SCHEMA)

    def _read_manifest(self, *, repair: bool = False) -> dict[str, object]:
        if not self.is_available():
            return {}
        manifest_path = self._manifest_path
        assert manifest_path is not None
        manifest = read_json_object(
            manifest_path,
            metadata_label="player/team workload manifest",
            repair_corrupt=repair,
        )
        if manifest:
            return manifest

        recovered = self._rebuild_manifest_from_artifact()
        if recovered and repair:
            logger.warning(
                "recovered player/team workload manifest from parquet artifact {}",
                self._artifact_path,
            )
            atomic_write_text(manifest_path, json.dumps(recovered, indent=2) + "\n")
        return recovered

    def _rebuild_manifest_from_artifact(self) -> dict[str, object]:
        frame = self._artifact_frame(seasons=None, season_types=None)
        if frame is None:
            return {}

        real_params = self._drop_sentinels(frame)
        pair_evidence = self._frame_pair_evidence(frame)
        covered_pairs = [
            {
                "season": season,
                "season_type": season_type,
                "row_count": pair_evidence[(season, season_type)][0],
            }
            for season, season_type in sorted(pair_evidence)
        ]
        if not covered_pairs and frame.is_empty():
            return {}

        artifact_path = self._artifact_path
        assert artifact_path is not None
        return {
            "artifact_version": _ARTIFACT_VERSION,
            "artifact_kind": _ARTIFACT_KIND,
            "artifact_path": str(artifact_path),
            "updated_at": datetime.now(UTC).isoformat(),
            "total_params": real_params.height,
            "covered_pairs": covered_pairs,
            "covered_seasons": sorted({row["season"] for row in covered_pairs}),
            "covered_season_types": sorted({row["season_type"] for row in covered_pairs}),
            "recovered_from_artifact": True,
        }

    @staticmethod
    def _manifest_pair_counts(
        manifest: dict[str, object],
    ) -> dict[tuple[str, str], int | None]:
        rows = manifest.get("covered_pairs", [])
        if not isinstance(rows, list):
            return {}
        pairs: dict[tuple[str, str], int | None] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            mapping = cast("dict[str, object]", row)
            season = mapping.get("season")
            season_type = mapping.get("season_type")
            if season is None or season_type is None:
                continue
            raw_count = mapping.get("row_count")
            if raw_count is None:
                row_count = None
            elif isinstance(raw_count, int | str) and not isinstance(raw_count, bool):
                try:
                    row_count = int(raw_count)
                except ValueError:
                    row_count = -1
            else:
                row_count = -1
            if row_count is not None and row_count < 0:
                row_count = -1
            pairs[(str(season), str(season_type))] = row_count
        return pairs

    @staticmethod
    def _normalized_pairs(seasons: list[str], season_types: list[str]) -> set[tuple[str, str]]:
        return {
            (str(season), str(season_type)) for season in seasons for season_type in season_types
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
        return (
            frame.select(
                pl.col("player_id").cast(pl.Int64, strict=False),
                pl.col("team_id").cast(pl.Int64, strict=False),
                pl.col("season").cast(pl.Utf8, strict=False),
                pl.col("season_type").cast(pl.Utf8, strict=False),
            )
            .drop_nulls()
            .unique(subset=list(_COLUMNS))
        )

    @staticmethod
    def _frame_pairs(frame: pl.DataFrame) -> set[tuple[str, str]]:
        if frame.is_empty():
            return set()
        grouped = frame.group_by(["season", "season_type"]).len(name="count")
        return {(str(row["season"]), str(row["season_type"])) for row in grouped.to_dicts()}

    @staticmethod
    def _frame_pair_evidence(
        frame: pl.DataFrame,
    ) -> dict[tuple[str, str], tuple[int, int]]:
        if frame.is_empty():
            return {}
        grouped = (
            frame.with_columns(
                (
                    (pl.col("player_id") == _COVERED_SENTINEL_PLAYER_ID)
                    & (pl.col("team_id") == _COVERED_SENTINEL_TEAM_ID)
                ).alias("_is_covered_sentinel")
            )
            .group_by(["season", "season_type"])
            .agg(
                (~pl.col("_is_covered_sentinel")).sum().alias("row_count"),
                pl.col("_is_covered_sentinel").sum().alias("sentinel_count"),
            )
            .sort(["season", "season_type"])
        )
        return {
            (str(row["season"]), str(row["season_type"])): (
                int(row["row_count"]),
                int(row["sentinel_count"]),
            )
            for row in grouped.to_dicts()
        }

    @staticmethod
    def _sentinel_frame(pairs: set[tuple[str, str]]) -> pl.DataFrame:
        if not pairs:
            return pl.DataFrame(schema=_SCHEMA)
        return pl.DataFrame(
            [
                {
                    "player_id": _COVERED_SENTINEL_PLAYER_ID,
                    "team_id": _COVERED_SENTINEL_TEAM_ID,
                    "season": season,
                    "season_type": season_type,
                }
                for season, season_type in sorted(pairs)
            ],
            schema=_SCHEMA,
        )

    @staticmethod
    def _drop_sentinels(frame: pl.DataFrame) -> pl.DataFrame:
        if frame.is_empty():
            return frame
        return frame.filter(
            ~(
                (pl.col("player_id") == _COVERED_SENTINEL_PLAYER_ID)
                & (pl.col("team_id") == _COVERED_SENTINEL_TEAM_ID)
            )
        )
