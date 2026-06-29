from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.orchestrate.staging_batches import (
    StagingBatchStore,
    StagingChunkMetadata,
    StagingFrameBatch,
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
            content_hash="old-hash",
            source_label=legacy_metadata.source_label,
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
