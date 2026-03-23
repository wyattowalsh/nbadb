from __future__ import annotations

from unittest.mock import patch

import duckdb
import pytest

from nbadb.orchestrate.scanner import (
    DataScanner,
    ScanCategory,
    ScanFinding,
    ScanReport,
    ScanSeverity,
)

# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def conn():
    """In-memory DuckDB with representative tables for scan testing."""
    c = duckdb.connect(":memory:")

    # dim_game — 3 games
    c.execute("""
        CREATE TABLE dim_game (
            game_id VARCHAR NOT NULL,
            game_date DATE,
            season_year VARCHAR,
            home_team_id INTEGER,
            visitor_team_id INTEGER
        )
    """)
    c.execute("""
        INSERT INTO dim_game VALUES
            ('0021400001', '2024-10-22', '2024-25', 1, 2),
            ('0021400002', '2024-10-23', '2024-25', 3, 4),
            ('0021400003', '2024-10-24', '2024-25', 5, 6)
    """)

    # dim_player — 2 players
    c.execute("""
        CREATE TABLE dim_player (
            player_id INTEGER NOT NULL,
            player_name VARCHAR
        )
    """)
    c.execute("INSERT INTO dim_player VALUES (101, 'Player A'), (102, 'Player B')")

    # dim_team — 2 teams
    c.execute("""
        CREATE TABLE dim_team (
            team_id INTEGER NOT NULL,
            team_name VARCHAR
        )
    """)
    c.execute("INSERT INTO dim_team VALUES (1, 'Team A'), (2, 'Team B')")

    yield c
    c.close()


def _stub_transformer(output_table: str, depends_on: list[str] | None = None):
    """Lightweight stub with output_table and depends_on attributes."""

    class _Stub:
        pass

    s = _Stub()
    s.output_table = output_table
    s.depends_on = depends_on or []
    return s


# ── missing table checks ─────────────────────────────────────────


class TestMissingTableChecks:
    def test_missing_staging_table(self, conn):
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=["stg_nonexistent"],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[],
            ),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        errors = report.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].check == "missing_staging_table"
        assert errors[0].table == "stg_nonexistent"

    def test_empty_staging_table(self, conn):
        conn.execute("CREATE TABLE stg_empty_test (id INTEGER)")

        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=["stg_empty_test"],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[],
            ),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        warnings = report.filter(severity=ScanSeverity.WARNING)
        assert len(warnings) == 1
        assert warnings[0].check == "empty_staging_table"

    def test_missing_transform_table(self, conn):
        stub = _stub_transformer("fact_nonexistent", ["stg_foo"])

        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[stub],
            ),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        errors = report.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].check == "missing_transform_table"
        assert errors[0].details["depends_on"] == ["stg_foo"]

    def test_existing_table_no_finding(self, conn):
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[_stub_transformer("dim_game")],
            ),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        assert len(report.findings) == 0


# ── cross-table checks ───────────────────────────────────────────


class TestCrossTableChecks:
    def test_game_coverage_gap(self, conn):
        # fact_game_result covers only 2 of 3 games
        conn.execute("""
            CREATE TABLE fact_game_result (
                game_id VARCHAR, season_year VARCHAR, pts_home INTEGER, pts_away INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_game_result VALUES
                ('0021400001', '2024-25', 110, 100),
                ('0021400002', '2024-25', 105, 95)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        coverage = [f for f in report.findings if f.check == "game_coverage"]
        assert len(coverage) == 1
        assert coverage[0].details["missing"] == 1
        assert coverage[0].table == "fact_game_result"

    def test_game_coverage_no_gap(self, conn):
        conn.execute("""
            CREATE TABLE fact_game_result (
                game_id VARCHAR, season_year VARCHAR, pts_home INTEGER, pts_away INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_game_result VALUES
                ('0021400001', '2024-25', 110, 100),
                ('0021400002', '2024-25', 105, 95),
                ('0021400003', '2024-25', 115, 108)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        coverage = [f for f in report.findings if f.check == "game_coverage"]
        assert len(coverage) == 0

    def test_referential_integrity_orphans(self, conn):
        conn.execute("""
            CREATE TABLE fact_game_result (
                game_id VARCHAR, season_year VARCHAR, pts_home INTEGER, pts_away INTEGER
            )
        """)
        # Insert a game_id that doesn't exist in dim_game
        conn.execute("""
            INSERT INTO fact_game_result VALUES
                ('0021400001', '2024-25', 110, 100),
                ('ORPHAN_GAME', '2024-25', 99, 88)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        ref = [f for f in report.findings if f.check == "referential_integrity"]
        assert len(ref) == 1
        assert ref[0].details["orphans"] == 1

    def test_dynamic_ref_integrity(self, conn):
        # A fact_ table with game_id that has orphan
        conn.execute("""
            CREATE TABLE fact_custom_stats (
                game_id VARCHAR, player_id INTEGER, stat_val FLOAT
            )
        """)
        conn.execute("""
            INSERT INTO fact_custom_stats VALUES
                ('0021400001', 101, 5.0),
                ('MISSING_GAME', 102, 3.0)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        ref = [
            f
            for f in report.findings
            if f.check == "referential_integrity" and f.table == "fact_custom_stats"
        ]
        assert len(ref) == 1
        assert ref[0].details["orphans"] == 1

    def test_no_orphans(self, conn):
        conn.execute("""
            CREATE TABLE fact_player_game_log (
                player_id INTEGER, game_id VARCHAR, pts INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_player_game_log VALUES (101, '0021400001', 20)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        ref = [
            f
            for f in report.findings
            if f.check == "referential_integrity" and f.table == "fact_player_game_log"
        ]
        assert len(ref) == 0


# ── temporal checks ───────────────────────────────────────────────


class TestTemporalChecks:
    def test_low_season_count(self, conn):
        conn.execute("""
            CREATE TABLE fact_standings (
                team_id INTEGER, season_year VARCHAR, wins INTEGER
            )
        """)
        # 3 seasons: two with ~100 rows, one with 5 rows
        for i in range(100):
            conn.execute("INSERT INTO fact_standings VALUES (?, '2022-23', ?)", [i % 30 + 1, i])
        for i in range(100):
            conn.execute("INSERT INTO fact_standings VALUES (?, '2023-24', ?)", [i % 30 + 1, i])
        for i in range(5):
            conn.execute("INSERT INTO fact_standings VALUES (?, '2024-25', ?)", [i % 30 + 1, i])

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.TEMPORAL])

        low = [f for f in report.findings if f.check == "low_season_count"]
        assert len(low) == 1
        assert low[0].details["season"] == "2024-25"

    def test_no_temporal_anomaly(self, conn):
        conn.execute("""
            CREATE TABLE fact_test (season_year VARCHAR, val INTEGER)
        """)
        for i in range(50):
            conn.execute("INSERT INTO fact_test VALUES ('2022-23', ?)", [i])
        for i in range(50):
            conn.execute("INSERT INTO fact_test VALUES ('2023-24', ?)", [i])
        for i in range(50):
            conn.execute("INSERT INTO fact_test VALUES ('2024-25', ?)", [i])

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.TEMPORAL])

        low = [f for f in report.findings if f.check == "low_season_count"]
        assert len(low) == 0

    def test_date_gap_detected(self, conn):
        import datetime

        conn.execute("""
            CREATE TABLE dim_game_with_gap (
                game_id VARCHAR, game_date DATE, season_year VARCHAR
            )
        """)
        # Create dates with a 20-day gap in December (not off-season)
        dates = [
            datetime.date(2024, 12, 1),
            datetime.date(2024, 12, 2),
            datetime.date(2024, 12, 3),
            # 20-day gap
            datetime.date(2024, 12, 23),
            datetime.date(2024, 12, 24),
        ]
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT INTO dim_game_with_gap VALUES (?, ?, '2024-25')",
                [f"G{i}", d],
            )

        # The scanner only checks specific tables for date gaps
        # We need to use dim_game for this check
        conn.execute("DROP TABLE dim_game")
        conn.execute("ALTER TABLE dim_game_with_gap RENAME TO dim_game")

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.TEMPORAL])

        gaps = [f for f in report.findings if f.check == "date_gap"]
        assert len(gaps) == 1
        assert gaps[0].details["gap_days"] == 20

    def test_offseason_gap_filtered(self, conn):
        import datetime

        # Replace dim_game with dates that have a gap starting in July (off-season)
        conn.execute("DELETE FROM dim_game")
        dates = [
            datetime.date(2024, 6, 15),  # June 15 — end of season
            datetime.date(2024, 10, 22),  # Oct 22 — season opener
        ]
        for i, d in enumerate(dates):
            conn.execute(
                "INSERT INTO dim_game VALUES (?, ?, '2024-25', 1, 2)",
                [f"G{i}", d],
            )

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.TEMPORAL])

        gaps = [f for f in report.findings if f.check == "date_gap"]
        # Should be filtered — gap starts in June (month 6)
        assert len(gaps) == 0


# ── data quality checks ──────────────────────────────────────────


class TestDataQualityChecks:
    def test_null_key_column(self, conn):
        conn.execute("""
            CREATE TABLE fact_with_nulls (
                game_id VARCHAR, player_id INTEGER, pts INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_with_nulls VALUES
                ('0021400001', 101, 20),
                (NULL, 102, 15),
                ('0021400003', NULL, 10)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        null_findings = [
            f
            for f in report.findings
            if f.check == "null_key_column" and f.table == "fact_with_nulls"
        ]
        assert len(null_findings) == 2
        columns_with_nulls = {f.details["column"] for f in null_findings}
        assert columns_with_nulls == {"game_id", "player_id"}

    def test_no_nulls(self, conn):
        conn.execute(
            "CREATE TABLE fact_clean ("
            "game_id VARCHAR NOT NULL, player_id INTEGER NOT NULL, pts INTEGER)"
        )
        conn.execute("INSERT INTO fact_clean VALUES ('0021400001', 101, 20)")

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        null_findings = [
            f for f in report.findings if f.check == "null_key_column" and f.table == "fact_clean"
        ]
        assert len(null_findings) == 0

    def test_duplicate_keys(self, conn):
        conn.execute("""
            CREATE TABLE fact_dupes (game_id VARCHAR, player_id INTEGER, pts INTEGER)
        """)
        conn.execute("""
            INSERT INTO fact_dupes VALUES
                ('0021400001', 101, 20),
                ('0021400001', 101, 22),
                ('0021400002', 102, 15)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        dupe_findings = [
            f for f in report.findings if f.check == "duplicate_keys" and f.table == "fact_dupes"
        ]
        assert len(dupe_findings) == 1
        assert dupe_findings[0].details["duplicates"] == 1

    def test_zero_stat_rows(self, conn):
        conn.execute("""
            CREATE TABLE fact_zeros (
                game_id VARCHAR, player_id INTEGER,
                pts INTEGER, reb INTEGER, ast INTEGER, stl INTEGER, blk INTEGER
            )
        """)
        # 10 rows total, 8 all-zero
        for i in range(8):
            conn.execute("INSERT INTO fact_zeros VALUES (?, ?, 0, 0, 0, 0, 0)", [f"G{i}", i])
        conn.execute("INSERT INTO fact_zeros VALUES ('G8', 8, 20, 5, 3, 1, 2)")
        conn.execute("INSERT INTO fact_zeros VALUES ('G9', 9, 15, 3, 2, 0, 1)")

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        zero_findings = [
            f for f in report.findings if f.check == "zero_stat_rows" and f.table == "fact_zeros"
        ]
        assert len(zero_findings) == 1
        assert zero_findings[0].details["zero_rows"] == 8
        assert zero_findings[0].details["pct"] == 80.0

    def test_staging_tables_skipped(self, conn):
        conn.execute("""
            CREATE TABLE stg_dirty (game_id VARCHAR, val INTEGER)
        """)
        conn.execute("INSERT INTO stg_dirty VALUES (NULL, 1)")

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        stg_findings = [f for f in report.findings if f.table == "stg_dirty"]
        assert len(stg_findings) == 0


# ── filtering ────────────────────────────────────────────────────


class TestScanFiltering:
    def test_category_filter(self, conn):
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=["stg_nonexistent"],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[],
            ),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        # Should only have missing_table findings, not cross_table or temporal
        categories = {f.category for f in report.findings}
        assert categories <= {ScanCategory.MISSING_TABLE}

    def test_table_filter(self, conn):
        conn.execute("""
            CREATE TABLE fact_game_result (
                game_id VARCHAR, season_year VARCHAR, pts_home INTEGER, pts_away INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_game_result VALUES ('0021400001', '2024-25', 110, 100)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(table_filter="dim_")

        # All findings should be about tables starting with dim_
        for f in report.findings:
            assert f.table.startswith("dim_"), f"Unexpected table in finding: {f.table}"

    def test_report_serialization(self, conn):
        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.DATA_QUALITY])

        data = report.to_dict()
        assert "summary" in data
        assert "findings" in data
        assert "duration_seconds" in data
        # Ensure JSON-serializable
        import json

        json.dumps(data, default=str)

    def test_report_summary(self, conn):
        report = ScanReport()
        summary = report.summary()
        assert summary["total"] == 0
        assert summary["error"] == 0
        assert summary["warning"] == 0
        assert summary["info"] == 0

    def test_scan_repeated_calls_independent(self, conn):
        """Calling scan() twice on the same scanner produces independent reports."""
        conn.execute("""
            CREATE TABLE fact_with_nulls (
                game_id VARCHAR, player_id INTEGER, pts INTEGER
            )
        """)
        conn.execute("INSERT INTO fact_with_nulls VALUES (NULL, 101, 20)")

        scanner = DataScanner(conn)

        report1 = scanner.scan(categories=[ScanCategory.DATA_QUALITY])
        findings1 = len(report1.findings)
        checks1 = report1.checks_run
        assert findings1 > 0

        report2 = scanner.scan(categories=[ScanCategory.DATA_QUALITY])
        assert len(report2.findings) == findings1
        assert report2.checks_run == checks1
        # Reports should be distinct objects
        assert report1 is not report2


# ── to_markdown ─────────────────────────────────────────────


class TestToMarkdown:
    def test_empty_report(self):
        report = ScanReport(checks_run=5, tables_scanned=3, duration_seconds=0.5)
        md = report.to_markdown()
        assert "Data Scan Report" in md
        assert "All clear" in md
        assert "No issues found" in md

    def test_with_findings(self):
        report = ScanReport(
            findings=[
                ScanFinding(
                    category="data_quality",
                    severity="error",
                    table="fact_test",
                    check="null_key_column",
                    message="fact_test.game_id: 5/100 nulls",
                ),
                ScanFinding(
                    category="cross_table",
                    severity="warning",
                    table="fact_box",
                    check="game_coverage",
                    message="fact_box: 10 games missing",
                ),
            ],
            checks_run=10,
            tables_scanned=5,
            duration_seconds=1.2,
        )
        md = report.to_markdown()
        assert "Data Scan Report" in md
        assert "1 error(s)" in md
        assert "Data Quality" in md
        assert "Cross-Table Gaps" in md
        assert "`fact_test`" in md
        assert "`fact_box`" in md

    def test_truncation(self):
        """More than MAX findings per category are truncated."""
        findings = [
            ScanFinding(
                category="data_quality",
                severity="warning",
                table=f"fact_{i}",
                check="duplicate_keys",
                message=f"fact_{i}: duplicates",
            )
            for i in range(100)
        ]
        report = ScanReport(
            findings=findings,
            checks_run=100,
            tables_scanned=100,
            duration_seconds=2.0,
        )
        md = report.to_markdown()
        assert "and 50 more" in md

    def test_pipe_in_message_escaped(self):
        report = ScanReport(
            findings=[
                ScanFinding(
                    category="data_quality",
                    severity="info",
                    table="fact_test",
                    check="zero_stat_rows",
                    message="fact_test: 10|20 rows",
                ),
            ],
            checks_run=1,
            tables_scanned=1,
            duration_seconds=0.1,
        )
        md = report.to_markdown()
        # Pipe should be escaped to not break markdown table
        assert "10\\|20" in md


# ── to_github_annotations ──────────────────────────────────


class TestToGithubAnnotations:
    def test_errors_and_warnings(self):
        report = ScanReport(
            findings=[
                ScanFinding(
                    category="data_quality",
                    severity="error",
                    table="t",
                    check="c",
                    message="err msg",
                ),
                ScanFinding(
                    category="data_quality",
                    severity="warning",
                    table="t",
                    check="c",
                    message="warn msg",
                ),
                ScanFinding(
                    category="data_quality",
                    severity="info",
                    table="t",
                    check="c",
                    message="info msg",
                ),
            ]
        )
        annotations = report.to_github_annotations()
        assert len(annotations) == 2
        assert annotations[0] == "::error::err msg"
        assert annotations[1] == "::warning::warn msg"

    def test_empty_report_no_annotations(self):
        report = ScanReport()
        assert report.to_github_annotations() == []
