from __future__ import annotations

import hashlib
import io
import json
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING

import polars as pl
from loguru import logger

from nbadb.core.types import validate_sql_identifier

if TYPE_CHECKING:
    from collections.abc import Iterable

    import duckdb


_WRITE_LOCK = threading.Lock()


@dataclass(frozen=True, slots=True)
class StagingChunkMetadata:
    run_mode: str
    lane_id: str
    pattern: str
    chunk_index: int
    params_digest: str
    entries_digest: str
    source_endpoint_name: str | None = None
    source_params_digest: str | None = None

    @property
    def source_label(self) -> str:
        return f"{self.run_mode}:{self.pattern}:{self.lane_id}:{self.chunk_index}"


@dataclass(frozen=True, slots=True)
class StagingFrameBatch:
    frames: dict[str, pl.DataFrame]
    metadata: StagingChunkMetadata
    expected_staging_keys: tuple[str, ...] = ()
    dedupe_materialized: bool = False
    replace_existing_chunk: bool = False


@dataclass(frozen=True, slots=True)
class StagingPersistResult:
    staging_tables: int = 0
    rows_persisted: int = 0
    chunks_inserted: int = 0
    chunks_replayed: int = 0


def digest_jsonable(value: object) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


def frame_content_hash(df: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    df.write_ipc(buffer)
    schema_payload = json.dumps(
        [(name, str(dtype)) for name, dtype in zip(df.columns, df.dtypes, strict=True)],
        separators=(",", ":"),
    )
    digest = hashlib.sha256(schema_payload.encode("utf-8"))
    digest.update(buffer.getvalue())
    return digest.hexdigest()


def _quoted_csv(columns: Iterable[str]) -> str:
    return ", ".join(validate_sql_identifier(column) for column in columns)


class StagingBatchStore:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn
        self.ensure_schema()

    def ensure_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS _staging_chunk_journal (
                chunk_id VARCHAR NOT NULL,
                staging_key VARCHAR NOT NULL,
                row_count BIGINT NOT NULL,
                content_hash VARCHAR NOT NULL,
                source_label VARCHAR,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (chunk_id, staging_key)
            )
            """
        )

    def persist_frames(
        self,
        frames: dict[str, pl.DataFrame],
        *,
        metadata: StagingChunkMetadata,
        expected_staging_keys: Iterable[str] | None = None,
        materialize: bool = False,
        dedupe_materialized: bool = False,
        replace_existing_chunk: bool = False,
    ) -> StagingPersistResult:
        return self.persist_frame_batches(
            [
                StagingFrameBatch(
                    frames=frames,
                    metadata=metadata,
                    expected_staging_keys=tuple(expected_staging_keys or ()),
                    dedupe_materialized=dedupe_materialized,
                    replace_existing_chunk=replace_existing_chunk,
                )
            ],
            materialize=materialize,
        )

    def persist_frame_batches(
        self,
        batches: Iterable[StagingFrameBatch],
        *,
        materialize: bool = False,
    ) -> StagingPersistResult:
        batch_list = list(batches)
        if not batch_list:
            return StagingPersistResult()

        result = StagingPersistResult()
        changed_keys: list[str] = []
        with _WRITE_LOCK:
            self._conn.execute("BEGIN TRANSACTION")
            try:
                tables = rows = inserted = replayed = 0
                for batch in batch_list:
                    batch_result = self._persist_frame_batch(batch, changed_keys)
                    tables += batch_result.staging_tables
                    rows += batch_result.rows_persisted
                    inserted += batch_result.chunks_inserted
                    replayed += batch_result.chunks_replayed

                if materialize and changed_keys:
                    self.materialize(sorted(set(changed_keys)))
                self._conn.execute("COMMIT")
                result = StagingPersistResult(
                    staging_tables=tables,
                    rows_persisted=rows,
                    chunks_inserted=inserted,
                    chunks_replayed=replayed,
                )
            except Exception:
                self._conn.execute("ROLLBACK")
                raise
        logger.info(
            "persisted {} staging chunk tables, {} rows ({} replayed)",
            result.staging_tables,
            result.rows_persisted,
            result.chunks_replayed,
        )
        return result

    def _persist_frame_batch(
        self,
        batch: StagingFrameBatch,
        changed_keys: list[str],
    ) -> StagingPersistResult:
        tables = rows = inserted = replayed = 0
        expected_keys = sorted(set(batch.frames) | set(batch.expected_staging_keys))
        for staging_key in expected_keys:
            df = batch.frames.get(staging_key, pl.DataFrame())
            safe_key = validate_sql_identifier(staging_key)
            content_hash = frame_content_hash(df)
            chunk_id = self._chunk_id(safe_key, batch.metadata)
            existing = self._existing_chunk_hash(chunk_id, safe_key)
            if existing is None:
                legacy_chunk_id = self._legacy_source_chunk_id(safe_key, batch.metadata)
                if legacy_chunk_id is not None:
                    existing = self._existing_chunk_hash(legacy_chunk_id, safe_key)
                    if existing is not None:
                        if existing == content_hash:
                            self._rename_chunk(
                                safe_key,
                                old_chunk_id=legacy_chunk_id,
                                new_chunk_id=chunk_id,
                            )
                        elif batch.replace_existing_chunk:
                            self._delete_chunk(safe_key, legacy_chunk_id)
                            existing = None
                        else:
                            msg = (
                                f"staging chunk hash mismatch for {safe_key} "
                                f"{legacy_chunk_id}: {existing} != {content_hash}"
                            )
                            raise RuntimeError(msg)
            if existing is not None:
                if existing != content_hash:
                    if batch.replace_existing_chunk:
                        self._delete_chunk(safe_key, chunk_id)
                        existing = None
                    else:
                        msg = (
                            f"staging chunk hash mismatch for {safe_key} "
                            f"{chunk_id}: {existing} != {content_hash}"
                        )
                        raise RuntimeError(msg)
                if existing is not None:
                    replayed += 1
                    continue

            frame_to_append = df
            if not df.is_empty():
                frame_to_append = self._legacy_filtered_frame(safe_key, df)
                if batch.dedupe_materialized and self._table_exists(safe_key):
                    frame_to_append = self._filtered_against_table(safe_key, frame_to_append)
                self._append_chunk_frame(
                    safe_key,
                    chunk_id,
                    batch.metadata.chunk_index,
                    frame_to_append,
                )
            self._record_chunk(
                chunk_id,
                safe_key,
                row_count=df.height,
                content_hash=content_hash,
                source_label=batch.metadata.source_label,
            )
            if batch.replace_existing_chunk or not frame_to_append.is_empty():
                changed_keys.append(safe_key)
            tables += 1
            rows += frame_to_append.height
            inserted += 1
        return StagingPersistResult(
            staging_tables=tables,
            rows_persisted=rows,
            chunks_inserted=inserted,
            chunks_replayed=replayed,
        )

    def materialize(self, staging_keys: Iterable[str] | None = None) -> int:
        keys = list(staging_keys) if staging_keys is not None else self._chunk_staging_keys()
        count = 0
        for staging_key in keys:
            safe_key = validate_sql_identifier(staging_key)
            internal = self._chunk_table_name(safe_key)
            if not self._table_exists(internal):
                continue
            self._conn.execute(
                f"""
                CREATE OR REPLACE TABLE {safe_key} AS
                SELECT * EXCLUDE (_nbadb_chunk_id, _nbadb_chunk_index, _nbadb_row_index)
                FROM {internal}
                ORDER BY _nbadb_chunk_index, _nbadb_row_index, _nbadb_chunk_id
                """
            )
            count += 1
        return count

    def _chunk_id(
        self,
        staging_key: str,
        metadata: StagingChunkMetadata,
    ) -> str:
        if metadata.source_endpoint_name is not None and metadata.source_params_digest is not None:
            payload = {
                "staging_key": staging_key,
                "pattern": metadata.pattern,
                "source_endpoint_name": metadata.source_endpoint_name,
                "source_params_digest": metadata.source_params_digest,
            }
        else:
            payload = {
                "staging_key": staging_key,
                "run_mode": metadata.run_mode,
                "lane_id": metadata.lane_id,
                "pattern": metadata.pattern,
                "chunk_index": metadata.chunk_index,
                "params_digest": metadata.params_digest,
                "entries_digest": metadata.entries_digest,
            }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _legacy_source_chunk_id(
        self,
        staging_key: str,
        metadata: StagingChunkMetadata,
    ) -> str | None:
        if metadata.source_endpoint_name is None or metadata.source_params_digest is None:
            return None
        payload = {
            "staging_key": staging_key,
            "run_mode": metadata.run_mode,
            "pattern": metadata.pattern,
            "source_endpoint_name": metadata.source_endpoint_name,
            "source_params_digest": metadata.source_params_digest,
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def _existing_chunk_hash(self, chunk_id: str, staging_key: str) -> str | None:
        row = self._conn.execute(
            """
            SELECT content_hash
            FROM _staging_chunk_journal
            WHERE chunk_id = $1 AND staging_key = $2
            """,
            [chunk_id, staging_key],
        ).fetchone()
        return str(row[0]) if row else None

    def _record_chunk(
        self,
        chunk_id: str,
        staging_key: str,
        *,
        row_count: int,
        content_hash: str,
        source_label: str,
    ) -> None:
        self._conn.execute(
            """
            INSERT INTO _staging_chunk_journal
                (chunk_id, staging_key, row_count, content_hash, source_label)
            VALUES ($1, $2, $3, $4, $5)
            """,
            [chunk_id, staging_key, row_count, content_hash, source_label],
        )

    def _rename_chunk(self, staging_key: str, *, old_chunk_id: str, new_chunk_id: str) -> None:
        if old_chunk_id == new_chunk_id:
            return
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            self._conn.execute(
                f"UPDATE {internal} SET _nbadb_chunk_id = $1 WHERE _nbadb_chunk_id = $2",
                [new_chunk_id, old_chunk_id],
            )
        self._conn.execute(
            """
            UPDATE _staging_chunk_journal
            SET chunk_id = $1
            WHERE chunk_id = $2 AND staging_key = $3
            """,
            [new_chunk_id, old_chunk_id, staging_key],
        )

    def _delete_chunk(self, staging_key: str, chunk_id: str) -> None:
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            self._conn.execute(
                f"DELETE FROM {internal} WHERE _nbadb_chunk_id = $1",
                [chunk_id],
            )
        self._conn.execute(
            """
            DELETE FROM _staging_chunk_journal
            WHERE chunk_id = $1 AND staging_key = $2
            """,
            [chunk_id, staging_key],
        )

    def _legacy_filtered_frame(self, staging_key: str, df: pl.DataFrame) -> pl.DataFrame:
        internal = self._chunk_table_name(staging_key)
        if not self._table_exists(staging_key) or self._table_exists(internal):
            return df

        temp_name = "_nbadb_legacy_chunk_tmp"
        filtered = self._filtered_against_table(staging_key, df, temp_name=temp_name)
        self._seed_legacy_table(staging_key)
        return filtered

    def _filtered_against_table(
        self,
        staging_key: str,
        df: pl.DataFrame,
        *,
        temp_name: str = "_nbadb_staging_diff_tmp",
    ) -> pl.DataFrame:
        if df.is_empty():
            return df
        if not set(df.columns).issubset(self._data_columns(staging_key)):
            return df
        self._conn.register(temp_name, df)
        try:
            columns = _quoted_csv(df.columns)
            return self._conn.execute(
                f"SELECT {columns} FROM {temp_name} EXCEPT ALL SELECT {columns} FROM {staging_key}"
            ).pl()
        finally:
            self._conn.unregister(temp_name)

    def _seed_legacy_table(self, staging_key: str) -> None:
        internal = self._chunk_table_name(staging_key)
        if self._table_exists(internal):
            return
        self._conn.execute(
            f"""
            CREATE TABLE {internal} AS
            SELECT
                -1 AS _nbadb_chunk_index,
                row_number() OVER () - 1 AS _nbadb_row_index,
                *,
                '__legacy__' AS _nbadb_chunk_id
            FROM {staging_key}
            """
        )

    def _append_chunk_frame(
        self,
        staging_key: str,
        chunk_id: str,
        chunk_index: int,
        df: pl.DataFrame,
    ) -> None:
        internal = self._chunk_table_name(staging_key)
        if df.is_empty():
            return
        chunk_df = df.with_row_index("_nbadb_row_index").with_columns(
            pl.lit(chunk_index).alias("_nbadb_chunk_index"),
            pl.lit(chunk_id).alias("_nbadb_chunk_id"),
        )
        temp_name = "_nbadb_staging_chunk_tmp"
        self._conn.register(temp_name, chunk_df)
        try:
            if self._table_exists(internal):
                self._ensure_chunk_table_shape(internal, temp_name)
                target_columns = [name for name, _ in self._table_columns(internal)]
                select_columns = self._aligned_select_columns(temp_name, target_columns, internal)
                self._conn.execute(
                    f"""
                    INSERT INTO {internal} ({_quoted_csv(target_columns)})
                    SELECT {", ".join(select_columns)}
                    FROM {temp_name}
                    """
                )
            else:
                self._conn.execute(f"CREATE TABLE {internal} AS SELECT * FROM {temp_name}")
        finally:
            self._conn.unregister(temp_name)

    def _chunk_staging_keys(self) -> list[str]:
        prefix = "_staging_chunks__"
        rows = self._conn.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'main'
            """
        ).fetchall()
        return sorted(
            table_name[len(prefix) :]
            for row in rows
            if (table_name := str(row[0])).startswith(prefix)
        )

    def _chunk_table_name(self, staging_key: str) -> str:
        return validate_sql_identifier(f"_staging_chunks__{staging_key}")

    def _data_columns(self, table_name: str) -> set[str]:
        return {
            name
            for name, _ in self._table_columns(table_name)
            if name
            not in {
                "_nbadb_chunk_id",
                "_nbadb_chunk_index",
                "_nbadb_row_index",
            }
        }

    def _table_columns(self, table_name: str) -> list[tuple[str, str]]:
        rows = self._conn.execute(
            """
            SELECT column_name, data_type
            FROM information_schema.columns
            WHERE table_schema = 'main' AND table_name = $1
            ORDER BY ordinal_position
            """,
            [table_name],
        ).fetchall()
        return [(str(name), str(data_type)) for name, data_type in rows]

    def _ensure_chunk_table_shape(self, internal: str, temp_name: str) -> None:
        internal_columns = dict(self._table_columns(internal))
        if "_nbadb_chunk_index" not in internal_columns:
            self._conn.execute(f"ALTER TABLE {internal} ADD COLUMN _nbadb_chunk_index BIGINT")
            self._conn.execute(
                f"UPDATE {internal} SET _nbadb_chunk_index = 0 WHERE _nbadb_chunk_index IS NULL"
            )
            internal_columns = dict(self._table_columns(internal))

        for column, data_type in self._table_columns(temp_name):
            if column not in internal_columns:
                safe_column = validate_sql_identifier(column)
                self._conn.execute(f"ALTER TABLE {internal} ADD COLUMN {safe_column} {data_type}")

    def _aligned_select_columns(
        self,
        temp_name: str,
        target_columns: list[str],
        internal: str,
    ) -> list[str]:
        temp_columns = dict(self._table_columns(temp_name))
        internal_columns = dict(self._table_columns(internal))
        select_columns: list[str] = []
        for column in target_columns:
            safe_column = validate_sql_identifier(column)
            target_type = internal_columns[column]
            if column in temp_columns:
                select_columns.append(f"CAST({safe_column} AS {target_type}) AS {safe_column}")
            else:
                select_columns.append(f"CAST(NULL AS {target_type}) AS {safe_column}")
        return select_columns

    def _table_exists(self, table_name: str) -> bool:
        row = self._conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = $1
            """,
            [table_name],
        ).fetchone()
        return row is not None
