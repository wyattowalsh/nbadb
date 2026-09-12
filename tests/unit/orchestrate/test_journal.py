from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, cast

import polars as pl
import pytest

from nbadb.core.errors import ParserInputCaptureIntegrityError
from nbadb.extract.bronze import LogicalCallReceiptBinding, canonical_parameters_sha256
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.staging_batches import (
    CANONICAL_FRAME_FORMAT,
    FRAME_CONTENT_HASH_CONTRACT,
    FRAME_SCHEMA_HASH_CONTRACT,
    StagingBatchStore,
    StagingChunkMetadata,
)
from nbadb.orchestrate.w2_operation_coordinator import W2SourceCallAdmissionV1
from nbadb.transform.schema_version import schema_hash_for_columns

if TYPE_CHECKING:
    import duckdb


@pytest.fixture
def journal(duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection) -> PipelineJournal:
    """Create PipelineJournal with canonical in-memory DuckDB (with pipeline tables)."""
    return PipelineJournal(duckdb_memory_with_pipeline_tables)


def _receipt_binding(
    *,
    receipt: str = "a" * 64,
    params: dict[str, object] | None = None,
    endpoint: str = "ep",
    provider: str = "c" * 64,
    routes: tuple[tuple[str, int], ...] = (("stg_ep", 0),),
) -> LogicalCallReceiptBinding:
    return LogicalCallReceiptBinding(
        logical_call_receipt_sha256=receipt,
        endpoint_name=endpoint,
        logical_parameters_sha256=canonical_parameters_sha256(params or {}),
        provider_authority_sha256=provider,
        result_route_ids=tuple(
            sorted(
                f"{endpoint}:{staging_key}:{result_index}" for staging_key, result_index in routes
            )
        ),
    )


def _persist_receipt_binding(
    journal: PipelineJournal,
    binding: LogicalCallReceiptBinding,
    *,
    frames: dict[str, pl.DataFrame] | None = None,
) -> None:
    successor_generation = journal.successor_generation_sha256
    route_mapping: list[tuple[str, str]] = []
    default_frames: dict[str, pl.DataFrame] = {}
    source_endpoints: set[str] = set()
    for value, route_id in enumerate(binding.result_route_ids, start=1):
        endpoint, staging_key, _result_index = route_id.rsplit(":", 2)
        source_endpoints.add(endpoint)
        route_mapping.append((staging_key, route_id))
        default_frames[staging_key] = pl.DataFrame({"value": [value]})
    assert len(source_endpoints) == 1
    StagingBatchStore(journal._conn).persist_frames(
        default_frames if frames is None else frames,
        metadata=StagingChunkMetadata(
            run_mode="init",
            lane_id="lane",
            pattern="season",
            chunk_index=0,
            params_digest="params",
            entries_digest="entries",
            source_endpoint_name=next(iter(source_endpoints)),
            source_params_digest=binding.logical_parameters_sha256,
        ),
        expected_staging_keys=[staging_key for staging_key, _route in route_mapping],
        replace_existing_chunk=successor_generation is not None,
        receipt_binding=binding,
        result_route_ids_by_staging_key=tuple(route_mapping),
        successor_generation_sha256=successor_generation,
    )


def _persist_w2_admission(
    journal: PipelineJournal,
) -> tuple[LogicalCallReceiptBinding, str, W2SourceCallAdmissionV1]:
    from tests.unit.orchestrate.test_w2_operation_coordinator import (
        _candidate,
        _coordinate,
    )

    candidate, public_store, operation_store = _candidate(journal._conn)
    admission = _coordinate(candidate, public_store, operation_store)
    binding = candidate.logical_call_binding
    bundle = cast("Any", candidate.operation_inputs.raw_bundle)
    selected = tuple(item for item in bundle.observations if item.lifecycle == "selected_terminal")
    assert len(selected) == 1
    params = selected[0].attempt.safe_parameters_json
    _persist_receipt_binding(journal, binding)
    return binding, params, admission


class TestJournalWatermarks:
    def test_get_watermark_empty(self, journal: PipelineJournal) -> None:
        assert journal.get_watermark("foo", "season") is None

    def test_set_and_get_watermark(
        self,
        journal: PipelineJournal,
    ) -> None:
        journal.set_watermark("stg_game_log", "season", "2024-25", 1000)
        assert journal.get_watermark("stg_game_log", "season") == "2024-25"

    def test_upsert_watermark(self, journal: PipelineJournal) -> None:
        journal.set_watermark("t", "s", "v1", 100)
        journal.set_watermark("t", "s", "v2", 200)
        assert journal.get_watermark("t", "s") == "v2"


class TestJournalExtraction:
    @pytest.mark.parametrize(
        ("column_name", "expected_sql_type", "expected_value"),
        [
            ("logical_call_receipt_sha256", "VARCHAR", None),
            ("provider_authority_sha256", "VARCHAR", None),
            ("logical_parameters_sha256", "VARCHAR", None),
            ("result_route_ids_json", "VARCHAR", None),
            ("w2_required", "BOOLEAN", False),
            ("w2_source_call_admission_sha256", "VARCHAR", None),
            ("w2_source_call_admission_bytes", "BLOB", None),
            ("raw_authority_bundle_sha256", "VARCHAR", None),
            ("raw_authority_persistence_receipt_sha256", "VARCHAR", None),
            ("committed_staging_readback_count", "BIGINT", None),
            ("committed_staging_readback_root_sha256", "VARCHAR", None),
            ("w2_operation_key_sha256", "VARCHAR", None),
            ("w2_operation_receipt_sha256", "VARCHAR", None),
            ("w2_operation_persistence_receipt_sha256", "VARCHAR", None),
        ],
    )
    def test_read_only_legacy_projection_has_exact_absent_authority_sql_types(
        self,
        duckdb_memory_conn: duckdb.DuckDBPyConnection,
        column_name: str,
        expected_sql_type: str,
        expected_value: object,
    ) -> None:
        duckdb_memory_conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                PRIMARY KEY (endpoint, params)
            )
            """
        )
        duckdb_memory_conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, rows_extracted)
            VALUES ('legacy', '{}', 'done', 1)
            """
        )
        journal = PipelineJournal(duckdb_memory_conn, migrate_schema=False)

        cursor = duckdb_memory_conn.execute(
            f"SELECT {journal._authority_projection()} FROM _extraction_journal"
        )
        assert cursor.description is not None
        description = {item[0]: str(item[1]) for item in cursor.description}
        row = cursor.fetchone()
        assert row is not None
        projected_row = dict(zip((item[0] for item in cursor.description), row, strict=True))

        assert description[column_name] == expected_sql_type
        assert projected_row[column_name] == expected_value

    def test_read_only_unmigrated_legacy_journal_preserves_non_w2_done_surfaces(
        self,
        duckdb_memory_conn: duckdb.DuckDBPyConnection,
    ) -> None:
        duckdb_memory_conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                PRIMARY KEY (endpoint, params)
            )
            """
        )
        params = '{"season":"2024-25","season_type":"Regular Season"}'
        duckdb_memory_conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, rows_extracted)
            VALUES ('legacy', $1, 'done', 7)
            """,
            [params],
        )
        before = duckdb_memory_conn.execute("PRAGMA table_info('_extraction_journal')").fetchall()
        journal = PipelineJournal(duckdb_memory_conn, migrate_schema=False)

        assert journal.was_extracted("legacy", params)
        assert not journal.was_extracted("legacy", params, require_receipt=True)
        assert not journal.was_extracted("legacy", params, require_w2_operation=True)
        assert journal.was_extracted_batch([("legacy", params)]) == {("legacy", params)}
        assert (
            journal.was_extracted_batch(
                [("legacy", params)],
                require_receipt=True,
            )
            == set()
        )
        assert journal.has_done_entries()
        assert not journal.has_done_entries(require_w2_operation=True)
        assert journal.resume_summary() == {
            "done": 1,
            "failed": 0,
            "running": 0,
            "abandoned": 0,
            "total_rows": 7,
        }
        assert journal.resume_summary(require_w2_operation=True) == {
            "done": 0,
            "failed": 1,
            "running": 0,
            "abandoned": 0,
            "total_rows": 0,
        }
        assert journal.count_by_endpoint_and_status() == [("legacy", "done", 1)]
        assert journal.count_done_by_endpoint_and_season() == [("legacy", "2024-25", 1)]
        assert journal.count_done_by_endpoint_season_type() == [
            ("legacy", "2024-25", "Regular Season", 1)
        ]
        entries = journal.fetch_entries(status_filter="done")
        assert len(entries) == 1
        assert entries[0][:4] == ("legacy", params, "done", 0)
        assert (
            duckdb_memory_conn.execute("PRAGMA table_info('_extraction_journal')").fetchall()
            == before
        )

    @pytest.mark.parametrize(
        "extra_columns",
        [
            (("w2_required", "BOOLEAN", None),),
            (("w2_required", "VARCHAR", "false"),),
            (("w2_required", "INTEGER", 0),),
            (("w2_source_call_admission_sha256", "VARCHAR", "a" * 64),),
        ],
        ids=[
            "present-null-marker",
            "foreign-varchar-marker",
            "foreign-integer-marker",
            "orphan-evidence-with-absent-marker",
        ],
    )
    def test_read_only_hostile_authority_is_nonterminal_and_immutable_across_surfaces(
        self,
        duckdb_memory_conn: duckdb.DuckDBPyConnection,
        extra_columns: tuple[tuple[str, str, object], ...],
    ) -> None:
        duckdb_memory_conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                PRIMARY KEY (endpoint, params)
            )
            """
        )
        for column_name, sql_type, _value in extra_columns:
            duckdb_memory_conn.execute(
                f"ALTER TABLE _extraction_journal ADD COLUMN {column_name} {sql_type}"
            )
        params = '{"season":"2024-25","season_type":"Regular Season"}'
        duckdb_memory_conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, rows_extracted)
            VALUES ('hostile', $1, 'done', 7)
            """,
            [params],
        )
        for column_name, _sql_type, value in extra_columns:
            duckdb_memory_conn.execute(
                f"UPDATE _extraction_journal SET {column_name} = $1",
                [value],
            )
        schema_before = duckdb_memory_conn.execute(
            "PRAGMA table_info('_extraction_journal')"
        ).fetchall()
        rows_before = duckdb_memory_conn.execute("SELECT * FROM _extraction_journal").fetchall()
        journal = PipelineJournal(duckdb_memory_conn, migrate_schema=False)

        assert not journal.was_extracted("hostile", params)
        assert not journal.was_extracted("hostile", params, require_receipt=True)
        assert not journal.was_extracted("hostile", params, require_w2_operation=True)
        assert journal.was_extracted_batch([("hostile", params)]) == set()
        assert not journal.has_done_entries()
        assert not journal.has_done_entries(require_w2_operation=True)
        assert journal.resume_summary() == {
            "done": 0,
            "failed": 1,
            "running": 0,
            "abandoned": 0,
            "total_rows": 0,
        }
        assert journal.resume_summary(require_w2_operation=True) == {
            "done": 0,
            "failed": 1,
            "running": 0,
            "abandoned": 0,
            "total_rows": 0,
        }
        assert journal.count_by_endpoint_and_status() == [("hostile", "failed", 1)]
        assert journal.count_done_by_endpoint_and_season() == []
        assert journal.count_done_by_endpoint_season_type() == []
        assert journal.fetch_entries(status_filter="done") == []
        all_entries = journal.fetch_entries()
        assert len(all_entries) == 1
        assert all_entries[0][:4] == ("hostile", params, "failed", 0)

        assert (
            duckdb_memory_conn.execute("PRAGMA table_info('_extraction_journal')").fetchall()
            == schema_before
        )
        assert (
            duckdb_memory_conn.execute("SELECT * FROM _extraction_journal").fetchall()
            == rows_before
        )

    def test_read_only_partial_schema_never_downgrades_present_w2_requirement(
        self,
        duckdb_memory_conn: duckdb.DuckDBPyConnection,
    ) -> None:
        duckdb_memory_conn.execute(
            """
            CREATE TABLE _extraction_journal (
                endpoint VARCHAR NOT NULL,
                params VARCHAR,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                w2_required BOOLEAN,
                PRIMARY KEY (endpoint, params)
            )
            """
        )
        duckdb_memory_conn.execute(
            """
            INSERT INTO _extraction_journal
                (endpoint, params, status, rows_extracted, w2_required)
            VALUES ('w2_partial', '{}', 'done', 1, TRUE)
            """
        )
        before = duckdb_memory_conn.execute("PRAGMA table_info('_extraction_journal')").fetchall()
        journal = PipelineJournal(duckdb_memory_conn, migrate_schema=False)

        assert not journal.was_extracted("w2_partial", "{}")
        assert journal.was_extracted_batch([("w2_partial", "{}")]) == set()
        assert not journal.has_done_entries()
        assert journal.resume_summary()["failed"] == 1
        assert journal.count_by_endpoint_and_status() == [("w2_partial", "failed", 1)]
        assert journal.count_done_by_endpoint_season_type() == []
        assert journal.fetch_entries(status_filter="done") == []
        assert (
            duckdb_memory_conn.execute("PRAGMA table_info('_extraction_journal')").fetchall()
            == before
        )

    def test_injected_utc_clock_is_normalized_and_exact(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    ) -> None:
        fixed = datetime(2026, 8, 13, 7, 30, tzinfo=timezone(timedelta(hours=2)))
        journal = PipelineJournal(
            duckdb_memory_with_pipeline_tables,
            utc_now=lambda: fixed,
        )
        journal.record_start("ep", "p")
        journal.record_success("ep", "p", 1)

        row = duckdb_memory_with_pipeline_tables.execute(
            "SELECT started_at, completed_at FROM _extraction_journal"
        ).fetchone()
        expected = fixed.astimezone(UTC).replace(tzinfo=None)
        assert row == (expected, expected)

    @pytest.mark.parametrize(
        "value",
        [datetime(2026, 8, 13), "2026-08-13T00:00:00Z"],
    )
    def test_injected_utc_clock_rejects_invalid_values(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
        value: object,
    ) -> None:
        journal = PipelineJournal(
            duckdb_memory_with_pipeline_tables,
            utc_now=lambda: cast("datetime", value),
        )
        with pytest.raises(ValueError, match="aware datetime"):
            journal.record_start("ep", "p")

    def test_default_clock_remains_available(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    ) -> None:
        journal = PipelineJournal(duckdb_memory_with_pipeline_tables)
        journal.record_start("ep", "p")
        started_at = duckdb_memory_with_pipeline_tables.execute(
            "SELECT started_at FROM _extraction_journal"
        ).fetchone()[0]
        assert isinstance(started_at, datetime)

    def test_successor_promotion_rejects_nested_transaction_ownership(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    ) -> None:
        successor = PipelineJournal(
            duckdb_memory_with_pipeline_tables,
            successor_generation_sha256="a" * 64,
        )
        successor.record_start("ep", "{}")
        duckdb_memory_with_pipeline_tables.execute("BEGIN TRANSACTION")
        try:
            with pytest.raises(RuntimeError, match="transaction ownership"):
                successor.was_extracted("ep", "{}")
        finally:
            duckdb_memory_with_pipeline_tables.execute("ROLLBACK")

    def test_successor_initialization_does_not_migrate_the_baseline_journal(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    ) -> None:
        before = duckdb_memory_with_pipeline_tables.execute(
            "PRAGMA table_info('_extraction_journal')"
        ).fetchall()
        assert "logical_call_receipt_sha256" not in {row[1] for row in before}

        successor = PipelineJournal(
            duckdb_memory_with_pipeline_tables,
            successor_generation_sha256="a" * 64,
        )

        after = duckdb_memory_with_pipeline_tables.execute(
            "PRAGMA table_info('_extraction_journal')"
        ).fetchall()
        assert after == before
        assert successor.successor_generation_sha256 == "a" * 64

    def test_existing_successor_rows_are_additively_migrated_to_w2_authority(
        self,
        duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
    ) -> None:
        duckdb_memory_with_pipeline_tables.execute(
            """
            CREATE TABLE _successor_extraction_journal (
                successor_generation_sha256 VARCHAR NOT NULL,
                endpoint VARCHAR NOT NULL,
                params VARCHAR NOT NULL,
                status VARCHAR NOT NULL,
                started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                completed_at TIMESTAMP,
                rows_extracted BIGINT,
                error_message VARCHAR,
                retry_count INTEGER DEFAULT 0,
                logical_call_receipt_sha256 VARCHAR,
                provider_authority_sha256 VARCHAR,
                logical_parameters_sha256 VARCHAR,
                result_route_ids_json VARCHAR,
                PRIMARY KEY (successor_generation_sha256, endpoint, params)
            )
            """
        )
        duckdb_memory_with_pipeline_tables.execute(
            """
            INSERT INTO _successor_extraction_journal
                (successor_generation_sha256, endpoint, params, status, rows_extracted)
            VALUES ($1, 'legacy', '{}', 'done', 1)
            """,
            ["a" * 64],
        )

        PipelineJournal(
            duckdb_memory_with_pipeline_tables,
            successor_generation_sha256="a" * 64,
        )

        row = duckdb_memory_with_pipeline_tables.execute(
            """
            SELECT w2_required,
                   w2_source_call_admission_sha256,
                   w2_source_call_admission_bytes,
                   raw_authority_bundle_sha256,
                   raw_authority_persistence_receipt_sha256,
                   committed_staging_readback_count,
                   committed_staging_readback_root_sha256,
                   w2_operation_key_sha256,
                   w2_operation_receipt_sha256,
                   w2_operation_persistence_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = 'legacy' AND params = '{}'
            """,
            ["a" * 64],
        ).fetchone()
        assert row == (False, None, None, None, None, None, None, None, None, None)
        columns = {
            str(column[1]): column
            for column in duckdb_memory_with_pipeline_tables.execute(
                "PRAGMA table_info('_successor_extraction_journal')"
            ).fetchall()
        }
        assert columns["w2_required"][3] is True

    def test_successor_generation_completion_is_exact_and_never_reuses_baseline(
        self,
        journal: PipelineJournal,
    ) -> None:
        first = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        second = PipelineJournal(
            journal._conn,
            successor_generation_sha256="b" * 64,
        )
        params = '{"season": "2025-26"}'
        first_binding = _receipt_binding(
            params={"season": "2025-26"},
            endpoint="league_game_log",
        )
        second_binding = _receipt_binding(
            receipt="b" * 64,
            params={"season": "2025-26"},
            endpoint="league_game_log",
        )
        _persist_receipt_binding(first, first_binding)

        journal.record_start("league_game_log", params)
        journal.record_success("league_game_log", params, 10)
        assert journal.was_extracted("league_game_log", params)
        assert not first.was_extracted("league_game_log", params)
        second.record_start("league_game_log", params)
        assert not second.was_extracted("league_game_log", params)
        second.clear_journal()

        first.record_start("league_game_log", params)
        first.record_success(
            "league_game_log",
            params,
            11,
            receipt_binding=first_binding,
        )
        assert first.was_extracted("league_game_log", params)
        assert first.has_done_entries()
        assert first.was_extracted_batch([("league_game_log", params)]) == {
            ("league_game_log", params)
        }
        assert not second.was_extracted("league_game_log", params)
        assert not second.has_done_entries()

        _persist_receipt_binding(second, second_binding)
        second.record_start("league_game_log", params)
        second.record_success(
            "league_game_log",
            params,
            12,
            receipt_binding=second_binding,
        )
        shared_receipt = journal._conn.execute(
            """
            SELECT logical_call_receipt_sha256
            FROM _staging_chunk_journal
            WHERE result_route_id = 'league_game_log:stg_ep:0'
            """
        ).fetchone()
        assert shared_receipt == (second_binding.logical_call_receipt_sha256,)
        assert second.was_extracted("league_game_log", params)
        # Gen1 remains valid through its generation-bound replacement receipt,
        # even though shared staging now reflects gen2's fresh observation.
        assert first.was_extracted("league_game_log", params)
        rows = journal._conn.execute(
            """
            SELECT successor_generation_sha256, rows_extracted
            FROM _successor_extraction_journal
            ORDER BY successor_generation_sha256
            """
        ).fetchall()
        assert rows == [("a" * 64, 11), ("b" * 64, 12)]

    def test_successor_failure_resume_and_clear_are_generation_scoped(
        self,
        journal: PipelineJournal,
    ) -> None:
        first = PipelineJournal(journal._conn, successor_generation_sha256="a" * 64)
        second = PipelineJournal(journal._conn, successor_generation_sha256="b" * 64)

        journal.record_start("ep", "{}")
        journal.record_failure("ep", "{}", "baseline_error")
        first.record_start("ep", "{}")
        first.record_failure("ep", "{}", "first_error")
        second.record_start("ep", "{}")
        second.record_failure("ep", "{}", "second_error")

        assert journal.get_failed() == [("ep", "{}", "baseline_error")]
        assert first.get_failed() == [("ep", "{}", "first_error")]
        assert second.get_failed() == [("ep", "{}", "second_error")]
        assert first.resume_summary()["failed"] == 1
        assert second.error_breakdown() == [("second_error", 1)]
        first.clear_journal()
        assert first.resume_summary()["failed"] == 0
        assert second.resume_summary()["failed"] == 1
        assert journal.resume_summary()["failed"] == 1

    @pytest.mark.parametrize("value", ["A" * 64, "a" * 63, "", True])
    def test_successor_generation_identity_requires_lowercase_sha256(
        self,
        journal: PipelineJournal,
        value: object,
    ) -> None:
        with pytest.raises(ValueError, match="lowercase SHA-256"):
            PipelineJournal(
                journal._conn,
                successor_generation_sha256=cast("str | None", value),
            )

    def test_successor_completion_requires_a_live_receipt_without_opt_in(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding = _receipt_binding()
        successor.record_start("ep", "{}")

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="completion requires a logical-call receipt",
        ):
            successor.record_success("ep", "{}", 1)

        assert not successor.was_extracted("ep", "{}")
        assert not successor.has_done_entries()
        assert successor.was_extracted_batch([("ep", "{}")]) == set()

        _persist_receipt_binding(successor, binding)
        successor.record_success("ep", "{}", 1, receipt_binding=binding)
        assert successor.was_extracted("ep", "{}")
        assert successor.has_done_entries()
        assert successor.was_extracted_batch([("ep", "{}")]) == {("ep", "{}")}
        assert successor.resume_summary() == {
            "done": 1,
            "failed": 0,
            "running": 0,
            "abandoned": 0,
            "total_rows": 1,
        }

        journal._conn.execute(
            """
            UPDATE _successor_staging_replacement_journal
            SET provider_authority_sha256 = $1
            WHERE successor_generation_sha256 = $2
              AND logical_call_receipt_sha256 = $3
            """,
            ["d" * 64, "a" * 64, binding.logical_call_receipt_sha256],
        )
        assert not successor.was_extracted("ep", "{}")
        assert not successor.has_done_entries()
        assert successor.was_extracted_batch([("ep", "{}")]) == set()
        assert successor.resume_summary() == {
            "done": 0,
            "failed": 1,
            "running": 0,
            "abandoned": 0,
            "total_rows": 0,
        }

        successor.record_start("ep", "{}")
        row = journal._conn.execute(
            """
            SELECT status, completed_at, rows_extracted,
                   logical_call_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = 'ep' AND params = '{}'
            """,
            ["a" * 64],
        ).fetchone()
        assert row == ("running", None, None, None)

    def test_successor_batch_recovers_committed_multi_route_call_before_replay(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        endpoint = "box_score_summary"
        params_value = {"game_id": "0022500001"}
        params = '{"game_id": "0022500001"}'
        binding = _receipt_binding(
            params=params_value,
            endpoint=endpoint,
            routes=(("stg_box_score_line", 0), ("stg_box_score_official", 1)),
        )
        successor.record_start(endpoint, params)
        _persist_receipt_binding(
            successor,
            binding,
            frames={
                "stg_box_score_line": pl.DataFrame({"value": [1, 2]}),
                "stg_box_score_official": pl.DataFrame({"value": [3, 4, 5]}),
            },
        )

        # Simulate restart prefetch after staging committed but before record_success.
        assert successor.was_extracted_batch([(endpoint, params)]) == {(endpoint, params)}
        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, error_message,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_ids_json
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = $2 AND params = $3
            """,
            ["a" * 64, endpoint, params],
        ).fetchone()
        assert row == (
            "done",
            5,
            None,
            binding.logical_call_receipt_sha256,
            binding.provider_authority_sha256,
            binding.logical_parameters_sha256,
            '["box_score_summary:stg_box_score_line:0",'
            '"box_score_summary:stg_box_score_official:1"]',
        )
        assert successor.was_extracted(endpoint, params)

    def test_successor_record_start_recovers_failed_typed_zero_commit(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        endpoint = "video_details_asset"
        params_value = {"game_id": "0022500001", "measure_type": "Boxscore"}
        params = '{"game_id": "0022500001", "measure_type": "Boxscore"}'
        binding = _receipt_binding(
            receipt="b" * 64,
            params=params_value,
            endpoint=endpoint,
            routes=(("stg_video_details_asset", 0),),
        )
        successor.record_start(endpoint, params)
        _persist_receipt_binding(
            successor,
            binding,
            frames={"stg_video_details_asset": pl.DataFrame(schema={"value": pl.Int64})},
        )
        successor.record_failure(endpoint, params, "interrupted_resume")

        successor.record_start(endpoint, params)

        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, error_message,
                   logical_call_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = $2 AND params = $3
            """,
            ["a" * 64, endpoint, params],
        ).fetchone()
        assert row == ("done", 0, None, binding.logical_call_receipt_sha256)
        assert successor.was_extracted(endpoint, params)

    def test_successor_reloads_exact_multi_route_replacement_attestations(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding = _receipt_binding(
            receipt="b" * 64,
            params={"game_id": "0022500001"},
            endpoint="box_score_summary",
            routes=(("stg_box_score_line", 0), ("stg_box_score_official", 1)),
        )
        _persist_receipt_binding(successor, binding)

        restored = successor.load_successor_replacement_attestations()

        assert tuple(item.result_route_id for item in restored) == binding.result_route_ids
        assert {item.logical_call_receipt_sha256 for item in restored} == {
            binding.logical_call_receipt_sha256
        }
        assert all(item.successor_generation_sha256 == "a" * 64 for item in restored)
        assert all(item.canonical_frame_format == CANONICAL_FRAME_FORMAT for item in restored)
        assert all(
            item.frame_content_hash_contract == FRAME_CONTENT_HASH_CONTRACT for item in restored
        )
        assert all(
            item.frame_schema_hash_contract == FRAME_SCHEMA_HASH_CONTRACT for item in restored
        )

    @pytest.mark.parametrize(
        ("table_name", "column", "hostile_value"),
        [
            ("_successor_staging_replacement_journal", "canonical_frame_format", None),
            (
                "_successor_staging_replacement_journal",
                "frame_content_hash_contract",
                "nbadb_arrow_logical_table_sha256_v1",
            ),
            (
                "_successor_staging_replacement_journal",
                "frame_schema_hash_contract",
                "nbadb_arrow_schema_sha256_v1",
            ),
        ],
        ids=["null-successor", "v1-successor", "v1-successor-schema"],
    )
    def test_successor_replay_rejects_stale_frame_contract_evidence(
        self,
        journal: PipelineJournal,
        table_name: str,
        column: str,
        hostile_value: str | None,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding = _receipt_binding()
        successor.record_start("ep", "{}")
        _persist_receipt_binding(successor, binding)
        successor.record_success("ep", "{}", 1, receipt_binding=binding)
        if hostile_value is None:
            journal._conn.execute(f"ALTER TABLE {table_name} ALTER COLUMN {column} DROP NOT NULL")
        journal._conn.execute(
            f"UPDATE {table_name} SET {column} = $1 WHERE logical_call_receipt_sha256 = $2",
            [hostile_value, binding.logical_call_receipt_sha256],
        )

        assert not successor.was_extracted("ep", "{}")
        assert successor.was_extracted_batch([("ep", "{}")]) == set()
        assert not successor.has_done_entries()
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="recovery inventory is invalid",
        ):
            successor.load_successor_replacement_attestations()

    def test_successor_replacement_reload_rejects_tampered_live_staging(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding = _receipt_binding(
            params={"game_id": "0022500001"},
            endpoint="box_score_summary",
            routes=(("stg_box_score_line", 0),),
        )
        _persist_receipt_binding(successor, binding)
        journal._conn.execute(
            """
            UPDATE _staging_chunk_journal
            SET persisted_content_sha256 = $1
            WHERE logical_call_receipt_sha256 = $2
            """,
            ["f" * 64, binding.logical_call_receipt_sha256],
        )

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="recovery inventory is invalid",
        ):
            successor.load_successor_replacement_attestations()

    def test_successor_crash_recovery_rejects_partial_replacement_inventory(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        endpoint = "box_score_summary"
        params = '{"game_id": "0022500001"}'
        binding = _receipt_binding(
            params={"game_id": "0022500001"},
            endpoint=endpoint,
            routes=(("stg_box_score_line", 0), ("stg_box_score_official", 1)),
        )
        successor.record_start(endpoint, params)
        _persist_receipt_binding(successor, binding)
        journal._conn.execute(
            """
            DELETE FROM _successor_staging_replacement_journal
            WHERE successor_generation_sha256 = $1
              AND staging_key = 'stg_box_score_official'
            """,
            ["a" * 64],
        )

        assert not successor.was_extracted(endpoint, params)
        successor.record_start(endpoint, params)
        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, logical_call_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = $2 AND params = $3
            """,
            ["a" * 64, endpoint, params],
        ).fetchone()
        assert row == ("running", None, None)

    def test_successor_crash_recovery_rejects_tampered_replacement_inventory(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        successor.record_start("ep", "{}")
        binding = _receipt_binding()
        _persist_receipt_binding(successor, binding)
        journal._conn.execute(
            """
            UPDATE _successor_staging_replacement_journal
            SET persisted_row_count = 99
            WHERE successor_generation_sha256 = $1
              AND logical_call_receipt_sha256 = $2
            """,
            ["a" * 64, binding.logical_call_receipt_sha256],
        )

        assert successor.was_extracted_batch([("ep", "{}")]) == set()
        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, logical_call_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = 'ep' AND params = '{}'
            """,
            ["a" * 64],
        ).fetchone()
        assert row == ("running", None, None)

    def test_successor_crash_recovery_rejects_mixed_receipt_roots(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        endpoint = "box_score_summary"
        params = '{"game_id": "0022500001"}'
        first = _receipt_binding(
            receipt="b" * 64,
            params={"game_id": "0022500001"},
            endpoint=endpoint,
            routes=(("stg_box_score_line", 0),),
        )
        second = _receipt_binding(
            receipt="d" * 64,
            params={"game_id": "0022500001"},
            endpoint=endpoint,
            routes=(("stg_box_score_official", 1),),
        )
        successor.record_start(endpoint, params)
        _persist_receipt_binding(successor, first)
        _persist_receipt_binding(successor, second)

        assert not successor.was_extracted(endpoint, params)
        successor.record_start(endpoint, params)
        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, logical_call_receipt_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = $2 AND params = $3
            """,
            ["a" * 64, endpoint, params],
        ).fetchone()
        assert row == ("running", None, None)

    def test_baseline_journal_does_not_promote_a_committed_staging_receipt(
        self,
        journal: PipelineJournal,
    ) -> None:
        journal.record_start("ep", "{}", require_receipt=True)
        _persist_receipt_binding(journal, _receipt_binding())

        assert not journal.was_extracted("ep", "{}", require_receipt=True)
        journal.record_start("ep", "{}", require_receipt=True)
        row = journal._conn.execute(
            """
            SELECT status, rows_extracted, logical_call_receipt_sha256
            FROM _extraction_journal
            WHERE endpoint = 'ep' AND params = '{}'
            """
        ).fetchone()
        assert row == ("running", None, None)

    def test_successor_runtime_recovery_mutations_are_generation_scoped(
        self,
        journal: PipelineJournal,
    ) -> None:
        first = PipelineJournal(journal._conn, successor_generation_sha256="a" * 64)
        second = PipelineJournal(journal._conn, successor_generation_sha256="b" * 64)
        for current in (journal, first, second):
            current.record_start("stale", "{}")
        journal._conn.execute("UPDATE _extraction_journal SET started_at = TIMESTAMP '2000-01-01'")
        journal._conn.execute(
            "UPDATE _successor_extraction_journal SET started_at = TIMESTAMP '2000-01-01'"
        )

        assert first.reset_stale_running(cutoff_minutes=60) == 1
        baseline_row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = 'stale'"
        ).fetchone()
        assert baseline_row is not None
        baseline_status = baseline_row[0]
        successor_statuses = journal._conn.execute(
            """
            SELECT successor_generation_sha256, status
            FROM _successor_extraction_journal
            WHERE endpoint = 'stale'
            ORDER BY successor_generation_sha256
            """
        ).fetchall()
        assert baseline_status == "running"
        assert successor_statuses == [("a" * 64, "failed"), ("b" * 64, "running")]

        journal.record_failure("stale", "{}", "baseline")
        second.record_failure("stale", "{}", "second")
        journal._conn.execute(
            "UPDATE _extraction_journal SET retry_count = $1 WHERE endpoint = 'stale'",
            [PipelineJournal.MAX_RETRIES],
        )
        journal._conn.execute(
            """
            UPDATE _successor_extraction_journal
            SET retry_count = $1
            WHERE endpoint = 'stale'
            """,
            [PipelineJournal.MAX_RETRIES],
        )

        assert first.abandon_exhausted() == 1
        baseline_row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = 'stale'"
        ).fetchone()
        assert baseline_row is not None
        baseline_status = baseline_row[0]
        successor_statuses = journal._conn.execute(
            """
            SELECT successor_generation_sha256, status
            FROM _successor_extraction_journal
            WHERE endpoint = 'stale'
            ORDER BY successor_generation_sha256
            """
        ).fetchall()
        assert baseline_status == "failed"
        assert successor_statuses == [("a" * 64, "abandoned"), ("b" * 64, "failed")]

        for current in (journal, first, second):
            current.record_start("recent", "{}")
        assert first.recover_interrupted_running() == 1
        baseline_row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = 'recent'"
        ).fetchone()
        assert baseline_row is not None
        baseline_status = baseline_row[0]
        successor_statuses = journal._conn.execute(
            """
            SELECT successor_generation_sha256, status
            FROM _successor_extraction_journal
            WHERE endpoint = 'recent'
            ORDER BY successor_generation_sha256
            """
        ).fetchall()
        assert baseline_status == "running"
        assert successor_statuses == [("a" * 64, "failed"), ("b" * 64, "running")]

    @pytest.mark.parametrize(
        ("method_name", "kwargs"),
        [
            ("reset_entries", {"endpoint": "ep"}),
            ("clear_entries", {"endpoint": "ep"}),
            ("count_by_endpoint_and_status", {}),
            ("count_done_by_endpoint_and_season", {}),
            ("count_done_by_endpoint_season_type", {}),
            ("fetch_entries", {}),
        ],
    )
    def test_successor_admin_surfaces_fail_closed_without_touching_any_journal(
        self,
        journal: PipelineJournal,
        method_name: str,
        kwargs: dict[str, object],
    ) -> None:
        first = PipelineJournal(journal._conn, successor_generation_sha256="a" * 64)
        second = PipelineJournal(journal._conn, successor_generation_sha256="b" * 64)
        journal.record_start("ep", "{}")
        journal.record_failure("ep", "{}", "baseline")
        first.record_start("ep", "{}")
        first.record_failure("ep", "{}", "first")
        second.record_start("ep", "{}")
        second.record_failure("ep", "{}", "second")
        baseline_before = journal._conn.execute(
            "SELECT * FROM _extraction_journal ORDER BY endpoint, params"
        ).fetchall()
        successor_before = journal._conn.execute(
            """
            SELECT * FROM _successor_extraction_journal
            ORDER BY successor_generation_sha256, endpoint, params
            """
        ).fetchall()

        with pytest.raises(
            RuntimeError,
            match=rf"{method_name} is unavailable when successor_generation_sha256 is set",
        ):
            getattr(first, method_name)(**kwargs)

        assert (
            journal._conn.execute(
                "SELECT * FROM _extraction_journal ORDER BY endpoint, params"
            ).fetchall()
            == baseline_before
        )
        assert (
            journal._conn.execute(
                """
                SELECT * FROM _successor_extraction_journal
                ORDER BY successor_generation_sha256, endpoint, params
                """
            ).fetchall()
            == successor_before
        )

    def test_record_start_and_success(
        self,
        journal: PipelineJournal,
    ) -> None:
        journal.record_start("box_score", '{"game_id": "001"}')
        assert not journal.was_extracted(
            "box_score",
            '{"game_id": "001"}',
        )
        journal.record_success(
            "box_score",
            '{"game_id": "001"}',
            rows=50,
        )
        assert journal.was_extracted("box_score", '{"game_id": "001"}')

    def test_record_failure(self, journal: PipelineJournal) -> None:
        journal.record_start("ep", "p")
        journal.record_failure("ep", "p", "timeout")
        assert not journal.was_extracted("ep", "p")
        failed = journal.get_failed()
        assert len(failed) == 1
        assert failed[0] == ("ep", "p", "timeout")

    def test_clear_journal(self, journal: PipelineJournal) -> None:
        journal.record_start("ep", "p")
        journal.record_success("ep", "p", 10)
        journal.clear_journal()
        assert not journal.was_extracted("ep", "p")

    def test_resume_skips_done(self, journal: PipelineJournal) -> None:
        """Verify only successful rows are treated as complete."""
        journal.record_start("ep", "p")
        assert not journal.was_extracted("ep", "p")  # running
        journal.record_failure("ep", "p", "err")
        assert not journal.was_extracted("ep", "p")  # failed
        journal.record_start("ep", "p")
        journal.record_success("ep", "p", 5)
        assert journal.was_extracted("ep", "p")  # done

    def test_has_done_entries(self, journal: PipelineJournal) -> None:
        assert not journal.has_done_entries()
        journal.record_start("ep", "p")
        assert not journal.has_done_entries()
        journal.record_success("ep", "p", 5)
        assert journal.has_done_entries()

    def test_record_start_does_not_overwrite_done(self, journal: PipelineJournal) -> None:
        journal.record_start("ep", "p")
        journal.record_success("ep", "p", 5)

        journal.record_start("ep", "p")

        row = journal._conn.execute(
            "SELECT status, rows_extracted, completed_at FROM _extraction_journal "
            "WHERE endpoint = 'ep' AND params = 'p'"
        ).fetchone()
        assert row[0] == "done"
        assert row[1] == 5
        assert row[2] is not None

    def test_legacy_done_is_compatible_only_when_capture_is_disabled(
        self,
        journal: PipelineJournal,
    ) -> None:
        journal.record_start("ep", "{}")
        journal.record_success("ep", "{}", 5)

        assert journal.was_extracted("ep", "{}")
        assert not journal.was_extracted("ep", "{}", require_receipt=True)

        journal.record_start("ep", "{}", require_receipt=True)
        row = journal._conn.execute(
            """
            SELECT status, completed_at, rows_extracted,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_ids_json
            FROM _extraction_journal
            WHERE endpoint = 'ep' AND params = '{}'
            """
        ).fetchone()
        assert row == ("running", None, None, None, None, None, None)

    def test_receipt_bound_done_requires_matching_staging_inventory(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding = _receipt_binding()
        journal.record_start("ep", "{}", require_receipt=True)
        _persist_receipt_binding(journal, binding)
        journal.record_success("ep", "{}", 1, receipt_binding=binding)

        assert journal.was_extracted("ep", "{}", require_receipt=True)
        assert journal.was_extracted_batch(
            [("ep", "{}")],
            require_receipt=True,
        ) == {("ep", "{}")}

    @pytest.mark.parametrize(
        ("column", "hostile_value"),
        [
            ("canonical_frame_format", None),
            ("frame_content_hash_contract", "nbadb_arrow_logical_table_sha256_v1"),
            ("frame_schema_hash_contract", "nbadb_arrow_logical_table_sha256_v2"),
        ],
        ids=["null-format", "v1-content", "foreign-schema-contract"],
    )
    def test_receipt_bound_done_rejects_stale_or_foreign_frame_contract_ids(
        self,
        journal: PipelineJournal,
        column: str,
        hostile_value: str | None,
    ) -> None:
        binding = _receipt_binding()
        journal.record_start("ep", "{}", require_receipt=True)
        _persist_receipt_binding(journal, binding)
        journal.record_success("ep", "{}", 1, receipt_binding=binding)
        if hostile_value is None:
            journal._conn.execute(
                f"ALTER TABLE _staging_chunk_journal ALTER COLUMN {column} DROP NOT NULL"
            )
        journal._conn.execute(
            f"UPDATE _staging_chunk_journal SET {column} = $1 "
            "WHERE logical_call_receipt_sha256 = $2",
            [hostile_value, binding.logical_call_receipt_sha256],
        )

        assert not journal.was_extracted("ep", "{}", require_receipt=True)
        assert (
            journal.was_extracted_batch(
                [("ep", "{}")],
                require_receipt=True,
            )
            == set()
        )
        journal.record_start("ep", "{}", require_receipt=True)
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="staging receipt inventory",
        ):
            journal.record_success("ep", "{}", 1, receipt_binding=binding)

    def test_record_success_rejects_a_different_staging_receipt_root(
        self,
        journal: PipelineJournal,
    ) -> None:
        journal.record_start("ep", "{}", require_receipt=True)
        _persist_receipt_binding(journal, _receipt_binding(receipt="a" * 64))

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="staging receipt inventory",
        ):
            journal.record_success(
                "ep",
                "{}",
                1,
                receipt_binding=_receipt_binding(receipt="d" * 64),
            )

        status = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = 'ep' AND params = '{}'"
        ).fetchone()[0]
        assert status == "running"


class TestJournalW2Authority:
    def test_w2_done_round_trips_through_every_resume_trust_path(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name

        journal.record_start(
            endpoint,
            params,
            require_receipt=True,
            require_w2_operation=True,
        )
        journal.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes()),
        )

        assert journal.was_extracted(
            endpoint,
            params,
            require_w2_operation=True,
        )
        assert journal.was_extracted_batch(
            [(endpoint, params)],
            require_w2_operation=True,
        ) == {(endpoint, params)}
        assert journal.has_done_entries(require_w2_operation=True)
        assert journal.resume_summary(require_w2_operation=True) == {
            "done": 1,
            "failed": 0,
            "running": 0,
            "abandoned": 0,
            "total_rows": 1,
        }
        row = journal._conn.execute(
            """
            SELECT w2_required,
                   w2_source_call_admission_sha256,
                   w2_source_call_admission_bytes,
                   raw_authority_bundle_sha256,
                   raw_authority_persistence_receipt_sha256,
                   committed_staging_readback_count,
                   committed_staging_readback_root_sha256,
                   w2_operation_key_sha256,
                   w2_operation_receipt_sha256,
                   w2_operation_persistence_receipt_sha256
            FROM _extraction_journal
            WHERE endpoint = $1 AND params = $2
            """,
            [endpoint, params],
        ).fetchone()
        assert row == (
            True,
            admission.admission_sha256,
            admission.canonical_bytes(),
            admission.raw_authority_bundle_sha256,
            admission.raw_authority_persistence_receipt_sha256,
            admission.committed_staging_readback_count,
            admission.committed_staging_readback_root_sha256,
            admission.operation_key_sha256,
            admission.operation_receipt_sha256,
            admission.w2_operation_persistence_receipt_sha256,
        )

        # Exact done authority remains terminal and is not reset by replayed start.
        journal.record_start(endpoint, params, require_w2_operation=True)
        assert journal.was_extracted(endpoint, params, require_w2_operation=True)

    def test_w2_required_success_rejects_missing_and_cross_call_admission(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name
        journal.record_start(endpoint, params, require_w2_operation=True)

        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="requires one exact admission",
        ):
            journal.record_success(
                endpoint,
                params,
                1,
                receipt_binding=binding,
            )

        cross_call = LogicalCallReceiptBinding(
            logical_call_receipt_sha256="f" * 64,
            endpoint_name=binding.endpoint_name,
            logical_parameters_sha256=binding.logical_parameters_sha256,
            provider_authority_sha256=binding.provider_authority_sha256,
            result_route_ids=binding.result_route_ids,
        )
        with pytest.raises(
            ParserInputCaptureIntegrityError,
            match="staging receipt inventory does not match",
        ):
            journal.record_success(
                endpoint,
                params,
                1,
                receipt_binding=cross_call,
                w2_admission=admission,
            )

        status = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = $1 AND params = $2",
            [endpoint, params],
        ).fetchone()
        assert status == ("running",)

    @pytest.mark.parametrize(
        ("column", "value"),
        [
            ("w2_source_call_admission_bytes", b"{}"),
            ("raw_authority_bundle_sha256", "f" * 64),
            ("committed_staging_readback_count", 2),
            ("w2_operation_receipt_sha256", "f" * 64),
        ],
    )
    def test_corrupt_w2_done_evidence_is_nonterminal_and_reset_clears_every_pin(
        self,
        journal: PipelineJournal,
        column: str,
        value: object,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name
        journal.record_start(endpoint, params, require_w2_operation=True)
        journal.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=admission,
        )
        journal._conn.execute(
            f"UPDATE _extraction_journal SET {column} = $1 WHERE endpoint = $2 AND params = $3",
            [value, endpoint, params],
        )

        assert not journal.was_extracted(endpoint, params)
        assert not journal.was_extracted(endpoint, params, require_w2_operation=True)
        assert not journal.has_done_entries(require_w2_operation=True)
        assert journal.resume_summary(require_w2_operation=True)["failed"] == 1
        assert journal.count_done_by_endpoint_season_type() == []
        assert journal.count_by_endpoint_and_status() == [(endpoint, "failed", 1)]
        assert journal.fetch_entries(status_filter="done") == []

        journal.record_start(endpoint, params, require_w2_operation=True)
        row = journal._conn.execute(
            """
            SELECT status,
                   w2_required,
                   w2_source_call_admission_sha256,
                   w2_source_call_admission_bytes,
                   raw_authority_bundle_sha256,
                   raw_authority_persistence_receipt_sha256,
                   committed_staging_readback_count,
                   committed_staging_readback_root_sha256,
                   w2_operation_key_sha256,
                   w2_operation_receipt_sha256,
                   w2_operation_persistence_receipt_sha256
            FROM _extraction_journal
            WHERE endpoint = $1 AND params = $2
            """,
            [endpoint, params],
        ).fetchone()
        assert row == ("running", True, None, None, None, None, None, None, None, None, None)

    def test_missing_durable_w2_row_makes_done_nonterminal(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name
        journal.record_start(endpoint, params, require_w2_operation=True)
        journal.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=admission,
        )
        journal._conn.execute(
            "DELETE FROM raw_nba_api_w2_operation WHERE operation_key_sha256 = $1",
            [admission.operation_key_sha256],
        )

        assert not journal.was_extracted(endpoint, params, require_w2_operation=True)
        assert (
            journal.was_extracted_batch(
                [(endpoint, params)],
                require_w2_operation=True,
            )
            == set()
        )

    def test_w2_required_success_must_begin_from_the_exact_running_row(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name
        journal.record_start(endpoint, params, require_w2_operation=True)
        journal.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=admission,
        )

        with pytest.raises(RuntimeError, match="no matching running row"):
            journal.record_success(
                endpoint,
                params,
                1,
                receipt_binding=binding,
                w2_admission=admission,
            )

    def test_selective_reset_clears_every_w2_authority_field(
        self,
        journal: PipelineJournal,
    ) -> None:
        binding, params, admission = _persist_w2_admission(journal)
        endpoint = binding.endpoint_name
        journal.record_start(endpoint, params, require_w2_operation=True)
        journal.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=admission,
        )

        assert journal.reset_entries(endpoint=endpoint) == 1

        row = journal._conn.execute(
            """
            SELECT status,
                   logical_call_receipt_sha256,
                   provider_authority_sha256,
                   logical_parameters_sha256,
                   result_route_ids_json,
                   w2_required,
                   w2_source_call_admission_sha256,
                   w2_source_call_admission_bytes,
                   raw_authority_bundle_sha256,
                   raw_authority_persistence_receipt_sha256,
                   committed_staging_readback_count,
                   committed_staging_readback_root_sha256,
                   w2_operation_key_sha256,
                   w2_operation_receipt_sha256,
                   w2_operation_persistence_receipt_sha256
            FROM _extraction_journal
            WHERE endpoint = $1 AND params = $2
            """,
            [endpoint, params],
        ).fetchone()
        assert row == ("failed", None, None, None, None, False, *([None] * 9))

    def test_w2_required_successor_staging_candidate_cannot_self_promote(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding = _receipt_binding(params={})
        successor.record_start("ep", "{}", require_w2_operation=True)
        _persist_receipt_binding(successor, binding)

        assert not successor.was_extracted("ep", "{}", require_w2_operation=True)
        assert (
            successor.was_extracted_batch(
                [("ep", "{}")],
                require_w2_operation=True,
            )
            == set()
        )
        row = journal._conn.execute(
            """
            SELECT status, w2_required, w2_source_call_admission_sha256
            FROM _successor_extraction_journal
            WHERE successor_generation_sha256 = $1
              AND endpoint = 'ep' AND params = '{}'
            """,
            ["a" * 64],
        ).fetchone()
        assert row == ("running", True, None)

    def test_w2_required_successor_round_trips_exact_admission(
        self,
        journal: PipelineJournal,
    ) -> None:
        successor = PipelineJournal(
            journal._conn,
            successor_generation_sha256="a" * 64,
        )
        binding, params, admission = _persist_w2_admission(successor)
        endpoint = binding.endpoint_name
        successor.record_start(endpoint, params, require_w2_operation=True)

        successor.record_success(
            endpoint,
            params,
            1,
            receipt_binding=binding,
            w2_admission=W2SourceCallAdmissionV1.from_canonical_bytes(admission.canonical_bytes()),
        )

        assert successor.was_extracted(
            endpoint,
            params,
            require_w2_operation=True,
        )
        assert successor.was_extracted_batch(
            [(endpoint, params)],
            require_w2_operation=True,
        ) == {(endpoint, params)}
        assert successor.has_done_entries(require_w2_operation=True)
        assert successor.resume_summary(require_w2_operation=True)["done"] == 1


class TestJournalRetryCap:
    def test_retry_count_increments(self, journal: PipelineJournal) -> None:
        journal.record_start("ep", "p")
        journal.record_failure("ep", "p", "err1")
        journal.record_start("ep", "p")
        journal.record_failure("ep", "p", "err2")
        row = journal._conn.execute(
            "SELECT retry_count FROM _extraction_journal WHERE endpoint = 'ep' AND params = 'p'"
        ).fetchone()
        assert row is not None
        assert row[0] == 2

    def test_get_failed_excludes_exhausted(self, journal: PipelineJournal) -> None:
        journal.record_start("ep", "p")
        for _ in range(PipelineJournal.MAX_RETRIES):
            journal.record_start("ep", "p")
            journal.record_failure("ep", "p", "err")
        assert journal.get_failed() == []

    def test_abandon_exhausted_transitions_status(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep', 'p', 'failed', ?)",
            [PipelineJournal.MAX_RETRIES],
        )
        journal.abandon_exhausted()
        row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint = 'ep' AND params = 'p'"
        ).fetchone()
        assert row[0] == "abandoned"
        assert not journal.was_extracted("ep", "p")

    def test_was_extracted_does_not_skip_abandoned(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep', 'p', 'abandoned', 0)"
        )
        assert not journal.was_extracted("ep", "p")

    def test_was_extracted_does_not_skip_exhausted_failed(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep', 'p', 'failed', ?)",
            [PipelineJournal.MAX_RETRIES],
        )
        assert not journal.was_extracted("ep", "p")

    def test_get_failed_includes_exhausted_when_requested(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal "
            "(endpoint, params, status, retry_count, error_message) "
            "VALUES ('ep', 'p', 'failed', ?, 'err')",
            [PipelineJournal.MAX_RETRIES],
        )
        assert journal.get_failed() == []
        assert journal.get_failed(include_exhausted=True) == [("ep", "p", "err")]

    def test_get_failed_includes_abandoned_when_requested(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal "
            "(endpoint, params, status, retry_count, error_message) "
            "VALUES ('ep', 'p', 'abandoned', ?, 'err')",
            [PipelineJournal.MAX_RETRIES],
        )
        assert journal.get_failed() == []
        assert journal.get_failed(include_abandoned=True) == [("ep", "p", "err")]


class TestJournalMetrics:
    def test_record_metric(self, journal: PipelineJournal) -> None:
        journal.record_metric("ep", duration=1.5, rows=100, errors=0)
        row = journal._conn.execute(
            "SELECT endpoint, duration_seconds, rows_extracted, error_count "
            "FROM _pipeline_metrics WHERE endpoint = 'ep'"
        ).fetchone()
        assert row is not None
        assert row[0] == "ep"
        assert row[1] == pytest.approx(1.5)
        assert row[2] == 100
        assert row[3] == 0


class TestJournalSeasonTypeCounts:
    def test_count_done_by_endpoint_season_type(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", '{"season": "2024-25", "season_type": "Regular Season"}')
        journal.record_success("ep1", '{"season": "2024-25", "season_type": "Regular Season"}', 10)
        journal.record_start("ep1", '{"season": "2024-25", "season_type": "Playoffs"}')
        journal.record_success("ep1", '{"season": "2024-25", "season_type": "Playoffs"}', 10)

        counts = journal.count_done_by_endpoint_season_type()

        assert counts == [
            ("ep1", "2024-25", "Playoffs", 1),
            ("ep1", "2024-25", "Regular Season", 1),
        ]


# ---------------------------------------------------------------------------
# was_extracted_batch
# ---------------------------------------------------------------------------


class TestJournalBatch:
    def test_was_extracted_batch_empty(self, journal: PipelineJournal) -> None:
        assert journal.was_extracted_batch([]) == set()

    def test_was_extracted_batch_with_done(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", "p1")
        journal.record_success("ep1", "p1", 10)
        journal.record_start("ep2", "p2")
        result = journal.was_extracted_batch([("ep1", "p1"), ("ep2", "p2")])
        assert ("ep1", "p1") in result
        assert ("ep2", "p2") not in result

    def test_was_extracted_batch_excludes_abandoned(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep1', 'p1', 'abandoned', 0)"
        )
        result = journal.was_extracted_batch([("ep1", "p1")])
        assert ("ep1", "p1") not in result

    def test_was_extracted_batch_excludes_exhausted(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep1', 'p1', 'failed', ?)",
            [PipelineJournal.MAX_RETRIES],
        )
        result = journal.was_extracted_batch([("ep1", "p1")])
        assert ("ep1", "p1") not in result

    def test_was_extracted_batch_multiple_items(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", "p1")
        journal.record_success("ep1", "p1", 10)
        journal.record_start("ep2", "p2")
        journal.record_success("ep2", "p2", 20)
        journal.record_start("ep3", "p3")
        result = journal.was_extracted_batch(
            [
                ("ep1", "p1"),
                ("ep2", "p2"),
                ("ep3", "p3"),
                ("ep4", "p4"),
            ]
        )
        assert result == {("ep1", "p1"), ("ep2", "p2")}

    def test_was_extracted_batch_large(self, journal: PipelineJournal) -> None:
        """Verify full-scan approach handles >1000 items correctly."""
        done_items = [(f"ep{i}", f"p{i}") for i in range(5)]
        for ep, p in done_items:
            journal.record_start(ep, p)
            journal.record_success(ep, p, 10)

        # Build a query with 1500 items including the 5 done ones
        all_items = [(f"ep{i}", f"p{i}") for i in range(1500)]
        result = journal.was_extracted_batch(all_items)
        assert result == set(done_items)


# ---------------------------------------------------------------------------
# log_summary
# ---------------------------------------------------------------------------


class TestJournalSummary:
    def test_log_summary_empty(self, journal: PipelineJournal) -> None:
        journal.log_summary()  # should not raise

    def test_log_summary_with_done_and_failed(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", "p1")
        journal.record_success("ep1", "p1", 100)
        journal.record_start("ep2", "p2")
        journal.record_failure("ep2", "p2", "timeout")
        journal.log_summary()  # should not raise


# ---------------------------------------------------------------------------
# reset_stale_running
# ---------------------------------------------------------------------------


class TestJournalStaleRunning:
    def test_reset_stale_running(self, journal: PipelineJournal) -> None:
        # Insert an entry with an old started_at timestamp
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, started_at) "
            "VALUES ('ep1', 'p1', 'running', '2020-01-01T00:00:00')"
        )
        journal.reset_stale_running(cutoff_minutes=1)
        # Verify the entry is now failed with stale_running error
        row = journal._conn.execute(
            "SELECT status, error_message FROM _extraction_journal "
            "WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        assert row[0] == "failed"
        assert row[1] == "stale_running"

    def test_reset_stale_running_no_stale(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", "p1")
        # Recently started entry should not be reset
        row_before = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        journal.reset_stale_running(cutoff_minutes=60)
        row_after = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        assert row_after[0] == row_before[0]  # unchanged

    def test_reset_stale_running_does_not_affect_done(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, started_at) "
            "VALUES ('ep1', 'p1', 'done', '2020-01-01T00:00:00')"
        )
        journal.reset_stale_running(cutoff_minutes=1)
        row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        assert row[0] == "done"

    def test_recover_interrupted_running_marks_recent_rows_failed(
        self, journal: PipelineJournal
    ) -> None:
        journal.record_start("ep1", "p1")
        count = journal.recover_interrupted_running()

        row = journal._conn.execute(
            "SELECT status, error_message, completed_at FROM _extraction_journal "
            "WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        assert count == 1
        assert row[0] == "failed"
        assert row[1] == "interrupted_resume"
        assert row[2] is not None

    def test_recover_interrupted_running_does_not_affect_done(
        self, journal: PipelineJournal
    ) -> None:
        journal.record_start("ep1", "p1")
        journal.record_success("ep1", "p1", 10)

        count = journal.recover_interrupted_running()
        row = journal._conn.execute(
            "SELECT status FROM _extraction_journal WHERE endpoint='ep1' AND params='p1'"
        ).fetchone()
        assert count == 0
        assert row[0] == "done"


class TestJournalTableMetadata:
    def test_get_table_metadata_empty(self, journal: PipelineJournal) -> None:
        assert journal.get_table_metadata("agg_player_season") is None

    def test_record_and_get_table_metadata(self, journal: PipelineJournal) -> None:
        schema_hash = schema_hash_for_columns(["player_id", "pts"], ["Int64", "Int64"])
        journal.record_table_metadata("agg_player_season", 1200, schema_hash, quality_score=0.95)
        metadata = journal.get_table_metadata("agg_player_season")
        assert metadata is not None
        assert metadata[0] == 1200
        assert metadata[1] == schema_hash
        assert metadata[2]
        assert metadata[3] == 0.95

    def test_upsert_table_metadata(self, journal: PipelineJournal) -> None:
        journal.record_table_metadata("fact_team_game", 50, "hash_v1")
        journal.record_table_metadata("fact_team_game", 75, "hash_v2")
        metadata = journal.get_table_metadata("fact_team_game")
        assert metadata is not None
        assert metadata[0] == 75
        assert metadata[1] == "hash_v2"
