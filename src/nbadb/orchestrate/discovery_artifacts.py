from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Literal

import polars as pl
from loguru import logger

from nbadb.orchestrate.persistence import atomic_write_path, atomic_write_text

_ARTIFACT_VERSION = 2
_ARTIFACT_FORMAT = "parquet"

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
        payload = json.dumps(_scope_payload(self), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True, slots=True)
class _ArtifactIntegrity:
    generation_path: Path
    row_count: int
    content_sha256: str
    schema: tuple[tuple[str, str], ...]


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
        manifest_path = self._manifest_path(scope)
        if not manifest_path.exists():
            return None

        payload = self._load_manifest(manifest_path)
        if payload is None:
            return None
        if payload.get("artifact_version") == 1:
            return self._load_and_promote_legacy_exact(scope, payload, manifest_path)

        integrity = self._load_integrity(scope, payload, manifest_path)
        if integrity is None:
            return None

        try:
            artifact_bytes = integrity.generation_path.read_bytes()
        except OSError as exc:
            logger.warning(
                "ignoring unreadable discovery artifact {}: {}",
                integrity.generation_path,
                type(exc).__name__,
            )
            return None

        actual_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        if actual_sha256 != integrity.content_sha256:
            logger.warning(
                "ignoring discovery artifact with content digest mismatch: {}",
                integrity.generation_path,
            )
            return None

        frame = self._read_validated_frame(
            scope,
            artifact_bytes,
            artifact_path=integrity.generation_path,
            row_count=integrity.row_count,
            expected_schema=integrity.schema,
        )
        if frame is None:
            return None
        return frame

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
        return _concat_frames(combo_frames)

    def upsert_frame(
        self,
        scope: DiscoveryArtifactScope,
        frame: pl.DataFrame,
        *,
        provenance: str,
    ) -> pl.DataFrame:
        if not self.is_available():
            return frame
        _validate_artifact_kind_schema(scope, frame)
        manifest_path = self._manifest_path(scope)

        buffer = BytesIO()
        frame.write_parquet(buffer)
        artifact_bytes = buffer.getvalue()
        content_sha256 = hashlib.sha256(artifact_bytes).hexdigest()
        generation_path = self._generation_path(scope, content_sha256)

        def _write_artifact(path: Path) -> None:
            path.write_bytes(artifact_bytes)

        generation_sha256 = _sha256_path(generation_path)
        if generation_sha256 != content_sha256:
            atomic_write_path(generation_path, _write_artifact)
            generation_sha256 = _sha256_path(generation_path)
        if generation_sha256 != content_sha256:
            raise OSError(f"discovery artifact generation verification failed: {generation_path}")

        manifest_payload = {
            "artifact_kind": scope.kind,
            "artifact_version": _ARTIFACT_VERSION,
            "scope": _scope_payload(scope),
            "content": {
                "format": _ARTIFACT_FORMAT,
                "path": generation_path.name,
                "row_count": frame.height,
                "schema": _schema_payload(frame),
                "sha256": content_sha256,
            },
            "updated_at": datetime.now(UTC).isoformat(),
            "provenance": provenance,
        }
        atomic_write_text(
            manifest_path,
            json.dumps(manifest_payload, indent=2, sort_keys=True) + "\n",
        )
        return frame

    def load_ids(self, scope: DiscoveryArtifactScope, *, column: str = "value") -> list[int]:
        frame = self.load_frame(scope)
        if frame is None:
            return []
        return self._ids_from_frame(frame, column=column)

    def load_ids_for_seasons(
        self,
        *,
        kind: ArtifactKind,
        seasons: tuple[str, ...],
        variant: str = "default",
        column: str = "value",
    ) -> list[int] | None:
        """Load a union of per-season ID artifacts when every season is cached."""
        if not seasons:
            return []

        values: list[int] = []
        for season in seasons:
            frame = self.load_frame(
                DiscoveryArtifactScope(
                    kind=kind,
                    seasons=(season,),
                    season_types=(),
                    variant=variant,
                )
            )
            if frame is None:
                return None
            season_values = self._ids_from_frame(frame, column=column)
            if kind in {"player_ids_active", "player_ids_all"} and not season_values:
                logger.warning(
                    "ignoring empty player-ID discovery artifact for required season {}",
                    season,
                )
                return None
            values.extend(season_values)

        return sorted({int(value) for value in values})

    def upsert_ids(
        self,
        scope: DiscoveryArtifactScope,
        values: list[int],
        *,
        provenance: str,
        column: str = "value",
    ) -> list[int]:
        frame = pl.DataFrame(
            {column: pl.Series(column, sorted({int(value) for value in values}), dtype=pl.Int64)}
        )
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
        """Return the fixed legacy-v1 artifact path for exact-scope promotion."""
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.parquet"

    def _generation_path(
        self,
        scope: DiscoveryArtifactScope,
        content_sha256: str,
    ) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / _generation_filename(scope, content_sha256)

    def _manifest_path(self, scope: DiscoveryArtifactScope) -> Path:
        root_dir = self._root_dir
        assert root_dir is not None
        return root_dir / f"{scope.kind}.{scope.digest()}.json"

    def _load_integrity(
        self,
        scope: DiscoveryArtifactScope,
        payload: dict[str, object],
        manifest_path: Path,
    ) -> _ArtifactIntegrity | None:
        content = payload.get("content")
        row_count = content.get("row_count") if isinstance(content, dict) else None
        content_sha256 = content.get("sha256") if isinstance(content, dict) else None
        generation_name = content.get("path") if isinstance(content, dict) else None
        schema = _parse_schema_payload(content.get("schema") if isinstance(content, dict) else None)
        expected_generation_name = (
            _generation_filename(scope, content_sha256)
            if isinstance(content_sha256, str) and _is_sha256(content_sha256)
            else None
        )
        valid = (
            type(payload.get("artifact_version")) is int
            and payload["artifact_version"] == _ARTIFACT_VERSION
            and payload.get("artifact_kind") == scope.kind
            and payload.get("scope") == _scope_payload(scope)
            and isinstance(content, dict)
            and content.get("format") == _ARTIFACT_FORMAT
            and isinstance(generation_name, str)
            and generation_name == expected_generation_name
            and Path(generation_name).name == generation_name
            and type(row_count) is int
            and row_count >= 0
            and _is_sha256(content_sha256)
            and schema is not None
            and isinstance(payload.get("updated_at"), str)
            and isinstance(payload.get("provenance"), str)
        )
        if not valid:
            logger.warning(
                "ignoring invalid or mismatched discovery artifact manifest {}",
                manifest_path,
            )
            return None
        assert isinstance(row_count, int)
        assert isinstance(content_sha256, str)
        assert isinstance(generation_name, str)
        assert schema is not None
        return _ArtifactIntegrity(
            generation_path=self._generation_path(scope, content_sha256),
            row_count=row_count,
            content_sha256=content_sha256,
            schema=schema,
        )

    @staticmethod
    def _load_manifest(manifest_path: Path) -> dict[str, object] | None:
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            logger.warning(
                "ignoring unreadable discovery artifact manifest {}: {}",
                manifest_path,
                type(exc).__name__,
            )
            return None
        if not isinstance(payload, dict):
            logger.warning("ignoring non-object discovery artifact manifest {}", manifest_path)
            return None
        return payload

    def _load_and_promote_legacy_exact(
        self,
        scope: DiscoveryArtifactScope,
        payload: dict[str, object],
        manifest_path: Path,
    ) -> pl.DataFrame | None:
        if not _is_promotable_legacy_scope(scope):
            logger.warning(
                "ignoring legacy aggregate discovery artifact manifest {}",
                manifest_path,
            )
            return None

        legacy_path = self._artifact_path(scope)
        legacy_scope = payload.get("scope")
        row_count = payload.get("row_count")
        recorded_path = payload.get("artifact_path")
        valid = (
            type(payload.get("artifact_version")) is int
            and payload["artifact_version"] == 1
            and payload.get("artifact_kind") == scope.kind
            and legacy_scope == _legacy_scope_payload(scope)
            and type(row_count) is int
            and row_count >= 0
            and isinstance(recorded_path, str)
            and Path(recorded_path).name == legacy_path.name
            and isinstance(payload.get("updated_at"), str)
            and isinstance(payload.get("provenance"), str)
            and legacy_path.name == f"{scope.kind}.{scope.digest()}.parquet"
        )
        if not valid:
            logger.warning(
                "ignoring invalid or mismatched legacy discovery artifact manifest {}",
                manifest_path,
            )
            return None

        try:
            artifact_bytes = legacy_path.read_bytes()
        except OSError as exc:
            logger.warning(
                "ignoring unreadable legacy discovery artifact {}: {}",
                legacy_path,
                type(exc).__name__,
            )
            return None
        assert isinstance(row_count, int)
        frame = self._read_validated_frame(
            scope,
            artifact_bytes,
            artifact_path=legacy_path,
            row_count=row_count,
        )
        if frame is None:
            return None

        provenance = str(payload["provenance"])
        self.upsert_frame(scope, frame, provenance=f"legacy-v1-promotion:{provenance}")
        logger.info("promoted exact legacy discovery artifact {} to version 2", legacy_path)
        return frame

    @staticmethod
    def _read_validated_frame(
        scope: DiscoveryArtifactScope,
        artifact_bytes: bytes,
        *,
        artifact_path: Path,
        row_count: int,
        expected_schema: tuple[tuple[str, str], ...] | None = None,
    ) -> pl.DataFrame | None:
        try:
            frame = pl.read_parquet(BytesIO(artifact_bytes))
        except (OSError, pl.exceptions.PolarsError) as exc:
            logger.warning(
                "ignoring unreadable discovery artifact {}: {}",
                artifact_path,
                type(exc).__name__,
            )
            return None
        if frame.height != row_count:
            logger.warning(
                "ignoring discovery artifact with row-count mismatch: {}",
                artifact_path,
            )
            return None
        if expected_schema is not None and _schema_tuple(frame) != expected_schema:
            logger.warning(
                "ignoring discovery artifact with schema-manifest mismatch: {}",
                artifact_path,
            )
            return None
        try:
            _validate_artifact_kind_schema(scope, frame)
        except ValueError as exc:
            logger.warning(
                "ignoring discovery artifact with invalid kind schema {}: {}",
                artifact_path,
                exc,
            )
            return None
        return frame

    @staticmethod
    def _ids_from_frame(frame: pl.DataFrame, *, column: str) -> list[int]:
        if frame.is_empty() or column not in frame.columns:
            return []
        return [
            int(value)
            for value in (
                frame.get_column(column).drop_nulls().cast(pl.Int64, strict=False).to_list()
            )
        ]


def _scope_payload(scope: DiscoveryArtifactScope) -> dict[str, object]:
    return {
        "kind": scope.kind,
        "seasons": list(scope.seasons),
        "season_types": list(scope.season_types),
        "variant": scope.variant,
    }


def _legacy_scope_payload(scope: DiscoveryArtifactScope) -> dict[str, object]:
    return {
        "seasons": list(scope.seasons),
        "season_types": list(scope.season_types),
        "variant": scope.variant,
    }


def _generation_filename(scope: DiscoveryArtifactScope, content_sha256: str) -> str:
    return f"{scope.kind}.{scope.digest()}.{content_sha256}.parquet"


def _is_promotable_legacy_scope(scope: DiscoveryArtifactScope) -> bool:
    if scope.kind == "league_game_log":
        return len(scope.seasons) == 1 and len(scope.season_types) == 1
    return (
        scope.kind in {"player_ids_active", "player_ids_all"}
        and len(scope.seasons) == 1
        and not scope.season_types
    )


def _schema_payload(frame: pl.DataFrame) -> list[dict[str, str]]:
    return [{"name": name, "dtype": str(dtype)} for name, dtype in frame.schema.items()]


def _schema_tuple(frame: pl.DataFrame) -> tuple[tuple[str, str], ...]:
    return tuple((name, str(dtype)) for name, dtype in frame.schema.items())


def _parse_schema_payload(value: object) -> tuple[tuple[str, str], ...] | None:
    if not isinstance(value, list):
        return None
    parsed: list[tuple[str, str]] = []
    for item in value:
        name = item.get("name") if isinstance(item, dict) else None
        dtype = item.get("dtype") if isinstance(item, dict) else None
        if (
            not isinstance(item, dict)
            or set(item) != {"name", "dtype"}
            or not isinstance(name, str)
            or not name
            or not isinstance(dtype, str)
            or not dtype
        ):
            return None
        parsed.append((name, dtype))
    if len({name for name, _dtype in parsed}) != len(parsed):
        return None
    return tuple(parsed)


def _validate_artifact_kind_schema(
    scope: DiscoveryArtifactScope,
    frame: pl.DataFrame,
) -> None:
    if scope.kind == "league_game_log":
        required_columns = {"game_id", "game_date"}
        missing_columns = required_columns - set(frame.columns)
        if missing_columns:
            raise ValueError(f"league_game_log is missing columns {sorted(missing_columns)}")
        if frame.schema["game_id"] != pl.String:
            raise ValueError("league_game_log.game_id must be String")
        if frame.schema["game_date"].base_type() not in {pl.String, pl.Date, pl.Datetime}:
            raise ValueError("league_game_log.game_date must be String, Date, or Datetime")
        if frame.get_column("game_id").null_count() or (
            not frame.is_empty()
            and frame.select(pl.col("game_id").str.strip_chars().eq("").any()).item()
        ):
            raise ValueError("league_game_log.game_id must contain non-empty values")
        if frame.get_column("game_date").null_count():
            raise ValueError("league_game_log.game_date must not contain nulls")
        if (
            frame.schema["game_date"] == pl.String
            and not frame.is_empty()
            and frame.select(pl.col("game_date").str.strip_chars().eq("").any()).item()
        ):
            raise ValueError("league_game_log.game_date must contain non-empty values")
        return

    if frame.columns != ["value"]:
        raise ValueError(f"{scope.kind} must contain only the value column")
    if not frame.schema["value"].is_integer():
        raise ValueError(f"{scope.kind}.value must be an integer dtype")
    if frame.get_column("value").null_count():
        raise ValueError(f"{scope.kind}.value must not contain nulls")
    if not frame.is_empty() and frame.select(pl.col("value").le(0).any()).item():
        raise ValueError(f"{scope.kind}.value must contain only positive identifiers")


def _concat_frames(frames: list[pl.DataFrame]) -> pl.DataFrame:
    if not frames:
        return pl.DataFrame()
    if len(frames) == 1:
        return frames[0].clone()
    return pl.concat(frames, how="diagonal_relaxed")


def _sha256_path(path: Path) -> str | None:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )
