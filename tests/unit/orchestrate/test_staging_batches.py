from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import replace
from datetime import UTC, date, datetime
from decimal import Decimal
from threading import Event, Thread

import duckdb
import polars as pl
import pyarrow as pa
import pyarrow.compute as pa_compute
import pyarrow.ipc as pa_ipc
import pytest

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding
from nbadb.extract.nba_api_adapter import (
    LOSSLESS_FALLBACK_SCHEMA,
    LOSSLESS_FALLBACK_STAGING_KEY,
)
from nbadb.orchestrate import staging_batches as staging_batches_module
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
    CommittedStagingRowSliceV2,
    SourceScopeReplacementAttestation,
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
    frame_content_hash,
    frame_schema_hash,
    validate_committed_row_partition,
)


def _metadata(*, chunk_index: int = 0) -> StagingChunkMetadata:
    return StagingChunkMetadata(
        run_mode="init",
        lane_id="init.season.test",
        pattern="season",
        chunk_index=chunk_index,
        params_digest="params",
        entries_digest="entries",
    )


def _source_metadata(
    *,
    run_mode: str = "init",
    chunk_index: int = 0,
    params_digest: str = "chunk-params",
    entries_digest: str = "entries",
    source_endpoint_name: str = "ep1",
    source_params_digest: str = "source-params",
) -> StagingChunkMetadata:
    return StagingChunkMetadata(
        run_mode=run_mode,
        lane_id="init.season.test",
        pattern="season",
        chunk_index=chunk_index,
        params_digest=params_digest,
        entries_digest=entries_digest,
        source_endpoint_name=source_endpoint_name,
        source_params_digest=source_params_digest,
    )


def _receipt_binding(
    *routes: str,
    receipt: str = "a" * 64,
) -> LogicalCallReceiptBinding:
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256=receipt,
        endpoint_name=routes[0].split(":", 1)[0],
        logical_parameters_sha256="b" * 64,
        provider_authority_sha256="c" * 64,
        result_route_ids=tuple(sorted(routes)),
    )


def _lossless_fallback_frame(*, response_receipt: str = "d" * 64) -> pl.DataFrame:
    common: dict[str, object | None] = {
        "response_receipt_sha256": response_receipt,
        "endpoint_slug": "fixtureendpoint",
        "result_set_name": "Stats",
        "result_set_occurrence": 0,
        "provider_index": 0,
        "canonical_index": None,
        "anomaly_codes_json": json.dumps(["additive_header"], separators=(",", ":")),
    }
    rows = [
        {
            **common,
            "record_kind": "result_set",
            "header_name": None,
            "header_ordinal": None,
            "row_ordinal": None,
            "value_kind": None,
            "canonical_json": None,
        },
        {
            **common,
            "record_kind": "header",
            "header_name": "EXTRA",
            "header_ordinal": 0,
            "row_ordinal": None,
            "value_kind": "string",
            "canonical_json": '"EXTRA"',
        },
        {
            **common,
            "record_kind": "row",
            "header_name": None,
            "header_ordinal": None,
            "row_ordinal": 0,
            "value_kind": "array",
            "canonical_json": "[1]",
        },
        {
            **common,
            "record_kind": "cell",
            "header_name": "EXTRA",
            "header_ordinal": 0,
            "row_ordinal": 0,
            "value_kind": "integer",
            "canonical_json": "1",
        },
    ]
    return pl.DataFrame(rows, schema=LOSSLESS_FALLBACK_SCHEMA, orient="row")


def _committed_readback(
    conn: duckdb.DuckDBPyConnection,
    frame: pl.DataFrame,
    *,
    staging_key: str = "stg_sample",
    source_params_digest: str = "readback-source",
    logical_receipt_sha256: str = "a" * 64,
) -> tuple[
    StagingBatchStore,
    LogicalCallReceiptBinding,
    CommittedStagingChunkReceiptV2,
    CommittedStagingFrameReadbackV2,
]:
    route = f"ep1:{staging_key}:0"
    binding = _receipt_binding(route, receipt=logical_receipt_sha256)
    store = StagingBatchStore(conn)
    store.persist_frames(
        {staging_key: frame},
        metadata=_source_metadata(source_params_digest=source_params_digest),
        receipt_binding=binding,
        result_route_ids_by_staging_key=((staging_key, route),),
    )
    receipt = store.committed_logical_call_receipts(binding)[0]
    return store, binding, receipt, store.committed_staging_frame_readback(receipt)


def _direct_v2_readback(
    frame: pl.DataFrame,
    *,
    staging_key: str = "stg_canonical",
) -> tuple[CommittedStagingChunkReceiptV2, CommittedStagingFrameReadbackV2]:
    content_sha256 = frame_content_hash(frame)
    receipt = CommittedStagingChunkReceiptV2(
        chunk_id="chunk-v2",
        staging_key=staging_key,
        canonical_frame_format=CANONICAL_FRAME_FORMAT,
        frame_content_hash_contract=FRAME_CONTENT_HASH_CONTRACT,
        frame_schema_hash_contract=FRAME_SCHEMA_HASH_CONTRACT,
        content_hash=content_sha256,
        persisted_row_count=frame.height,
        persisted_content_sha256=content_sha256,
        persisted_schema_sha256=frame_schema_hash(frame),
        logical_call_receipt_sha256="a" * 64,
        provider_authority_sha256="b" * 64,
        logical_parameters_sha256="c" * 64,
        result_route_id=f"endpoint:{staging_key}:0",
    )
    return receipt, CommittedStagingFrameReadbackV2.build(
        committed_receipt=receipt,
        frame=frame,
    )


def test_replaying_same_chunk_does_not_duplicate_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})

        first = store.persist_frames({"stg_sample": frame}, metadata=_metadata(), materialize=True)
        second = store.persist_frames({"stg_sample": frame}, metadata=_metadata(), materialize=True)

        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
    finally:
        conn.close()

    assert first.chunks_inserted == 1
    assert second.chunks_replayed == 1
    assert rows == [("001", 1)]


def test_same_source_replayed_in_different_chunk_group_does_not_duplicate_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})

        first = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(
                chunk_index=0,
                params_digest="chunk-a",
                source_params_digest="season-2024",
            ),
            materialize=False,
        )
        second = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(
                chunk_index=1,
                params_digest="chunk-b",
                source_params_digest="season-2024",
            ),
            materialize=False,
        )
        store.materialize(["stg_sample"])
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute(
            "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert first.chunks_inserted == 1
    assert second.chunks_replayed == 1
    assert journal_count == 1
    assert rows == [("001", 1)]


def test_same_source_replayed_with_different_entry_digest_does_not_duplicate_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})

        first = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(
                entries_digest="entries-a",
                source_params_digest="season-2024",
            ),
            materialize=False,
        )
        second = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(
                entries_digest="entries-b",
                source_params_digest="season-2024",
            ),
            materialize=False,
        )
        store.materialize(["stg_sample"])
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute(
            "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert first.chunks_inserted == 1
    assert second.chunks_replayed == 1
    assert journal_count == 1
    assert rows == [("001", 1)]


def test_same_chunk_with_different_content_fails() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
            metadata=_metadata(),
        )

        with pytest.raises(RuntimeError, match="staging chunk hash mismatch"):
            store.persist_frames(
                {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [2]})},
                metadata=_metadata(),
            )
    finally:
        conn.close()


def test_same_source_with_different_content_fails_across_chunk_groups() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
            metadata=_source_metadata(
                chunk_index=0,
                params_digest="chunk-a",
                source_params_digest="season-2024",
            ),
        )

        with pytest.raises(RuntimeError, match="staging chunk hash mismatch"):
            store.persist_frames(
                {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [2]})},
                metadata=_source_metadata(
                    chunk_index=1,
                    params_digest="chunk-b",
                    source_params_digest="season-2024",
                ),
            )
    finally:
        conn.close()


def test_replaceable_source_chunk_accepts_changed_refresh_content() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
            metadata=_source_metadata(run_mode="daily", source_params_digest="season-2024"),
            materialize=True,
            replace_existing_chunk=True,
        )
        result = store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [2]})},
            metadata=_source_metadata(run_mode="daily", source_params_digest="season-2024"),
            materialize=True,
            replace_existing_chunk=True,
        )
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_rows = conn.execute(
            """
            SELECT row_count
            FROM _staging_chunk_journal
            WHERE staging_key = 'stg_sample'
            """
        ).fetchall()
    finally:
        conn.close()

    assert result.chunks_inserted == 1
    assert rows == [("001", 2)]
    assert journal_rows == [(1,)]


def test_same_source_across_init_and_daily_does_not_duplicate_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})
        first = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(run_mode="init", source_params_digest="season-2024"),
            materialize=False,
        )
        second = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(run_mode="daily", source_params_digest="season-2024"),
            materialize=False,
            replace_existing_chunk=True,
        )
        store.materialize(["stg_sample"])
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute(
            "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert first.chunks_inserted == 1
    assert second.chunks_replayed == 1
    assert journal_count == 1
    assert rows == [("001", 1)]


def test_daily_source_replaces_legacy_run_mode_chunk_id() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        legacy_metadata = _source_metadata(
            run_mode="daily",
            source_params_digest="season-2024",
        )
        legacy_chunk_id = store._legacy_source_chunk_id("stg_sample", legacy_metadata)
        assert legacy_chunk_id is not None
        store._append_chunk_frame(
            "stg_sample",
            legacy_chunk_id,
            0,
            pl.DataFrame({"game_id": ["001"], "value": [1]}),
        )
        store._record_chunk(
            legacy_chunk_id,
            "stg_sample",
            row_count=1,
            content_hash="0" * 64,
            source_label=legacy_metadata.source_label,
            persisted_frame=pl.DataFrame({"game_id": ["001"], "value": [1]}),
            receipt_binding=None,
            result_route_id=None,
        )

        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [2]})},
            metadata=legacy_metadata,
            materialize=True,
            replace_existing_chunk=True,
        )
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute(
            "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows == [("001", 2)]
    assert journal_count == 1


def test_different_sources_with_same_content_preserve_distinct_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        frame = pl.DataFrame({"game_id": ["001"], "value": [1]})
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(source_params_digest="season-2024"),
            materialize=False,
        )
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(
                chunk_index=1,
                source_params_digest="season-2025",
            ),
            materialize=False,
        )
        store.materialize(["stg_sample"])
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
    finally:
        conn.close()

    assert rows == [("001", 1), ("001", 1)]


def test_persist_frame_batches_rolls_back_all_batches_on_failure() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["002"], "value": [2]})},
            metadata=_source_metadata(source_params_digest="source-b"),
            materialize=True,
        )

        with pytest.raises(RuntimeError, match="staging chunk hash mismatch"):
            store.persist_frame_batches(
                [
                    StagingFrameBatch(
                        frames={"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
                        metadata=_source_metadata(
                            chunk_index=1,
                            source_params_digest="source-a",
                        ),
                    ),
                    StagingFrameBatch(
                        frames={"stg_sample": pl.DataFrame({"game_id": ["002"], "value": [3]})},
                        metadata=_source_metadata(
                            chunk_index=1,
                            source_params_digest="source-b",
                        ),
                    ),
                ],
                materialize=True,
            )

        store.materialize(["stg_sample"])
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute(
            "SELECT count(*) FROM _staging_chunk_journal WHERE staging_key = 'stg_sample'"
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows == [("002", 2)]
    assert journal_count == 1


def test_existing_transaction_writer_commits_and_expires() -> None:
    conn = duckdb.connect(":memory:")
    batch = StagingFrameBatch(
        frames={"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
        metadata=_source_metadata(),
    )
    try:
        store = StagingBatchStore(conn)
        with store.existing_transaction_writer() as writer:
            conn.execute("BEGIN TRANSACTION")
            result = writer.persist_frame_batches([batch], materialize=True)
            conn.execute("COMMIT")
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        journal_count = conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0]
        with pytest.raises(RuntimeError, match="no longer active"):
            writer.persist_frame_batches([batch])
    finally:
        conn.close()

    assert result.chunks_inserted == 1
    assert rows == [("001", 1)]
    assert journal_count == 1


def test_existing_transaction_writer_rolls_back_all_authority() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        with store.existing_transaction_writer() as writer:
            conn.execute("BEGIN TRANSACTION")
            writer.persist_frame_batches(
                [
                    StagingFrameBatch(
                        frames={"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [1]})},
                        metadata=_source_metadata(),
                    )
                ],
                materialize=True,
            )
            conn.execute("ROLLBACK")
        journal_count = conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0]
        table_count = conn.execute(
            """
            SELECT count(*) FROM information_schema.tables
            WHERE table_schema = 'main'
              AND (table_name = 'stg_sample' OR table_name LIKE '_staging_chunks__%')
            """
        ).fetchone()[0]
    finally:
        conn.close()

    assert journal_count == 0
    assert table_count == 0


@pytest.mark.parametrize("finish", ["COMMIT", "ROLLBACK"])
def test_existing_transaction_writer_holds_lock_through_finish(tmp_path, finish: str) -> None:
    database = tmp_path / "writer-lock.duckdb"
    owner_conn = duckdb.connect(str(database))
    other_conn = duckdb.connect(str(database))
    owner = StagingBatchStore(owner_conn)
    other = StagingBatchStore(other_conn)
    entered = Event()
    finished = Event()
    errors: list[BaseException] = []

    def other_write() -> None:
        entered.set()
        try:
            other.persist_frames(
                {"stg_other": pl.DataFrame({"game_id": ["002"], "value": [2]})},
                metadata=_source_metadata(source_params_digest="other"),
                materialize=True,
            )
        except BaseException as exc:  # pragma: no cover - asserted below
            errors.append(exc)
        finally:
            finished.set()

    thread = Thread(target=other_write)
    try:
        with owner.existing_transaction_writer() as writer:
            owner_conn.execute("BEGIN TRANSACTION")
            writer.persist_frame_batches(
                [
                    StagingFrameBatch(
                        frames={"stg_owner": pl.DataFrame({"game_id": ["001"], "value": [1]})},
                        metadata=_source_metadata(source_params_digest="owner"),
                    )
                ],
                materialize=True,
            )
            thread.start()
            assert entered.wait(timeout=1.0)
            assert not finished.wait(timeout=0.05)
            owner_conn.execute(finish)
        assert finished.wait(timeout=2.0)
        thread.join(timeout=2.0)
    finally:
        if thread.is_alive():
            thread.join(timeout=2.0)
        other_conn.close()
        owner_conn.close()

    assert not errors


def test_materialize_preserves_legacy_staging_rows() -> None:
    conn = duckdb.connect(":memory:")
    try:
        legacy = pl.DataFrame({"game_id": ["001"], "value": [1]})
        conn.register("legacy_stg", legacy)
        conn.execute("CREATE TABLE stg_sample AS SELECT * FROM legacy_stg")
        conn.unregister("legacy_stg")

        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001", "002"], "value": [1, 2]})},
            metadata=_metadata(),
            materialize=True,
        )

        rows = conn.execute("SELECT game_id, value FROM stg_sample ORDER BY game_id").fetchall()
    finally:
        conn.close()

    assert rows == [("001", 1), ("002", 2)]


def test_duplicate_rows_inside_chunk_are_preserved() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"game_id": ["001", "001"], "value": [1, 1]})},
            metadata=_metadata(),
            materialize=True,
        )

        rows = conn.execute("SELECT game_id, value FROM stg_sample ORDER BY game_id").fetchall()
    finally:
        conn.close()

    assert rows == [("001", 1), ("001", 1)]


def test_appends_chunks_by_column_name_not_position() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"a": [1], "b": [10]})},
            metadata=_metadata(chunk_index=0),
            materialize=True,
        )
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"b": [20], "a": [2]})},
            metadata=_metadata(chunk_index=1),
            materialize=True,
        )

        rows = conn.execute("SELECT a, b FROM stg_sample ORDER BY a").fetchall()
    finally:
        conn.close()

    assert rows == [(1, 10), (2, 20)]


def test_persisted_attestation_uses_the_post_cast_stored_chunk() -> None:
    conn = duckdb.connect(":memory:")
    input_frame = pl.DataFrame({"value": pl.Series([2], dtype=pl.Int32)})
    expected_stored = pl.DataFrame({"value": pl.Series([2], dtype=pl.Int64)})
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"value": pl.Series([1], dtype=pl.Int64)})},
            metadata=_metadata(chunk_index=0),
        )
        store.persist_frames(
            {"stg_sample": input_frame},
            metadata=_metadata(chunk_index=1),
        )
        row = conn.execute(
            """
            SELECT content_hash, persisted_row_count,
                   persisted_content_sha256, persisted_schema_sha256
            FROM _staging_chunk_journal
            WHERE source_label = 'init:season:init.season.test:1'
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        frame_content_hash(input_frame),
        1,
        frame_content_hash(expected_stored),
        frame_schema_hash(expected_stored),
    )
    assert row[0] != row[2]


def test_appends_chunks_with_union_schema_by_name() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"a": [1], "b": [10]})},
            metadata=_metadata(chunk_index=0),
            materialize=True,
        )
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"a": [2], "c": [30]})},
            metadata=_metadata(chunk_index=1),
            materialize=True,
        )

        rows = conn.execute("SELECT a, b, c FROM stg_sample ORDER BY a").fetchall()
    finally:
        conn.close()

    assert rows == [(1, 10, None), (2, None, 30)]


def test_empty_expected_chunk_is_journaled_without_table_append() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store = StagingBatchStore(conn)
        result = store.persist_frames(
            {},
            metadata=_metadata(),
            expected_staging_keys=["stg_empty"],
            materialize=True,
        )
        journal_rows = conn.execute(
            """
            SELECT staging_key, row_count
            FROM _staging_chunk_journal
            WHERE staging_key = 'stg_empty'
            """
        ).fetchall()
        table_exists = conn.execute(
            """
            SELECT 1
            FROM information_schema.tables
            WHERE table_schema = 'main' AND table_name = 'stg_empty'
            """
        ).fetchone()
    finally:
        conn.close()

    assert result.chunks_inserted == 1
    assert journal_rows == [("stg_empty", 0)]
    assert table_exists is None


def test_materialize_without_keys_ignores_prefix_wildcard_false_positives() -> None:
    conn = duckdb.connect(":memory:")
    try:
        conn.execute('CREATE TABLE "xstagingXchunksYYbad-key" (a INTEGER)')
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"a": [1]})},
            metadata=_metadata(),
            materialize=False,
        )

        count = store.materialize()
        rows = conn.execute("SELECT a FROM stg_sample").fetchall()
    finally:
        conn.close()

    assert count == 1
    assert rows == [(1,)]


def test_receipt_bound_typed_empty_persists_ordered_empty_attestation() -> None:
    conn = duckdb.connect(":memory:")
    frame = pl.DataFrame(schema={"game_id": pl.String, "value": pl.Int64})
    route = "ep1:stg_empty:0"
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_empty": frame},
            metadata=_source_metadata(),
            expected_staging_keys=["stg_empty"],
            receipt_binding=binding,
            result_route_ids_by_staging_key=(("stg_empty", route),),
        )
        row = conn.execute(
            """
            SELECT row_count, persisted_row_count, persisted_content_sha256,
                   persisted_schema_sha256, logical_call_receipt_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            """
        ).fetchone()
    finally:
        conn.close()

    assert row == (
        0,
        0,
        frame_content_hash(frame),
        frame_schema_hash(frame),
        binding.logical_call_receipt_sha256,
        route,
    )


def test_receipt_bound_multi_route_includes_optional_empty_route() -> None:
    conn = duckdb.connect(":memory:")
    routes = (
        "schedule:stg_schedule:0",
        "schedule:stg_schedule_weeks:1",
    )
    binding = _receipt_binding(*routes)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_schedule": pl.DataFrame({"game_id": ["001"]})},
            metadata=_source_metadata(source_endpoint_name="schedule"),
            expected_staging_keys=["stg_schedule", "stg_schedule_weeks"],
            receipt_binding=binding,
            result_route_ids_by_staging_key=(
                ("stg_schedule", routes[0]),
                ("stg_schedule_weeks", routes[1]),
            ),
        )
        rows = conn.execute(
            """
            SELECT staging_key, persisted_row_count, logical_call_receipt_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            ORDER BY staging_key
            """
        ).fetchall()
    finally:
        conn.close()

    assert rows == [
        ("stg_schedule", 1, binding.logical_call_receipt_sha256, routes[0]),
        ("stg_schedule_weeks", 0, binding.logical_call_receipt_sha256, routes[1]),
    ]


def test_receipt_bound_replay_rejects_a_different_logical_root() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    frame = pl.DataFrame({"game_id": ["001"]})
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
            receipt_binding=_receipt_binding(route, receipt="a" * 64),
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="does not match the logical call",
        ):
            store.persist_frames(
                {"stg_sample": frame},
                metadata=_source_metadata(),
                receipt_binding=_receipt_binding(route, receipt="d" * 64),
                result_route_ids_by_staging_key=(("stg_sample", route),),
            )
    finally:
        conn.close()


def test_replaceable_refresh_rebinds_byte_identical_rows_to_fresh_logical_root() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    frame = pl.DataFrame({"game_id": ["001"]})
    prior_binding = _receipt_binding(route, receipt="a" * 64)
    fresh_binding = _receipt_binding(route, receipt="d" * 64)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
            materialize=True,
            replace_existing_chunk=True,
            receipt_binding=prior_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        result = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
            materialize=True,
            replace_existing_chunk=True,
            receipt_binding=fresh_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        rows = conn.execute("SELECT game_id FROM stg_sample").fetchall()
        receipts = conn.execute(
            """
            SELECT logical_call_receipt_sha256
            FROM _staging_chunk_journal
            WHERE staging_key = 'stg_sample'
            """
        ).fetchall()
    finally:
        conn.close()

    assert result.chunks_inserted == 1
    assert result.chunks_replayed == 0
    assert rows == [("001",)]
    assert receipts == [(fresh_binding.logical_call_receipt_sha256,)]


def test_successor_replacement_persists_exact_prior_and_fresh_receipt() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    prior = pl.DataFrame({"game_id": ["001"], "value": [1]})
    refreshed = pl.DataFrame({"game_id": ["001"], "value": [2]})
    prior_binding = _receipt_binding(route, receipt="a" * 64)
    fresh_binding = _receipt_binding(route, receipt="d" * 64)
    generation = "e" * 64
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": prior},
            metadata=_source_metadata(),
            materialize=True,
            receipt_binding=prior_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        result = store.persist_frames(
            {"stg_sample": refreshed},
            metadata=_source_metadata(),
            materialize=True,
            replace_existing_chunk=True,
            receipt_binding=fresh_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
            successor_generation_sha256=generation,
        )
        replay = store.persist_frames(
            {"stg_sample": refreshed},
            metadata=_source_metadata(),
            materialize=True,
            replace_existing_chunk=True,
            receipt_binding=fresh_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
            successor_generation_sha256=generation,
        )
        stored = conn.execute(
            """
            SELECT prior_persisted_content_sha256, persisted_content_sha256,
                   persisted_schema_sha256, persisted_row_count,
                   logical_call_receipt_sha256, replacement_sha256
            FROM _successor_staging_replacement_journal
            """
        ).fetchone()
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
    finally:
        conn.close()

    assert len(result.replacement_attestations) == 1
    attestation = result.replacement_attestations[0]
    assert isinstance(attestation, SourceScopeReplacementAttestation)
    assert attestation.source_scope_sha256 == fresh_binding.logical_parameters_sha256
    assert attestation.prior_persisted_content_sha256 == frame_content_hash(prior)
    assert attestation.persisted_content_sha256 == frame_content_hash(refreshed)
    assert attestation.logical_call_receipt_sha256 == fresh_binding.logical_call_receipt_sha256
    assert stored == (
        frame_content_hash(prior),
        frame_content_hash(refreshed),
        frame_schema_hash(refreshed),
        1,
        fresh_binding.logical_call_receipt_sha256,
        attestation.replacement_sha256,
    )
    assert replay.chunks_replayed == 1
    assert replay.replacement_attestations == (attestation,)
    assert rows == [("001", 2)]


def test_successor_typed_zero_replaces_and_attests_deleted_scope() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    prior = pl.DataFrame({"game_id": ["001"], "value": [1]})
    typed_zero = pl.DataFrame(schema=prior.schema)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": prior},
            metadata=_source_metadata(),
            materialize=True,
            receipt_binding=_receipt_binding(route, receipt="a" * 64),
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        result = store.persist_frames(
            {"stg_sample": typed_zero},
            metadata=_source_metadata(),
            materialize=True,
            replace_existing_chunk=True,
            receipt_binding=_receipt_binding(route, receipt="d" * 64),
            result_route_ids_by_staging_key=(("stg_sample", route),),
            successor_generation_sha256="e" * 64,
        )
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
    finally:
        conn.close()

    attestation = result.replacement_attestations[0]
    assert attestation.prior_persisted_content_sha256 == frame_content_hash(prior)
    assert attestation.persisted_row_count == 0
    assert attestation.persisted_content_sha256 == frame_content_hash(typed_zero)
    assert rows == []


def test_successor_replacement_rejects_receiptless_prior_without_mutation() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    prior = pl.DataFrame({"game_id": ["001"], "value": [1]})
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": prior},
            metadata=_source_metadata(),
            materialize=True,
        )
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="receipt-bound prior source scope",
        ):
            store.persist_frames(
                {"stg_sample": pl.DataFrame({"game_id": ["001"], "value": [2]})},
                metadata=_source_metadata(),
                materialize=True,
                replace_existing_chunk=True,
                receipt_binding=_receipt_binding(route, receipt="d" * 64),
                result_route_ids_by_staging_key=(("stg_sample", route),),
                successor_generation_sha256="e" * 64,
            )
        rows = conn.execute("SELECT game_id, value FROM stg_sample").fetchall()
        replacement_count = conn.execute(
            "SELECT count(*) FROM _successor_staging_replacement_journal"
        ).fetchone()[0]
    finally:
        conn.close()

    assert rows == [("001", 1)]
    assert replacement_count == 0


def test_receipt_bound_replay_upgrades_an_exact_v2_unbound_chunk() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    frame = pl.DataFrame({"game_id": ["001"]})
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
        )
        result = store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
            receipt_binding=binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        row = conn.execute(
            """
            SELECT persisted_row_count, persisted_content_sha256,
                   persisted_schema_sha256, logical_call_receipt_sha256,
                   provider_authority_sha256, logical_parameters_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            """
        ).fetchone()
    finally:
        conn.close()

    assert result.chunks_replayed == 1
    assert row == (
        1,
        frame_content_hash(frame),
        frame_schema_hash(frame),
        binding.logical_call_receipt_sha256,
        binding.provider_authority_sha256,
        binding.logical_parameters_sha256,
        route,
    )


@pytest.mark.parametrize(
    ("column", "hostile_value"),
    [
        ("canonical_frame_format", None),
        ("frame_content_hash_contract", "nbadb_arrow_logical_table_sha256_v1"),
        ("frame_schema_hash_contract", "nbadb_arrow_schema_sha256_v1"),
    ],
    ids=["null-format", "v1-content", "v1-schema"],
)
def test_receipt_bound_replay_never_upgrades_stale_contract_evidence(
    column: str,
    hostile_value: str | None,
) -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    frame = pl.DataFrame({"game_id": ["001"]})
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(),
        )
        if hostile_value is None:
            conn.execute(f"ALTER TABLE _staging_chunk_journal ALTER COLUMN {column} DROP NOT NULL")
        conn.execute(
            f"UPDATE _staging_chunk_journal SET {column} = $1",
            [hostile_value],
        )
        with pytest.raises(ParserInputCaptureIntegrityError, match="restart required"):
            store.persist_frames(
                {"stg_sample": frame},
                metadata=_source_metadata(),
                receipt_binding=binding,
                result_route_ids_by_staging_key=(("stg_sample", route),),
            )
        stored_binding = conn.execute(
            "SELECT logical_call_receipt_sha256 FROM _staging_chunk_journal"
        ).fetchone()[0]
    finally:
        conn.close()

    assert stored_binding is None


def test_receipt_validation_failure_rolls_back_prior_batch_write() -> None:
    conn = duckdb.connect(":memory:")
    good_route = "ep1:stg_one:0"
    bad_route = "ep2:wrong_key:0"
    try:
        store = StagingBatchStore(conn)
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="does not match its source route",
        ):
            store.persist_frame_batches(
                [
                    StagingFrameBatch(
                        frames={"stg_one": pl.DataFrame({"value": [1]})},
                        metadata=_source_metadata(source_endpoint_name="ep1"),
                        receipt_binding=_receipt_binding(good_route, receipt="a" * 64),
                        result_route_ids_by_staging_key=(("stg_one", good_route),),
                    ),
                    StagingFrameBatch(
                        frames={"stg_two": pl.DataFrame({"value": [2]})},
                        metadata=_source_metadata(
                            chunk_index=1,
                            source_endpoint_name="ep2",
                            source_params_digest="source-two",
                        ),
                        receipt_binding=_receipt_binding(bad_route, receipt="d" * 64),
                        result_route_ids_by_staging_key=(("stg_two", bad_route),),
                    ),
                ]
            )
        journal_count = conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0]
        internal_count = conn.execute(
            """
            SELECT count(*)
            FROM information_schema.tables
            WHERE table_schema = 'main'
              AND table_name LIKE '_staging_chunks__%'
            """
        ).fetchone()[0]
    finally:
        conn.close()

    assert journal_count == 0
    assert internal_count == 0


def test_lossless_fallback_persists_response_and_logical_receipts_atomically() -> None:
    conn = duckdb.connect(":memory:")
    route = f"ep1:{LOSSLESS_FALLBACK_STAGING_KEY}:1"
    binding = _receipt_binding(route)
    frame = _lossless_fallback_frame()
    try:
        store = StagingBatchStore(conn)
        first = store.persist_lossless_fallback(
            frame,
            metadata=_source_metadata(),
            receipt_binding=binding,
            result_route_id=route,
            materialize=True,
        )
        replay = store.persist_lossless_fallback(
            frame,
            metadata=_source_metadata(),
            receipt_binding=binding,
            result_route_id=route,
            materialize=True,
        )
        journal = conn.execute(
            """
            SELECT staging_key, persisted_row_count, logical_call_receipt_sha256,
                   provider_authority_sha256, logical_parameters_sha256,
                   result_route_id
            FROM _staging_chunk_journal
            WHERE staging_key = $1
            """,
            [LOSSLESS_FALLBACK_STAGING_KEY],
        ).fetchone()
        persisted = conn.execute(
            f"SELECT * FROM {LOSSLESS_FALLBACK_STAGING_KEY} ORDER BY record_kind"
        ).pl()
    finally:
        conn.close()

    assert first.chunks_inserted == 1
    assert first.rows_persisted == frame.height
    assert replay.chunks_replayed == 1
    assert journal == (
        LOSSLESS_FALLBACK_STAGING_KEY,
        frame.height,
        binding.logical_call_receipt_sha256,
        binding.provider_authority_sha256,
        binding.logical_parameters_sha256,
        route,
    )
    assert persisted.height == frame.height
    assert set(persisted["response_receipt_sha256"].to_list()) == {"d" * 64}
    assert persisted.filter(pl.col("record_kind") == "cell")["canonical_json"].item() == "1"


def test_lossless_fallback_persists_atomically_with_pinned_wide_route() -> None:
    conn = duckdb.connect(":memory:")
    wide_route = "ep1:stg_one:0"
    fallback_route = f"ep1:{LOSSLESS_FALLBACK_STAGING_KEY}:1"
    binding = _receipt_binding(wide_route, fallback_route)
    fallback = _lossless_fallback_frame()
    wide = pl.DataFrame({"id": [1], "value": ["one"]})
    try:
        store = StagingBatchStore(conn)
        result = store.persist_frames(
            {
                "stg_one": wide,
                LOSSLESS_FALLBACK_STAGING_KEY: fallback,
            },
            metadata=_source_metadata(),
            expected_staging_keys=("stg_one", LOSSLESS_FALLBACK_STAGING_KEY),
            materialize=True,
            receipt_binding=binding,
            result_route_ids_by_staging_key=(
                ("stg_one", wide_route),
                (LOSSLESS_FALLBACK_STAGING_KEY, fallback_route),
            ),
        )
        journal = conn.execute(
            """
            SELECT staging_key, logical_call_receipt_sha256, result_route_id
            FROM _staging_chunk_journal
            ORDER BY staging_key
            """
        ).fetchall()
    finally:
        conn.close()

    assert result.chunks_inserted == 2
    assert result.rows_persisted == wide.height + fallback.height
    assert journal == [
        (
            LOSSLESS_FALLBACK_STAGING_KEY,
            binding.logical_call_receipt_sha256,
            fallback_route,
        ),
        ("stg_one", binding.logical_call_receipt_sha256, wide_route),
    ]


def test_lossless_fallback_rejects_unbound_frame_without_journal_mutation() -> None:
    conn = duckdb.connect(":memory:")
    route = f"ep1:{LOSSLESS_FALLBACK_STAGING_KEY}:1"
    try:
        store = StagingBatchStore(conn)
        unbound = _lossless_fallback_frame().with_columns(
            pl.lit(None, dtype=pl.String).alias("response_receipt_sha256")
        )
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires one response receipt",
        ):
            store.persist_lossless_fallback(
                unbound,
                metadata=_source_metadata(),
                receipt_binding=_receipt_binding(route),
                result_route_id=route,
            )
        journal_count = conn.execute("SELECT count(*) FROM _staging_chunk_journal").fetchone()[0]
    finally:
        conn.close()

    assert journal_count == 0


def test_committed_frame_readback_and_row_partition_preserve_exact_multiplicity() -> None:
    conn = duckdb.connect(":memory:")
    frame = pl.DataFrame(
        {
            "game_id": ["001", "001", "002"],
            "value": [1, 1, 2],
        }
    )
    try:
        _, _, receipt, readback = _committed_readback(conn, frame)
        decoded = pl.read_ipc_stream(readback.canonical_frame_bytes)
        slices = (
            CommittedStagingRowSliceV2.build(
                readback=readback,
                slice_order_ordinal=0,
                start_row_ordinal=0,
                row_count=2,
            ),
            CommittedStagingRowSliceV2.build(
                readback=readback,
                slice_order_ordinal=1,
                start_row_ordinal=2,
                row_count=0,
            ),
            CommittedStagingRowSliceV2.build(
                readback=readback,
                slice_order_ordinal=2,
                start_row_ordinal=2,
                row_count=1,
            ),
        )
        partition = validate_committed_row_partition(readback, slices)
        repeated = validate_committed_row_partition(readback, slices)
    finally:
        conn.close()

    assert type(readback.canonical_frame_bytes) is bytes
    assert decoded.to_dicts() == frame.to_dicts()
    assert decoded.to_dicts()[:2] == [
        {"game_id": "001", "value": 1},
        {"game_id": "001", "value": 1},
    ]
    assert readback.recomputed_frame_schema_sha256 == frame_schema_hash(frame)
    assert readback.recomputed_frame_content_hash == frame_content_hash(frame)
    assert readback.recomputed_persisted_content_sha256 == receipt.persisted_content_sha256
    assert readback.row_count == 3
    assert slices[1].row_count == 0
    assert slices[1].start_row_ordinal == 2
    assert partition.row_count == 3
    assert partition.slice_count == 3
    assert partition.partition_receipt_sha256 == repeated.partition_receipt_sha256


def test_committed_frame_readback_rejects_active_caller_owned_transaction() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store, _, receipt, _ = _committed_readback(
            conn,
            pl.DataFrame({"game_id": ["001"]}),
        )
        with store.existing_transaction_writer():
            conn.execute("BEGIN TRANSACTION")
            with pytest.raises(
                ParserInputCaptureIntegrityError,
                match="unavailable inside an active transaction",
            ):
                store.committed_staging_frame_readback(receipt)
            conn.execute("ROLLBACK")
    finally:
        conn.close()


def test_committed_frame_readback_rejects_stale_receipt_after_replacement() -> None:
    conn = duckdb.connect(":memory:")
    frame = pl.DataFrame({"game_id": ["001"]})
    route = "ep1:stg_sample:0"
    try:
        store, _, stale_receipt, _ = _committed_readback(conn, frame)
        fresh_binding = _receipt_binding(route, receipt="d" * 64)
        store.persist_frames(
            {"stg_sample": frame},
            metadata=_source_metadata(source_params_digest="readback-source"),
            replace_existing_chunk=True,
            receipt_binding=fresh_binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from its exact journal row",
        ):
            store.committed_staging_frame_readback(stale_receipt)
    finally:
        conn.close()


def test_committed_frame_readback_rejects_wrong_table_and_mutated_receipt() -> None:
    conn = duckdb.connect(":memory:")
    try:
        store, _, receipt, _ = _committed_readback(
            conn,
            pl.DataFrame({"game_id": ["001"]}),
        )
        wrong_table = replace(
            receipt,
            staging_key="stg_other",
            result_route_id="ep1:stg_other:0",
        )
        mutated = replace(receipt, content_hash="f" * 64)
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="stale or names the wrong table",
        ):
            store.committed_staging_frame_readback(wrong_table)
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from its exact journal row",
        ):
            store.committed_staging_frame_readback(mutated)
    finally:
        conn.close()


def test_committed_frame_readback_preserves_canonical_zero_column_empty_frame() -> None:
    conn = duckdb.connect(":memory:")
    empty = pl.DataFrame()
    route = "ep1:stg_zero:0"
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_zero": empty},
            metadata=_source_metadata(),
            receipt_binding=binding,
            result_route_ids_by_staging_key=(("stg_zero", route),),
        )
        receipt = store.committed_logical_call_receipts(binding)[0]
        readback = store.committed_staging_frame_readback(receipt)
    finally:
        conn.close()

    assert readback.row_count == 0
    assert readback.recomputed_frame_schema_sha256 == frame_schema_hash(empty)
    assert readback.recomputed_frame_content_hash == frame_content_hash(empty)


def test_committed_frame_readback_preserves_typed_empty_frame() -> None:
    conn = duckdb.connect(":memory:")
    typed_empty = pl.DataFrame(schema={"game_id": pl.String, "value": pl.Int64})
    route = "ep1:stg_empty:0"
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_empty": typed_empty},
            metadata=_source_metadata(),
            receipt_binding=binding,
            result_route_ids_by_staging_key=(("stg_empty", route),),
        )
        receipt = store.committed_logical_call_receipts(binding)[0]
        readback = store.committed_staging_frame_readback(receipt)
        row_slice = CommittedStagingRowSliceV2.build(
            readback=readback,
            slice_order_ordinal=0,
            start_row_ordinal=0,
            row_count=0,
        )
        partition = validate_committed_row_partition(readback, (row_slice,))
    finally:
        conn.close()

    assert readback.row_count == 0
    assert readback.recomputed_frame_schema_sha256 == frame_schema_hash(typed_empty)
    assert readback.recomputed_frame_content_hash == frame_content_hash(typed_empty)
    assert partition.row_count == 0
    assert partition.slice_count == 1


def test_committed_frame_readback_rejects_unreconstructible_precast_content() -> None:
    conn = duckdb.connect(":memory:")
    route = "ep1:stg_sample:0"
    binding = _receipt_binding(route)
    try:
        store = StagingBatchStore(conn)
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"value": pl.Series([1], dtype=pl.Int64)})},
            metadata=_metadata(chunk_index=0),
        )
        store.persist_frames(
            {"stg_sample": pl.DataFrame({"value": pl.Series([2], dtype=pl.Int32)})},
            metadata=_source_metadata(chunk_index=1),
            receipt_binding=binding,
            result_route_ids_by_staging_key=(("stg_sample", route),),
        )
        receipt = store.committed_logical_call_receipts(binding)[0]
        assert receipt.content_hash != receipt.persisted_content_sha256
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="differs from its canonical frame or receipt",
        ):
            store.committed_staging_frame_readback(receipt)
    finally:
        conn.close()


def test_committed_readback_contracts_reject_bool_integer_aliases() -> None:
    conn = duckdb.connect(":memory:")
    try:
        _, _, receipt, readback = _committed_readback(
            conn,
            pl.DataFrame({"game_id": ["001"]}),
        )
        row_slice = CommittedStagingRowSliceV2.build(
            readback=readback,
            slice_order_ordinal=0,
            start_row_ordinal=0,
            row_count=1,
        )
        with pytest.raises(ParserInputCaptureIntegrityError, match="nonnegative integer"):
            replace(receipt, persisted_row_count=True)
        with pytest.raises(ParserInputCaptureIntegrityError, match="nonnegative integer"):
            replace(readback, row_count=True)
        with pytest.raises(ParserInputCaptureIntegrityError, match="integer two"):
            replace(row_slice, schema_version=True)
        with pytest.raises(ParserInputCaptureIntegrityError, match="nonnegative integer"):
            CommittedStagingRowSliceV2.build(
                readback=readback,
                slice_order_ordinal=0,
                start_row_ordinal=0,
                row_count=True,  # type: ignore[arg-type]
            )
    finally:
        conn.close()


def test_row_partition_rejects_reordered_gapped_overlapping_and_missing_slices() -> None:
    conn = duckdb.connect(":memory:")
    try:
        _, _, _, readback = _committed_readback(
            conn,
            pl.DataFrame({"value": [1, 2, 3]}),
        )

        def row_slice(
            ordinal: int,
            start: int,
            count: int,
        ) -> CommittedStagingRowSliceV2:
            return CommittedStagingRowSliceV2.build(
                readback=readback,
                slice_order_ordinal=ordinal,
                start_row_ordinal=start,
                row_count=count,
            )

        exact = (row_slice(0, 0, 1), row_slice(1, 1, 1), row_slice(2, 2, 1))
        reordered = (exact[1], exact[0], exact[2])
        gapped = (row_slice(0, 1, 1), row_slice(1, 2, 1))
        overlapping = (row_slice(0, 0, 2), row_slice(1, 1, 1))
        missing = (exact[0], exact[2])

        with pytest.raises(ParserInputCaptureIntegrityError, match="reordered or incomplete"):
            validate_committed_row_partition(readback, reordered)
        with pytest.raises(ParserInputCaptureIntegrityError, match="overlap or leave a row gap"):
            validate_committed_row_partition(readback, gapped)
        with pytest.raises(ParserInputCaptureIntegrityError, match="overlap or leave a row gap"):
            validate_committed_row_partition(readback, overlapping)
        with pytest.raises(ParserInputCaptureIntegrityError, match="reordered or incomplete"):
            validate_committed_row_partition(readback, missing)
    finally:
        conn.close()


def test_row_partition_rejects_foreign_slice_and_mutated_slice_receipt() -> None:
    conn = duckdb.connect(":memory:")
    try:
        _, _, _, readback = _committed_readback(
            conn,
            pl.DataFrame({"value": [1, 2]}),
        )
        _, _, _, foreign_readback = _committed_readback(
            conn,
            pl.DataFrame({"value": [9]}),
            staging_key="stg_other",
            source_params_digest="foreign-source",
            logical_receipt_sha256="d" * 64,
        )
        first = CommittedStagingRowSliceV2.build(
            readback=readback,
            slice_order_ordinal=0,
            start_row_ordinal=0,
            row_count=1,
        )
        second = CommittedStagingRowSliceV2.build(
            readback=readback,
            slice_order_ordinal=1,
            start_row_ordinal=1,
            row_count=1,
        )
        foreign = CommittedStagingRowSliceV2.build(
            readback=foreign_readback,
            slice_order_ordinal=1,
            start_row_ordinal=0,
            row_count=1,
        )
        with pytest.raises(ParserInputCaptureIntegrityError, match="foreign"):
            validate_committed_row_partition(readback, (first, foreign))
        with pytest.raises(ParserInputCaptureIntegrityError, match="digest"):
            replace(second, slice_content_sha256="f" * 64)
    finally:
        conn.close()


def _canonical_v2_frames() -> list[tuple[str, pl.DataFrame]]:
    return [
        (
            "decimal-widths",
            pl.DataFrame(
                {
                    "decimal_10_2": pl.Series(
                        [Decimal("0.00"), Decimal("-99999999.99")],
                        dtype=pl.Decimal(10, 2),
                    ),
                    "decimal_20_4": pl.Series(
                        [Decimal("1.2300"), Decimal("-9999999999999999.9999")],
                        dtype=pl.Decimal(20, 4),
                    ),
                    "decimal_38_2": pl.Series(
                        [
                            Decimal("999999999999999999999999999999999999.99"),
                            Decimal("-0.01"),
                        ],
                        dtype=pl.Decimal(38, 2),
                    ),
                }
            ),
        ),
        (
            "nested-decimal",
            pl.DataFrame(
                {
                    "payload": pl.Series(
                        [
                            {
                                "amount": Decimal("1.2300"),
                                "values": [Decimal("2.00"), Decimal("-3.50")],
                            },
                            {"amount": Decimal("-4.0000"), "values": []},
                        ],
                        dtype=pl.Struct(
                            {
                                "amount": pl.Decimal(20, 4),
                                "values": pl.List(pl.Decimal(10, 2)),
                            }
                        ),
                    )
                }
            ),
        ),
        (
            "binary-date-datetime",
            pl.DataFrame(
                {
                    "raw": pl.Series([b"", b"\x00\xff"], dtype=pl.Binary),
                    "day": pl.Series(
                        [date(1946, 11, 1), date(2026, 8, 27)],
                        dtype=pl.Date,
                    ),
                    "naive_at": pl.Series(
                        [
                            datetime(1946, 11, 1),
                            datetime(2026, 8, 27, 12, 34, 56, 789012),
                        ],
                        dtype=pl.Datetime("us"),
                    ),
                    "utc_at": pl.Series(
                        [
                            datetime(1946, 11, 1, tzinfo=UTC),
                            datetime(2026, 8, 27, 12, 34, 56, 789012, tzinfo=UTC),
                        ],
                        dtype=pl.Datetime("us", "UTC"),
                    ),
                }
            ),
        ),
        (
            "categorical-nonfinite",
            pl.DataFrame(
                {
                    "conference": pl.Series(
                        ["east", "west", "east", None, "west"],
                        dtype=pl.Categorical,
                    ),
                    "value": pl.Series(
                        [0.0, -0.0, float("nan"), float("inf"), float("-inf")],
                        dtype=pl.Float64,
                    ),
                }
            ),
        ),
        (
            "typed-empty",
            pl.DataFrame(
                schema={
                    "amount": pl.Decimal(20, 4),
                    "raw": pl.Binary,
                    "day": pl.Date,
                    "utc_at": pl.Datetime("us", "UTC"),
                    "conference": pl.Categorical,
                }
            ),
        ),
    ]


@pytest.mark.parametrize(
    ("_case", "frame"),
    _canonical_v2_frames(),
    ids=[name for name, _frame in _canonical_v2_frames()],
)
def test_canonical_arrow_v2_matrix_is_fixed_point_and_slice_bound(
    _case: str,
    frame: pl.DataFrame,
) -> None:
    canonical_bytes = staging_batches_module._canonical_frame_bytes(frame)
    decoded = staging_batches_module._decode_canonical_frame_bytes(canonical_bytes)
    receipt, readback = _direct_v2_readback(frame)
    row_slice = CommittedStagingRowSliceV2.build(
        readback=readback,
        slice_order_ordinal=0,
        start_row_ordinal=0,
        row_count=frame.height,
    )
    partition = validate_committed_row_partition(readback, (row_slice,))

    assert staging_batches_module._canonical_frame_bytes(decoded) == canonical_bytes
    assert decoded.schema == frame.schema
    assert frame_content_hash(decoded) == frame_content_hash(frame)
    assert frame_schema_hash(decoded) == frame_schema_hash(frame)
    assert frame_content_hash(frame) != hashlib.sha256(canonical_bytes).hexdigest()
    assert readback.canonical_frame_bytes == canonical_bytes
    assert row_slice.slice_schema_sha256 == frame_schema_hash(frame)
    assert row_slice.slice_content_sha256 == frame_content_hash(frame)
    assert partition.partition_receipt_sha256
    for identity in (
        receipt.identity_payload(),
        readback.identity_payload(),
        row_slice.identity_payload(),
        partition.identity_payload(),
    ):
        assert identity["canonical_frame_format"] == CANONICAL_FRAME_FORMAT
        assert identity["frame_content_hash_contract"] == FRAME_CONTENT_HASH_CONTRACT
        assert identity["frame_schema_hash_contract"] == FRAME_SCHEMA_HASH_CONTRACT


def test_canonical_arrow_v2_normalizes_metadata_chunks_offsets_and_dictionaries() -> None:
    dictionary_type = pa.dictionary(pa.int32(), pa.string())
    first_dictionary = pa.DictionaryArray.from_arrays(
        pa.array([0, 1], type=pa.int32()),
        pa.array(["east", "west"]),
    )
    second_dictionary = pa.DictionaryArray.from_arrays(
        pa.array([1], type=pa.int32()),
        pa.array(["west", "east"]),
    )
    sliced_lists = pa.array(
        [[0], [1, 2], [3], [], [4, 5]],
        type=pa.list_(pa.int64()),
    ).slice(1, 3)
    schema_with_metadata = pa.schema(
        [
            pa.field("conference", dictionary_type, metadata={b"field": b"ignored"}),
            pa.field("values", pa.list_(pa.int64()), metadata={b"nested": b"ignored"}),
        ],
        metadata={b"schema": b"ignored"},
    )
    hostile = pa.Table.from_arrays(
        [
            pa.chunked_array([first_dictionary, second_dictionary], type=dictionary_type),
            pa.chunked_array([sliced_lists.slice(0, 1), sliced_lists.slice(1, 2)]),
        ],
        schema=schema_with_metadata,
    )
    clean_dictionary = pa_compute.dictionary_encode(pa.array(["east", "west", "east"]))
    clean = pa.Table.from_arrays(
        [clean_dictionary, pa.array([[1, 2], [3], []], type=pa.list_(pa.int64()))],
        names=["conference", "values"],
    )

    normalized = staging_batches_module._normalize_arrow_table(hostile)
    canonical = staging_batches_module._encode_normalized_arrow_table(normalized)
    normalized_clean = staging_batches_module._normalize_arrow_table(clean)

    assert normalized.schema.metadata is None
    assert all(field.metadata is None for field in normalized.schema)
    assert all(column.num_chunks == 1 for column in normalized.columns)
    assert all(column.chunk(0).offset == 0 for column in normalized.columns)
    assert staging_batches_module._encode_normalized_arrow_table(normalized_clean) == canonical
    assert (
        staging_batches_module._encode_normalized_arrow_table(
            staging_batches_module._normalize_arrow_table(
                staging_batches_module._read_single_arrow_batch(canonical)
            )
        )
        == canonical
    )


def test_canonical_arrow_v2_ignores_duckdb_null_payload_bytes() -> None:
    frame = pl.DataFrame(
        {
            "w": pl.Series([None, 3, None], dtype=pl.Int64),
            "w_pct": pl.Series([None, 0.375, None], dtype=pl.Float64),
            "game_id": ["0022500001", "0022500002", "0022500003"],
        }
    )
    conn = duckdb.connect(":memory:")
    try:
        conn.register("nullable_source", frame.to_arrow())
        conn.execute("CREATE TABLE nullable_roundtrip AS SELECT * FROM nullable_source")
        roundtrip = conn.execute("SELECT * FROM nullable_roundtrip ORDER BY game_id").pl()
    finally:
        conn.close()

    assert roundtrip.schema == frame.schema
    assert roundtrip.rows() == frame.rows()
    assert staging_batches_module._canonical_frame_bytes(roundtrip) == (
        staging_batches_module._canonical_frame_bytes(frame)
    )
    assert frame_content_hash(roundtrip) == frame_content_hash(frame)
    assert frame_schema_hash(roundtrip) == frame_schema_hash(frame)


def test_canonical_arrow_v2_ignores_hidden_nested_null_payloads() -> None:
    mask = pa.array([True, False, True], type=pa.bool_())
    struct_type = pa.struct([pa.field("value", pa.int64())])
    list_type = pa.list_(pa.int64())

    def table(*, hidden: tuple[int, int]) -> pa.Table:
        struct_values = pa.array([hidden[0], 7, hidden[1]], type=pa.int64())
        struct_array = pa.StructArray.from_arrays(
            [struct_values],
            fields=list(struct_type),
            mask=mask,
        )
        list_values = pa.array([hidden[0], 7, 8, hidden[1]], type=pa.int64())
        list_array = pa.ListArray.from_arrays(
            pa.array([0, 1, 3, 4], type=pa.int32()),
            list_values,
            type=list_type,
            mask=mask,
        )
        return pa.Table.from_arrays(
            [struct_array, list_array],
            names=["struct_value", "list_value"],
        )

    left = table(hidden=(111, 222))
    right = table(hidden=(999, 888))
    assert (
        left.to_pylist()
        == right.to_pylist()
        == [
            {"struct_value": None, "list_value": None},
            {"struct_value": {"value": 7}, "list_value": [7, 8]},
            {"struct_value": None, "list_value": None},
        ]
    )

    left_bytes = staging_batches_module._encode_normalized_arrow_table(
        staging_batches_module._normalize_arrow_table(left)
    )
    right_bytes = staging_batches_module._encode_normalized_arrow_table(
        staging_batches_module._normalize_arrow_table(right)
    )
    assert left_bytes == right_bytes


def test_canonical_arrow_v2_preserves_nonfinite_float_bits() -> None:
    bit_patterns = (
        0x0000000000000000,
        0x8000000000000000,
        0x7FF0000000000000,
        0xFFF0000000000000,
        0x7FF8000000000001,
        0x7FF8000000000002,
    )
    values = [struct.unpack(">d", bits.to_bytes(8, "big"))[0] for bits in bit_patterns]
    frame = pl.DataFrame({"value": pl.Series(values, dtype=pl.Float64)})

    decoded = staging_batches_module._decode_canonical_frame_bytes(
        staging_batches_module._canonical_frame_bytes(frame)
    )
    decoded_bits = tuple(
        int.from_bytes(struct.pack(">d", value), "big")
        for value in decoded.get_column("value").to_list()
    )

    assert decoded_bits == bit_patterns


def test_canonical_arrow_v2_rejects_malformed_legacy_and_multibatch_ipc() -> None:
    frame = pl.DataFrame({"value": [1, 2]})
    canonical = staging_batches_module._canonical_frame_bytes(frame)
    table = frame.to_arrow()
    sink = pa.BufferOutputStream()
    with pa_ipc.new_stream(
        sink,
        table.schema,
        options=pa_ipc.IpcWriteOptions(metadata_version=pa_ipc.MetadataVersion.V4),
    ) as writer:
        writer.write_table(table)
    legacy_v4 = sink.getvalue().to_pybytes()
    sink = pa.BufferOutputStream()
    with pa_ipc.new_stream(sink, table.schema) as writer:
        batch = table.to_batches()[0]
        writer.write_batch(batch)
        writer.write_batch(batch)
    multibatch = sink.getvalue().to_pybytes()

    for hostile in (b"not-arrow", canonical + b"trailing", legacy_v4, multibatch):
        with pytest.raises(ParserInputCaptureIntegrityError):
            staging_batches_module._decode_canonical_frame_bytes(hostile)


@pytest.mark.parametrize(
    "drifted",
    [
        pl.DataFrame({"value": pl.Series([1, 2], dtype=pl.Int32)}),
        pl.DataFrame({"value": [1, 3]}),
        pl.DataFrame({"value": [2, 1]}),
        pl.DataFrame({"value": pl.Series(["1", "2"], dtype=pl.Categorical)}),
    ],
    ids=["schema", "value", "row-order", "category"],
)
def test_committed_readback_rejects_schema_value_row_and_category_drift(
    drifted: pl.DataFrame,
) -> None:
    baseline = pl.DataFrame({"value": [1, 2]})
    receipt, _ = _direct_v2_readback(baseline)

    with pytest.raises(
        ParserInputCaptureIntegrityError,
        match="differs from its canonical frame or receipt",
    ):
        CommittedStagingFrameReadbackV2.build(
            committed_receipt=receipt,
            frame=drifted,
        )


def test_v2_receipts_reject_wrong_contract_ids_and_resealed_v1_hashes() -> None:
    frame = pl.DataFrame({"value": [1]})
    receipt, readback = _direct_v2_readback(frame)
    row_slice = CommittedStagingRowSliceV2.build(
        readback=readback,
        slice_order_ordinal=0,
        start_row_ordinal=0,
        row_count=1,
    )
    raw_v1_style_hash = hashlib.sha256(readback.canonical_frame_bytes).hexdigest()

    with pytest.raises(ParserInputCaptureIntegrityError, match="restart required"):
        replace(
            receipt,
            canonical_frame_format="arrow_ipc_stream_v1_polars",
            frame_content_hash_contract="nbadb_arrow_logical_table_sha256_v1",
            frame_schema_hash_contract="nbadb_arrow_schema_sha256_v1",
            content_hash=raw_v1_style_hash,
            persisted_content_sha256=raw_v1_style_hash,
        )
    with pytest.raises(ParserInputCaptureIntegrityError, match="restart required"):
        replace(readback, frame_content_hash_contract="nbadb_arrow_logical_table_sha256_v1")
    with pytest.raises(ParserInputCaptureIntegrityError, match="restart required"):
        replace(row_slice, frame_schema_hash_contract="nbadb_arrow_schema_sha256_v1")
