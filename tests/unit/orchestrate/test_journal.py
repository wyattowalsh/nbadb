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
