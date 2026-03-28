from __future__ import annotations

import duckdb
import pytest

from nbadb.orchestrate.journal import PipelineJournal


@pytest.fixture
def journal() -> PipelineJournal:
    """Create an in-memory DuckDB with pipeline tables."""
    conn = duckdb.connect(":memory:")
    # Create the same tables as DBManager._create_pipeline_tables()
    conn.execute("""
        CREATE TABLE _pipeline_watermarks (
            table_name VARCHAR NOT NULL,
            watermark_type VARCHAR NOT NULL,
            watermark_value VARCHAR,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count_at_watermark BIGINT,
            PRIMARY KEY (table_name, watermark_type)
        )
    """)
    conn.execute("""
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
    """)
    conn.execute("""
        CREATE TABLE _pipeline_metrics (
            endpoint VARCHAR NOT NULL,
            run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            duration_seconds FLOAT,
            rows_extracted BIGINT,
            error_count INT DEFAULT 0,
            PRIMARY KEY (endpoint, run_timestamp)
        )
    """)
    yield PipelineJournal(conn)
    conn.close()


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
        """Verify was_extracted returns True only for 'done' status."""
        journal.record_start("ep", "p")
        assert not journal.was_extracted("ep", "p")  # running
        journal.record_success("ep", "p", 5)
        assert journal.was_extracted("ep", "p")  # done

    def test_has_done_entries(self, journal: PipelineJournal) -> None:
        assert not journal.has_done_entries()
        journal.record_start("ep", "p")
        assert not journal.has_done_entries()
        journal.record_success("ep", "p", 5)
        assert journal.has_done_entries()


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
        assert journal.was_extracted("ep", "p")

    def test_was_extracted_skips_abandoned(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep', 'p', 'abandoned', 0)"
        )
        assert journal.was_extracted("ep", "p")

    def test_was_extracted_skips_exhausted_failed(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep', 'p', 'failed', ?)",
            [PipelineJournal.MAX_RETRIES],
        )
        assert journal.was_extracted("ep", "p")


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

    def test_was_extracted_batch_includes_abandoned(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep1', 'p1', 'abandoned', 0)"
        )
        result = journal.was_extracted_batch([("ep1", "p1")])
        assert ("ep1", "p1") in result

    def test_was_extracted_batch_includes_exhausted(self, journal: PipelineJournal) -> None:
        journal._conn.execute(
            "INSERT INTO _extraction_journal (endpoint, params, status, retry_count) "
            "VALUES ('ep1', 'p1', 'failed', ?)",
            [PipelineJournal.MAX_RETRIES],
        )
        result = journal.was_extracted_batch([("ep1", "p1")])
        assert ("ep1", "p1") in result

    def test_was_extracted_batch_multiple_items(self, journal: PipelineJournal) -> None:
        journal.record_start("ep1", "p1")
        journal.record_success("ep1", "p1", 10)
        journal.record_start("ep2", "p2")
        journal.record_success("ep2", "p2", 20)
        journal.record_start("ep3", "p3")
        result = journal.was_extracted_batch([
            ("ep1", "p1"),
            ("ep2", "p2"),
            ("ep3", "p3"),
            ("ep4", "p4"),
        ])
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
