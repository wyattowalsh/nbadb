from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import TYPE_CHECKING, TypedDict, TypeGuard, cast

import polars as pl
from loguru import logger

from nbadb.orchestrate.persistence import atomic_write_path, atomic_write_text
from nbadb.orchestrate.seasons import season_string

if TYPE_CHECKING:
    from collections.abc import Mapping

    import duckdb

    from nbadb.orchestrate.planning import PlanParams

_ARTIFACT_VERSION = 4
_LEGACY_ARTIFACT_VERSION = 3
_ARTIFACT_KIND = "player_team_season_workload"
_ARTIFACT_FORMAT = "parquet"
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


class PlayerTeamSeasonWorkloadIntegrityAttestation(TypedDict):
    manifest_version: int
    generation_basename: str
    sha256: str
    schema: list[dict[str, str]]
    total_rows: int
    real_rows: int


PlayerTeamSeasonWorkloadBaseUnit = tuple[int, str, int, int]


class PlayerTeamSeasonWorkloadScopeContract(TypedDict):
    integrity: PlayerTeamSeasonWorkloadIntegrityAttestation
    requested_pairs: list[dict[str, int | str]]
    expected_base_unit_count: int
    expected_base_units_sha256: str
    expected_empty: bool


@dataclass(frozen=True, slots=True)
class PlayerTeamSeasonWorkloadScope:
    base_units: frozenset[PlayerTeamSeasonWorkloadBaseUnit]
    contract: PlayerTeamSeasonWorkloadScopeContract


@dataclass(frozen=True, slots=True)
class _WorkloadPointer:
    generation_path: Path
    content_sha256: str
    row_count: int
    real_row_count: int
    counts_by_pair: dict[tuple[str, str], int]


class PlayerTeamSeasonWorkloadStore:
    """Persist and validate the discovered player/team/season workload contract.

    ``artifact_path`` never falls back to an unpointed generation or the fixed
    v3 path. Callers handling v3 input must use ``legacy_artifact_path`` and
    explicitly invoke ``promote_legacy_v3()``.
    """

    def __init__(self, legacy_artifact_path: Path | None) -> None:
        self._legacy_artifact_path = legacy_artifact_path
        self._manifest_path = (
            legacy_artifact_path.with_suffix(_MANIFEST_SUFFIX)
            if legacy_artifact_path is not None
            else None
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
        """Return the current generation only after full pointer/content validation.

        A missing or invalid stable manifest makes even an existing generation
        unavailable, because its scope and integrity are no longer attested.
        """
        loaded = self._load_current()
        return loaded[0].generation_path if loaded is not None else None

    @property
    def legacy_artifact_path(self) -> Path | None:
        """Return the fixed v3 Parquet path used only by explicit legacy promotion."""
        return self._legacy_artifact_path

    @property
    def manifest_path(self) -> Path | None:
        return self._manifest_path

    def is_available(self) -> bool:
        return self._legacy_artifact_path is not None and self._manifest_path is not None

    def integrity_attestation(self) -> PlayerTeamSeasonWorkloadIntegrityAttestation | None:
        """Return JSON-ready v4 integrity metadata after strict content validation.

        Missing, legacy, malformed, unsafe, digest-mismatched, schema-mismatched,
        or semantically inconsistent state returns ``None``.
        """
        loaded = self._load_current()
        if loaded is None:
            return None
        pointer, _frame = loaded
        return {
            "manifest_version": _ARTIFACT_VERSION,
            "generation_basename": pointer.generation_path.name,
            "sha256": pointer.content_sha256,
            "schema": self._canonical_schema_payload(),
            "total_rows": pointer.row_count,
            "real_rows": pointer.real_row_count,
        }

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

        target_pairs: set[tuple[str, str]] = (
            {(str(pair[0]), str(pair[1])) for pair in covered_pairs}
            if covered_pairs is not None
            else self._normalized_pairs(seasons, season_types)
        )
        self._validate_pair_names(target_pairs)

        existing = self._read_existing_frame_for_update()
        retained = self._exclude_pairs(existing, target_pairs)
        updated = self._normalize_params(params)
        updated_pairs = self._frame_pairs(updated)
        if not updated_pairs <= target_pairs:
            unexpected = sorted(updated_pairs - target_pairs)
            raise ValueError(f"workload rows fall outside covered pairs: {unexpected}")

        sentinel_pairs = target_pairs - updated_pairs
        combined = self._canonicalize_frame(
            pl.concat(
                [retained, updated, self._sentinel_frame(sentinel_pairs)],
                how="vertical_relaxed",
            ).unique(subset=list(_COLUMNS))
        )
        self._persist_generation(combined, provenance="upsert")

    def promote_legacy_v3(self) -> Path | None:
        """Validate and atomically promote the fixed v3 artifact/manifest pair.

        The operation is idempotent for a valid current v4 generation. Missing,
        partial, malformed, or semantically inconsistent legacy state is left
        untouched and returns ``None``.
        """
        if not self.is_available():
            return None

        manifest = self._load_manifest_object()
        if manifest is None:
            return None
        if manifest.get("artifact_version") == _ARTIFACT_VERSION:
            return self.artifact_path
        if manifest.get("artifact_version") != _LEGACY_ARTIFACT_VERSION:
            self._warn_invalid("legacy manifest version")
            return None
        if manifest.get("artifact_kind") != _ARTIFACT_KIND:
            self._warn_invalid("legacy artifact kind")
            return None

        legacy_path = self._legacy_artifact_path
        assert legacy_path is not None
        if not legacy_path.is_file() or legacy_path.is_symlink():
            self._warn_invalid("legacy artifact path")
            return None

        declared_path = manifest.get("artifact_path")
        if not isinstance(declared_path, str) or Path(declared_path).name != legacy_path.name:
            self._warn_invalid("legacy artifact filename")
            return None

        pair_counts = self._parse_pair_counts(manifest.get("covered_pairs"))
        if pair_counts is None or not self._validate_covered_pair_summaries(manifest, pair_counts):
            self._warn_invalid("legacy covered-pair metadata")
            return None

        total_params = manifest.get("total_params")
        if not self._is_nonnegative_int(total_params) or total_params != sum(pair_counts.values()):
            self._warn_invalid("legacy real-row count")
            return None
        if not isinstance(manifest.get("updated_at"), str) or not manifest["updated_at"]:
            self._warn_invalid("legacy update timestamp")
            return None

        frame = self._read_parquet_bytes(legacy_path)
        if frame is None:
            return None
        expected_row_count = int(total_params) + sum(count == 0 for count in pair_counts.values())
        if not self._validate_frame(
            frame,
            row_count=expected_row_count,
            real_row_count=int(total_params),
            counts_by_pair=pair_counts,
        ):
            self._warn_invalid("legacy artifact content")
            return None

        self._persist_generation(frame, provenance="legacy_v3_promotion")
        return self.artifact_path

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
        pointer = self._load_current_pointer()
        if pointer is None:
            return PlayerTeamSeasonWorkloadCoverage(
                counts_by_pair={},
                covered_pairs=set(),
                invalid_pairs=set(),
            )

        filtered_counts = {
            pair: count
            for pair, count in pointer.counts_by_pair.items()
            if (seasons is None or pair[0] in seasons)
            and (season_types is None or pair[1] in season_types)
        }
        frame = self._load_generation(pointer)
        if frame is None:
            return PlayerTeamSeasonWorkloadCoverage(
                counts_by_pair={},
                covered_pairs=set(),
                invalid_pairs=set(filtered_counts),
            )

        return PlayerTeamSeasonWorkloadCoverage(
            counts_by_pair={pair: count for pair, count in filtered_counts.items() if count > 0},
            covered_pairs=set(filtered_counts),
            invalid_pairs=set(),
        )

    def _filtered_frame(
        self,
        *,
        seasons: list[str] | None,
        season_types: list[str] | None,
    ) -> pl.DataFrame | None:
        loaded = self._load_current()
        if loaded is None:
            return None
        _pointer, frame = loaded
        if seasons is not None:
            frame = frame.filter(pl.col("season").is_in(seasons))
        if season_types is not None:
            frame = frame.filter(pl.col("season_type").is_in(season_types))
        return self._drop_sentinels(frame)

    def _read_existing_frame_for_update(self) -> pl.DataFrame:
        if not self.is_available():
            return pl.DataFrame(schema=_SCHEMA)

        manifest_path = self._manifest_path
        legacy_path = self._legacy_artifact_path
        assert manifest_path is not None
        assert legacy_path is not None

        if not manifest_path.exists():
            if legacy_path.exists():
                raise ValueError("legacy workload artifact requires explicit v3 promotion")
            return pl.DataFrame(schema=_SCHEMA)

        loaded = self._load_current()
        if loaded is None:
            manifest = self._load_manifest_object()
            if (
                manifest is not None
                and manifest.get("artifact_version") == _LEGACY_ARTIFACT_VERSION
            ):
                raise ValueError("legacy workload artifact requires explicit v3 promotion")
            raise ValueError("refusing to update an invalid workload manifest or generation")
        return loaded[1]

    def _persist_generation(self, frame: pl.DataFrame, *, provenance: str) -> None:
        manifest_path = self._manifest_path
        assert manifest_path is not None
        frame = self._canonicalize_frame(frame)
        pair_evidence = self._frame_pair_evidence(frame)
        pair_counts = {pair: evidence[0] for pair, evidence in pair_evidence.items()}
        real_row_count = sum(pair_counts.values())

        buffer = BytesIO()
        frame.write_parquet(buffer)
        artifact_bytes = buffer.getvalue()
        content_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        generation_path = self._generation_path(content_sha256)

        pointer = _WorkloadPointer(
            generation_path=generation_path,
            content_sha256=content_sha256,
            row_count=frame.height,
            real_row_count=real_row_count,
            counts_by_pair=pair_counts,
        )
        if not self._validate_frame(
            frame,
            row_count=pointer.row_count,
            real_row_count=pointer.real_row_count,
            counts_by_pair=pointer.counts_by_pair,
        ):
            raise ValueError("refusing to persist an invalid workload contract")

        if generation_path.exists() or generation_path.is_symlink():
            if generation_path.is_symlink():
                raise OSError(f"workload generation path is a symlink: {generation_path}")
            existing_digest = self._sha256_path(generation_path)
            if existing_digest != content_sha256:
                raise OSError(
                    f"workload generation digest collision or corruption: {generation_path}"
                )
        else:

            def _write_generation(path: Path) -> None:
                path.write_bytes(artifact_bytes)

            atomic_write_path(generation_path, _write_generation)
            existing_digest = self._sha256_path(generation_path)
        if existing_digest != content_sha256:
            raise OSError(f"workload generation verification failed: {generation_path}")

        manifest_payload = self._manifest_payload(pointer, provenance=provenance)
        atomic_write_text(
            manifest_path,
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        )

    def _manifest_payload(
        self,
        pointer: _WorkloadPointer,
        *,
        provenance: str,
    ) -> dict[str, object]:
        covered_pairs = [
            {
                "season": season,
                "season_type": season_type,
                "row_count": pointer.counts_by_pair[(season, season_type)],
            }
            for season, season_type in sorted(pointer.counts_by_pair)
        ]
        return {
            "artifact_version": _ARTIFACT_VERSION,
            "artifact_kind": _ARTIFACT_KIND,
            "content": {
                "format": _ARTIFACT_FORMAT,
                "path": pointer.generation_path.name,
                "sha256": pointer.content_sha256,
                "schema": self._canonical_schema_payload(),
                "row_count": pointer.row_count,
                "real_row_count": pointer.real_row_count,
            },
            "total_params": pointer.real_row_count,
            "covered_pairs": covered_pairs,
            "covered_seasons": sorted({season for season, _season_type in pointer.counts_by_pair}),
            "covered_season_types": sorted(
                {season_type for _season, season_type in pointer.counts_by_pair}
            ),
            "updated_at": datetime.now(UTC).isoformat(),
            "provenance": provenance,
        }

    def _load_current(self) -> tuple[_WorkloadPointer, pl.DataFrame] | None:
        pointer = self._load_current_pointer()
        if pointer is None:
            return None
        frame = self._load_generation(pointer)
        if frame is None:
            return None
        return pointer, frame

    def _load_current_pointer(self) -> _WorkloadPointer | None:
        if not self.is_available():
            return None
        manifest = self._load_manifest_object()
        if manifest is None:
            return None
        if manifest.get("artifact_version") != _ARTIFACT_VERSION:
            self._warn_invalid("manifest version")
            return None
        if manifest.get("artifact_kind") != _ARTIFACT_KIND:
            self._warn_invalid("manifest artifact kind")
            return None

        content_object = manifest.get("content")
        if not isinstance(content_object, dict):
            self._warn_invalid("manifest content")
            return None
        content = cast("dict[str, object]", content_object)
        content_sha256 = content.get("sha256")
        generation_name = content.get("path")
        row_count = content.get("row_count")
        real_row_count = content.get("real_row_count")

        if content.get("format") != _ARTIFACT_FORMAT:
            self._warn_invalid("manifest format")
            return None
        if content.get("schema") != self._canonical_schema_payload():
            self._warn_invalid("manifest schema")
            return None
        if not self._is_sha256(content_sha256):
            self._warn_invalid("manifest digest")
            return None
        assert isinstance(content_sha256, str)
        expected_generation = self._generation_path(content_sha256)
        if (
            not isinstance(generation_name, str)
            or Path(generation_name).name != generation_name
            or generation_name != expected_generation.name
        ):
            self._warn_invalid("manifest generation path")
            return None
        if not self._is_nonnegative_int(row_count) or not self._is_nonnegative_int(real_row_count):
            self._warn_invalid("manifest row counts")
            return None

        pair_counts = self._parse_pair_counts(manifest.get("covered_pairs"))
        if pair_counts is None or not self._validate_covered_pair_summaries(manifest, pair_counts):
            self._warn_invalid("manifest covered-pair metadata")
            return None
        expected_real_rows = sum(pair_counts.values())
        expected_rows = expected_real_rows + sum(count == 0 for count in pair_counts.values())
        total_params = manifest.get("total_params")
        if (
            real_row_count != expected_real_rows
            or row_count != expected_rows
            or not self._is_nonnegative_int(total_params)
            or total_params != real_row_count
        ):
            self._warn_invalid("manifest aggregate counts")
            return None
        if not isinstance(manifest.get("updated_at"), str) or not manifest["updated_at"]:
            self._warn_invalid("manifest update timestamp")
            return None

        return _WorkloadPointer(
            generation_path=expected_generation,
            content_sha256=content_sha256,
            row_count=int(row_count),
            real_row_count=int(real_row_count),
            counts_by_pair=pair_counts,
        )

    def _load_generation(self, pointer: _WorkloadPointer) -> pl.DataFrame | None:
        if pointer.generation_path.is_symlink():
            self._warn_invalid("generation symlink")
            return None
        frame = self._read_parquet_bytes(
            pointer.generation_path,
            expected_sha256=pointer.content_sha256,
        )
        if frame is None:
            return None
        if not self._validate_frame(
            frame,
            row_count=pointer.row_count,
            real_row_count=pointer.real_row_count,
            counts_by_pair=pointer.counts_by_pair,
        ):
            self._warn_invalid("generation content")
            return None
        return frame

    def _read_parquet_bytes(
        self,
        path: Path,
        *,
        expected_sha256: str | None = None,
    ) -> pl.DataFrame | None:
        try:
            artifact_bytes = path.read_bytes()
        except OSError as exc:
            logger.warning(
                "ignoring unreadable player/team workload artifact {}: {}",
                path,
                type(exc).__name__,
            )
            return None
        actual_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        if expected_sha256 is not None and actual_sha256 != expected_sha256:
            self._warn_invalid("generation digest")
            return None
        try:
            return pl.read_parquet(BytesIO(artifact_bytes))
        except (OSError, RuntimeError, ValueError, pl.exceptions.PolarsError) as exc:
            logger.warning(
                "ignoring unreadable player/team workload parquet {}: {}",
                path,
                type(exc).__name__,
            )
            return None

    def _load_manifest_object(self) -> dict[str, object] | None:
        manifest_path = self._manifest_path
        if manifest_path is None or not manifest_path.exists():
            return None
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(
                "ignoring unreadable player/team workload manifest {}: {}",
                manifest_path,
                type(exc).__name__,
            )
            return None
        if not isinstance(payload, dict):
            self._warn_invalid("manifest object")
            return None
        return cast("dict[str, object]", payload)

    def _generation_path(self, content_sha256: str) -> Path:
        legacy_path = self._legacy_artifact_path
        assert legacy_path is not None
        return legacy_path.with_name(f"{legacy_path.stem}.{content_sha256}.parquet")

    @staticmethod
    def _validate_frame(
        frame: pl.DataFrame,
        *,
        row_count: int,
        real_row_count: int,
        counts_by_pair: dict[tuple[str, str], int],
    ) -> bool:
        if list(frame.schema.items()) != list(_SCHEMA.items()) or frame.height != row_count:
            return False
        if frame.null_count().row(0) != (0, 0, 0, 0):
            return False
        if frame.unique(subset=list(_COLUMNS)).height != frame.height:
            return False
        if not frame.is_empty():
            invalid_text = frame.filter(
                (pl.col("season").str.strip_chars() == "")
                | (pl.col("season_type").str.strip_chars() == "")
            )
            if not invalid_text.is_empty():
                return False
            sentinel = (pl.col("player_id") == _COVERED_SENTINEL_PLAYER_ID) & (
                pl.col("team_id") == _COVERED_SENTINEL_TEAM_ID
            )
            invalid_ids = frame.filter(
                (~sentinel) & ((pl.col("player_id") <= 0) | (pl.col("team_id") <= 0))
            )
            if not invalid_ids.is_empty():
                return False

        evidence = PlayerTeamSeasonWorkloadStore._frame_pair_evidence(frame)
        if set(evidence) != set(counts_by_pair):
            return False
        if sum(counts_by_pair.values()) != real_row_count:
            return False
        for pair, declared_count in counts_by_pair.items():
            actual_count, sentinel_count = evidence[pair]
            if actual_count != declared_count:
                return False
            if sentinel_count != (1 if declared_count == 0 else 0):
                return False
        return True

    @staticmethod
    def _parse_pair_counts(value: object) -> dict[tuple[str, str], int] | None:
        if not isinstance(value, list):
            return None
        pair_counts: dict[tuple[str, str], int] = {}
        for item in value:
            if not isinstance(item, dict):
                return None
            row = cast("dict[str, object]", item)
            if set(row) != {"season", "season_type", "row_count"}:
                return None
            season = row.get("season")
            season_type = row.get("season_type")
            row_count = row.get("row_count")
            if (
                not isinstance(season, str)
                or not season.strip()
                or not isinstance(season_type, str)
                or not season_type.strip()
                or not PlayerTeamSeasonWorkloadStore._is_nonnegative_int(row_count)
            ):
                return None
            pair = (season, season_type)
            if pair in pair_counts:
                return None
            pair_counts[pair] = int(row_count)
        return pair_counts

    @staticmethod
    def _validate_covered_pair_summaries(
        manifest: dict[str, object],
        pair_counts: dict[tuple[str, str], int],
    ) -> bool:
        expected_seasons = sorted({season for season, _season_type in pair_counts})
        expected_season_types = sorted({season_type for _season, season_type in pair_counts})
        return (
            manifest.get("covered_seasons") == expected_seasons
            and manifest.get("covered_season_types") == expected_season_types
        )

    @staticmethod
    def _canonical_schema_payload() -> list[dict[str, str]]:
        return [{"name": name, "dtype": str(dtype)} for name, dtype in _SCHEMA.items()]

    @staticmethod
    def _canonicalize_frame(frame: pl.DataFrame) -> pl.DataFrame:
        return frame.select(
            pl.col("player_id").cast(pl.Int64),
            pl.col("team_id").cast(pl.Int64),
            pl.col("season").cast(pl.Utf8),
            pl.col("season_type").cast(pl.Utf8),
        ).sort(["season", "season_type", "player_id", "team_id"])

    @staticmethod
    def _normalized_pairs(seasons: list[str], season_types: list[str]) -> set[tuple[str, str]]:
        return {
            (str(season), str(season_type)) for season in seasons for season_type in season_types
        }

    @staticmethod
    def _validate_pair_names(pairs: set[tuple[str, str]]) -> None:
        if any(not season.strip() or not season_type.strip() for season, season_type in pairs):
            raise ValueError("workload covered pairs require non-empty season values")

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
        try:
            normalized = frame.select(
                pl.col("player_id").cast(pl.Int64, strict=False),
                pl.col("team_id").cast(pl.Int64, strict=False),
                pl.col("season").cast(pl.Utf8, strict=False),
                pl.col("season_type").cast(pl.Utf8, strict=False),
            )
        except pl.exceptions.ColumnNotFoundError as exc:
            raise ValueError("workload params are missing required columns") from exc
        if normalized.null_count().row(0) != (0, 0, 0, 0):
            raise ValueError("workload params contain null or unparseable values")
        if not normalized.is_empty():
            invalid = normalized.filter(
                (pl.col("player_id") <= 0)
                | (pl.col("team_id") <= 0)
                | (pl.col("season").str.strip_chars() == "")
                | (pl.col("season_type").str.strip_chars() == "")
            )
            if not invalid.is_empty():
                raise ValueError("workload params contain invalid identifiers or scope values")
        return normalized.unique(subset=list(_COLUMNS))

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

    @staticmethod
    def _sha256_path(path: Path) -> str | None:
        try:
            return hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            return None

    @staticmethod
    def _is_sha256(value: object) -> bool:
        return (
            isinstance(value, str)
            and len(value) == 64
            and value == value.lower()
            and all(character in "0123456789abcdef" for character in value)
        )

    @staticmethod
    def _is_nonnegative_int(value: object) -> TypeGuard[int]:
        return isinstance(value, int) and not isinstance(value, bool) and value >= 0

    def _warn_invalid(self, reason: str) -> None:
        logger.warning(
            "ignoring invalid player/team workload {}: {}",
            reason,
            self._manifest_path,
        )


def player_team_season_workload_base_unit(
    params: Mapping[str, object],
) -> PlayerTeamSeasonWorkloadBaseUnit | None:
    """Return the canonical workload identity from extraction parameters."""
    season = params.get("season")
    season_type = params.get("season_type")
    player_id = params.get("player_id")
    team_id = params.get("team_id")
    if (
        not isinstance(season, str)
        or not isinstance(season_type, str)
        or not season_type.strip()
        or isinstance(player_id, bool)
        or isinstance(team_id, bool)
        or not isinstance(player_id, int | str)
        or not isinstance(team_id, int | str)
    ):
        return None
    try:
        season_year = int(season[:4])
        normalized_player_id = int(player_id)
        normalized_team_id = int(team_id)
    except (TypeError, ValueError):
        return None
    if season_string(season_year) != season or normalized_player_id <= 0 or normalized_team_id <= 0:
        return None
    return season_year, season_type, normalized_player_id, normalized_team_id


def player_team_season_workload_base_units_sha256(
    units: frozenset[PlayerTeamSeasonWorkloadBaseUnit] | set[PlayerTeamSeasonWorkloadBaseUnit],
) -> str:
    payload = [list(unit) for unit in sorted(units)]
    return hashlib.sha256(json.dumps(payload, separators=(",", ":")).encode()).hexdigest()


def build_player_team_season_workload_scope(
    store: PlayerTeamSeasonWorkloadStore,
    *,
    seasons: list[str],
    season_types: list[str],
) -> PlayerTeamSeasonWorkloadScope:
    """Build the exact generation, pair, and base-identity contract for a lane scope."""
    requested_pairs = {
        (str(season), str(season_type)) for season in seasons for season_type in season_types
    }
    if not requested_pairs or any(
        not season.strip() or not season_type.strip() for season, season_type in requested_pairs
    ):
        raise ValueError("player_team_season workload scope is missing")

    integrity = store.integrity_attestation()
    if integrity is None:
        raise ValueError("player_team_season workload sidecars are missing or invalid")

    coverage = store.load_coverage(seasons=seasons, season_types=season_types)
    invalid_pairs = requested_pairs & coverage.invalid_pairs
    if invalid_pairs:
        raise ValueError(
            f"player_team_season workload has invalid requested pairs: {sorted(invalid_pairs)}"
        )
    missing_pairs = requested_pairs - coverage.covered_pairs
    if missing_pairs:
        raise ValueError(
            f"player_team_season workload does not cover requested pairs: {sorted(missing_pairs)}"
        )

    base_units: list[PlayerTeamSeasonWorkloadBaseUnit] = []
    actual_counts: Counter[tuple[str, str]] = Counter()
    for params in store.load_params(seasons=seasons, season_types=season_types):
        identity = player_team_season_workload_base_unit(params)
        if identity is None:
            raise ValueError("player_team_season workload identity is invalid")
        season_year, season_type, _player_id, _team_id = identity
        pair = (season_string(season_year), season_type)
        if pair not in requested_pairs:
            raise ValueError(f"player_team_season workload row is outside lane scope: {pair}")
        base_units.append(identity)
        actual_counts[pair] += 1

    unique_base_units = frozenset(base_units)
    if len(base_units) != len(unique_base_units):
        raise ValueError("player_team_season workload contains duplicate base identities")

    requested_pair_payload: list[dict[str, int | str]] = []
    for season, season_type in sorted(requested_pairs):
        row_count = int(coverage.counts_by_pair.get((season, season_type), 0))
        if actual_counts[(season, season_type)] != row_count:
            raise ValueError(
                f"player_team_season workload pair count mismatch for {season}/{season_type}"
            )
        requested_pair_payload.append(
            {"season": season, "season_type": season_type, "row_count": row_count}
        )

    return PlayerTeamSeasonWorkloadScope(
        base_units=unique_base_units,
        contract={
            "integrity": integrity,
            "requested_pairs": requested_pair_payload,
            "expected_base_unit_count": len(unique_base_units),
            "expected_base_units_sha256": player_team_season_workload_base_units_sha256(
                unique_base_units
            ),
            "expected_empty": not unique_base_units,
        },
    )
