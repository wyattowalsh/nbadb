from __future__ import annotations

import json
from unittest.mock import patch

import duckdb
import pytest

from nbadb.orchestrate.scanner import (
    DataScanner,
    ScanCategory,
    ScanFinding,
    ScanReport,
    ScanSeverity,
    validate_full_publication_checkpoint_report,
)

_VALIDATOR = "nbadb.orchestrate.transformers.require_complete_transformer_universe"


def test_full_publication_checkpoint_report_requires_accounted_lane_inventory(
    tmp_path,
) -> None:
    report_path = tmp_path / "checkpoint-report.json"
    lane_id = "reference-static"
    report = {
        "source_sha": "a" * 40,
        "run_id": "12345",
        "included_run_ids": ["12345"],
        "included_lane_ids": [lane_id],
        "included_lane_coverage_hashes": {lane_id: "b" * 64},
        "coverage_fingerprint": "c" * 64,
        "database_sha256": "d" * 64,
        "manifest_lane_count": 1,
        "complete_lane_count": 1,
        "contract_blocked_lane_count": 0,
        "active_lane_count": 0,
        "skipped_lane_count": 0,
        "missing_lane_ids": [],
        "skipped_complete_lane_ids": [],
        "current_lane_attestation_failures": {},
        "workload_contract_errors": [],
        "table_row_counts": {},
        "journal_row_count": 0,
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    verified = {
        field_name: report[field_name]
        for field_name in (
            "run_id",
            "coverage_fingerprint",
            "database_sha256",
            "included_lane_ids",
            "included_run_ids",
            "included_lane_coverage_hashes",
            "contract_blocked_lane_count",
        )
    }

    with (
        patch(
            "nbadb.orchestrate.full_extraction_control.validate_checkpoint_artifact",
            return_value=verified,
        ) as canonical_verifier,
        patch(
            "nbadb.orchestrate.full_extraction_control._single_database_path",
            return_value=tmp_path / "checkpoint" / "nba.duckdb",
        ),
        patch(
            "nbadb.orchestrate.full_extraction_control._database_row_counts",
            return_value=({}, 0),
        ),
    ):
        assert (
            validate_full_publication_checkpoint_report(
                report_path,
                manifest_path=tmp_path / "manifest.json",
                checkpoint_dir=tmp_path / "checkpoint",
                chain_id="chain-1",
                source_sha="a" * 40,
            )["terminal_ready"]
            is True
        )
    canonical_verifier.assert_called_once_with(
        manifest_path=tmp_path / "manifest.json",
        checkpoint_dir=tmp_path / "checkpoint",
        checkpoint_report_path=report_path,
        chain_id="chain-1",
        source_sha="a" * 40,
        pointer_prefix="latest",
    )

    report["manifest_lane_count"] = 2
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="account for every manifest lane"):
        validate_full_publication_checkpoint_report(
            report_path,
            manifest_path=tmp_path / "manifest.json",
            checkpoint_dir=tmp_path / "checkpoint",
            chain_id="chain-1",
            source_sha="a" * 40,
        )

    report["manifest_lane_count"] = 1
    report["table_row_counts"] = {"stg_fixture": 1}
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    with (
        patch(
            "nbadb.orchestrate.full_extraction_control.validate_checkpoint_artifact",
            return_value=verified,
        ),
        patch(
            "nbadb.orchestrate.full_extraction_control._single_database_path",
            return_value=tmp_path / "checkpoint" / "nba.duckdb",
        ),
        patch(
            "nbadb.orchestrate.full_extraction_control._database_row_counts",
            return_value=({"stg_fixture": 2}, 0),
        ),
        pytest.raises(ValueError, match="staging row inventory differs"),
    ):
        validate_full_publication_checkpoint_report(
            report_path,
            manifest_path=tmp_path / "manifest.json",
            checkpoint_dir=tmp_path / "checkpoint",
            chain_id="chain-1",
            source_sha="a" * 40,
        )


def test_full_publication_checkpoint_report_rejects_canonical_mismatch(tmp_path) -> None:
    report_path = tmp_path / "checkpoint-report.json"
    report = {
        "source_sha": "a" * 40,
        "run_id": "12345",
        "included_run_ids": ["12345"],
        "included_lane_ids": ["reference-static"],
        "included_lane_coverage_hashes": {"reference-static": "b" * 64},
        "coverage_fingerprint": "c" * 64,
        "database_sha256": "d" * 64,
        "manifest_lane_count": 1,
        "complete_lane_count": 1,
        "contract_blocked_lane_count": 0,
        "active_lane_count": 0,
        "skipped_lane_count": 0,
        "missing_lane_ids": [],
        "skipped_complete_lane_ids": [],
        "current_lane_attestation_failures": {},
        "workload_contract_errors": [],
        "table_row_counts": {},
        "journal_row_count": 0,
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")
    verified = {
        "run_id": "12345",
        "included_run_ids": ["12345"],
        "included_lane_ids": ["different-lane"],
        "included_lane_coverage_hashes": {"different-lane": "e" * 64},
        "coverage_fingerprint": "c" * 64,
        "database_sha256": "d" * 64,
        "contract_blocked_lane_count": 0,
    }

    with (
        patch(
            "nbadb.orchestrate.full_extraction_control.validate_checkpoint_artifact",
            return_value=verified,
        ),
        pytest.raises(ValueError, match="differs from canonical verification"),
    ):
        validate_full_publication_checkpoint_report(
            report_path,
            manifest_path=tmp_path / "manifest.json",
            checkpoint_dir=tmp_path / "checkpoint",
            chain_id="chain-1",
            source_sha="a" * 40,
        )


def test_full_publication_checkpoint_report_rejects_unexpected_source_sha(tmp_path) -> None:
    report_path = tmp_path / "checkpoint-report.json"
    report = {
        "source_sha": "a" * 40,
        "run_id": "12345",
        "included_run_ids": ["12345"],
        "included_lane_ids": ["reference-static"],
        "included_lane_coverage_hashes": {"reference-static": "b" * 64},
        "coverage_fingerprint": "c" * 64,
        "database_sha256": "d" * 64,
        "manifest_lane_count": 1,
        "complete_lane_count": 1,
        "contract_blocked_lane_count": 0,
        "active_lane_count": 0,
        "skipped_lane_count": 0,
        "missing_lane_ids": [],
        "skipped_complete_lane_ids": [],
        "current_lane_attestation_failures": {},
        "workload_contract_errors": [],
        "table_row_counts": {},
        "journal_row_count": 0,
        "terminal_ready": True,
    }
    report_path.write_text(json.dumps(report) + "\n", encoding="utf-8")

    with pytest.raises(ValueError, match="does not match the expected source commit"):
        validate_full_publication_checkpoint_report(
            report_path,
            manifest_path=tmp_path / "manifest.json",
            checkpoint_dir=tmp_path / "checkpoint",
            chain_id="chain-1",
            source_sha="f" * 40,
        )


# ── fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def conn(duckdb_memory_conn: duckdb.DuckDBPyConnection):
    """In-memory DuckDB with representative tables for scan testing.

    Extends canonical duckdb_memory_conn with dim_game, dim_player, dim_team.
    """
    # dim_game — 3 games
    duckdb_memory_conn.execute("""
        CREATE TABLE dim_game (
            game_id VARCHAR NOT NULL,
            game_date DATE,
            season_year VARCHAR,
            home_team_id INTEGER,
            visitor_team_id INTEGER
        )
    """)
    duckdb_memory_conn.execute("""
        INSERT INTO dim_game VALUES
            ('0021400001', '2024-10-22', '2024-25', 1, 2),
            ('0021400002', '2024-10-23', '2024-25', 3, 4),
            ('0021400003', '2024-10-24', '2024-25', 5, 6)
    """)

    # dim_player — 2 players
    duckdb_memory_conn.execute("""
        CREATE TABLE dim_player (
            player_id INTEGER NOT NULL,
            player_name VARCHAR
        )
    """)
    duckdb_memory_conn.execute("INSERT INTO dim_player VALUES (101, 'Player A'), (102, 'Player B')")

    # dim_team — 2 teams
    duckdb_memory_conn.execute("""
        CREATE TABLE dim_team (
            team_id INTEGER NOT NULL,
            team_name VARCHAR
        )
    """)
    duckdb_memory_conn.execute("INSERT INTO dim_team VALUES (1, 'Team A'), (2, 'Team B')")

    return duckdb_memory_conn


def _stub_transformer(output_table: str, depends_on: list[str] | None = None):
    """Lightweight stub with output_table and depends_on attributes."""

    class _Stub:
        pass

    s = _Stub()
    s.output_table = output_table
    s.depends_on = depends_on or []
    return s


class _FailingSchemaIntrospectionConnection:
    def __init__(self, conn: duckdb.DuckDBPyConnection) -> None:
        self._conn = conn

    def execute(self, query, *args, **kwargs):
        if "information_schema.columns" in query:
            raise duckdb.CatalogException("synthetic schema introspection failure")
        return self._conn.execute(query, *args, **kwargs)


class _FailingAnchorCountConnection:
    def __init__(self, conn: duckdb.DuckDBPyConnection, table: str) -> None:
        self._conn = conn
        self._query = f'SELECT COUNT(*) FROM "{table}"'

    def execute(self, query, *args, **kwargs):
        if query == self._query:
            raise duckdb.CatalogException("synthetic publication anchor count failure")
        return self._conn.execute(query, *args, **kwargs)


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
            patch(_VALIDATOR),
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
            patch(_VALIDATOR),
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
            patch(_VALIDATOR),
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
            patch(_VALIDATOR),
        ):
            scanner = DataScanner(conn)
            report = scanner.scan(categories=[ScanCategory.MISSING_TABLE])

        assert len(report.findings) == 0

    @pytest.mark.parametrize("category", [ScanCategory.MISSING_TABLE, ScanCategory.CROSS_TABLE])
    @pytest.mark.parametrize("outputs", [[], ["dim_game"]])
    def test_zero_or_partial_transformer_discovery_is_an_error(self, conn, outputs, category):
        transformers = [_stub_transformer(output) for output in outputs]
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=transformers,
            ),
        ):
            report = DataScanner(conn).scan(categories=[category])

        errors = report.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].check == "transformer_discovery_failed"
        assert errors[0].details == {
            "error_type": "TransformerDiscoveryError",
            "required_contract": "exact_schema_backed_output_universe",
        }

    def test_transformer_discovery_exception_is_an_error_finding(self, conn):
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                side_effect=RuntimeError("synthetic import failure"),
            ),
        ):
            report = DataScanner(conn).scan(categories=[ScanCategory.MISSING_TABLE])

        errors = report.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].check == "transformer_discovery_failed"
        assert "synthetic import failure" in errors[0].message

    def test_empty_transform_reports_nonempty_policy_limitation(self, conn):
        conn.execute("CREATE TABLE fact_optional (id INTEGER)")
        transformer = _stub_transformer("fact_optional", ["stg_optional"])
        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[transformer],
            ),
            patch(_VALIDATOR),
        ):
            report = DataScanner(conn).scan(categories=[ScanCategory.MISSING_TABLE])

        warning = report.filter(severity=ScanSeverity.WARNING)[0]
        assert warning.check == "empty_transform_table"
        assert "no unconditional nonempty contract" in warning.message
        assert warning.details["hard_nonempty_policy"] == "not_established"
        assert "No repo-backed unconditional" in warning.details["policy_limitation"]

    def test_full_publication_all_anchor_tables_empty_are_errors(self, conn):
        conn.execute("DELETE FROM dim_game")
        conn.execute("DELETE FROM dim_player")
        conn.execute("DELETE FROM dim_team")
        conn.execute("CREATE TABLE fact_optional (id INTEGER)")
        transformers = [
            _stub_transformer("dim_game"),
            _stub_transformer("dim_player"),
            _stub_transformer("dim_team"),
            _stub_transformer("fact_optional"),
        ]

        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=transformers,
            ),
            patch(_VALIDATOR),
        ):
            report = DataScanner(conn).scan(
                categories=[ScanCategory.MISSING_TABLE],
                full_publication=True,
            )

        anchor_errors = [
            finding
            for finding in report.filter(severity=ScanSeverity.ERROR)
            if finding.check == "empty_publication_anchor"
        ]
        assert len(anchor_errors) == 3
        assert {finding.table for finding in anchor_errors} == {
            "dim_game",
            "dim_player",
            "dim_team",
        }
        assert all(
            finding.details["hard_nonempty_policy"] == "full_publication_anchor"
            for finding in anchor_errors
        )
        optional = report.filter(table="fact_optional")
        assert len(optional) == 1
        assert optional[0].severity == ScanSeverity.WARNING
        assert optional[0].check == "empty_transform_table"

    def test_full_publication_anchor_check_ignores_category_selection(self, conn):
        conn.execute("DROP TABLE dim_game")

        report = DataScanner(conn).scan(
            categories=[ScanCategory.DATA_QUALITY],
            full_publication=True,
        )

        errors = report.filter(severity=ScanSeverity.ERROR, table="dim_game")
        assert len(errors) == 1
        assert errors[0].check == "missing_publication_anchor"

    def test_full_publication_anchor_check_ignores_fact_table_filter(self, conn):
        conn.execute("DELETE FROM dim_player")
        transformers = [
            _stub_transformer("dim_game"),
            _stub_transformer("dim_player"),
            _stub_transformer("dim_team"),
            _stub_transformer("fact_optional"),
        ]

        with (
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=[],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=transformers,
            ),
            patch(_VALIDATOR),
        ):
            report = DataScanner(conn).scan(
                categories=[ScanCategory.MISSING_TABLE],
                table_filter="fact_",
                full_publication=True,
            )

        errors = report.filter(severity=ScanSeverity.ERROR, table="dim_player")
        assert len(errors) == 1
        assert errors[0].check == "empty_publication_anchor"

    def test_full_publication_anchor_count_failure_is_a_hard_finding(self, conn):
        failing_conn = _FailingAnchorCountConnection(conn, "dim_team")

        report = DataScanner(failing_conn).scan(
            categories=[ScanCategory.DATA_QUALITY],
            table_filter="fact_",
            full_publication=True,
        )

        errors = report.filter(severity=ScanSeverity.ERROR, table="dim_team")
        assert len(errors) == 1
        assert errors[0].check == "publication_anchor_nonempty_query_failed"
        assert errors[0].details == {
            "failed_check": "publication_anchor_nonempty",
            "error_type": "CatalogException",
        }

    def test_full_publication_domain_requires_every_anchor(self, conn):
        conn.execute("CREATE TABLE stg_play_by_play (id INTEGER)")
        conn.execute("CREATE TABLE stg_play_by_play_v2 (id INTEGER)")
        conn.execute("INSERT INTO stg_play_by_play VALUES (1)")
        conn.execute("INSERT INTO stg_play_by_play_v2 VALUES (1)")
        domain_anchors = {"representative": frozenset({"stg_play_by_play", "stg_play_by_play_v2"})}

        with (
            patch.object(DataScanner, "_FULL_PUBLICATION_ANCHORS", frozenset()),
            patch.object(DataScanner, "_FULL_PUBLICATION_DOMAIN_ANCHORS", domain_anchors),
            patch(
                "nbadb.orchestrate.staging_map.get_all_staging_keys",
                return_value=["stg_play_by_play", "stg_play_by_play_v2"],
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[],
            ),
            patch(_VALIDATOR),
        ):
            populated = DataScanner(conn).scan(
                categories=[ScanCategory.DATA_QUALITY],
                full_publication=True,
            )
            assert not [
                finding
                for finding in populated.findings
                if finding.check in {"missing_publication_domain", "empty_publication_domain"}
            ]

            conn.execute("DELETE FROM stg_play_by_play_v2")
            empty = DataScanner(conn).scan(
                categories=[ScanCategory.DATA_QUALITY],
                full_publication=True,
            )

        errors = empty.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].table == "publication_domain:representative"
        assert errors[0].check == "empty_publication_domain"
        assert errors[0].details["row_counts"] == {
            "stg_play_by_play": 1,
            "stg_play_by_play_v2": 0,
        }
        assert errors[0].details["empty_tables"] == ["stg_play_by_play_v2"]

    def test_full_publication_cardinality_mismatch_is_an_error(self, conn):
        conn.execute("CREATE TABLE stg_cardinality (id INTEGER)")
        conn.execute("CREATE TABLE fact_cardinality (id INTEGER)")
        conn.execute("INSERT INTO stg_cardinality VALUES (1), (2)")
        conn.execute("INSERT INTO fact_cardinality VALUES (1)")

        with (
            patch.object(DataScanner, "_FULL_PUBLICATION_ANCHORS", frozenset()),
            patch.object(DataScanner, "_FULL_PUBLICATION_DOMAIN_ANCHORS", {}),
            patch.object(
                DataScanner,
                "_FULL_PUBLICATION_CARDINALITY_PAIRS",
                (("stg_cardinality", "fact_cardinality"),),
            ),
            patch(
                "nbadb.orchestrate.transformers.discover_all_transformers",
                return_value=[],
            ),
            patch(_VALIDATOR),
        ):
            report = DataScanner(conn).scan(
                categories=[ScanCategory.DATA_QUALITY],
                full_publication=True,
            )

        errors = report.filter(severity=ScanSeverity.ERROR)
        assert len(errors) == 1
        assert errors[0].check == "publication_cardinality_mismatch"
        assert errors[0].details["source_row_count"] == 2
        assert errors[0].details["output_row_count"] == 1


# ── cross-table checks ───────────────────────────────────────────


class TestCrossTableChecks:
    def test_game_coverage_tables_are_schema_backed_outputs(self):
        from nbadb.orchestrate.transformers import expected_transform_output_tables

        outputs = expected_transform_output_tables(include_live=True)
        assert set(DataScanner._GAME_COVERAGE_TABLES) <= outputs
        assert "fact_box_score_team" in DataScanner._GAME_COVERAGE_TABLES
        assert "fact_box_score_traditional" not in DataScanner._GAME_COVERAGE_TABLES

    def test_malformed_game_coverage_schema_is_an_error_finding(self, conn):
        conn.execute("CREATE TABLE fact_box_score_team (team_id INTEGER)")

        report = DataScanner(conn).scan(categories=[ScanCategory.CROSS_TABLE])

        errors = [
            finding
            for finding in report.filter(severity=ScanSeverity.ERROR)
            if finding.table == "fact_box_score_team"
        ]
        assert len(errors) == 1
        assert errors[0].check == "game_coverage_query_failed"
        assert errors[0].details["failed_check"] == "game_coverage"
        assert errors[0].details["error_type"] == "BinderException"

    @pytest.mark.parametrize(
        "category",
        [
            ScanCategory.CROSS_TABLE,
            ScanCategory.TEMPORAL,
            ScanCategory.DATA_QUALITY,
        ],
    )
    def test_schema_introspection_failure_is_a_hard_finding_for_each_category(
        self,
        conn,
        category,
    ):
        table = "fact_introspection_target"
        conn.execute(f"CREATE TABLE {table} (game_id VARCHAR, value INTEGER)")
        failing_conn = _FailingSchemaIntrospectionConnection(conn)

        scanner = DataScanner(failing_conn)
        report = scanner.scan(categories=[category], table_filter=table)

        errors = report.filter(severity=ScanSeverity.ERROR, table=table)
        assert len(errors) == 1
        assert errors[0].category == category
        assert errors[0].check == "schema_introspection_query_failed"
        assert errors[0].details == {
            "failed_check": "schema_introspection",
            "error_type": "CatalogException",
        }
        assert table not in scanner._columns_cache

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

    def test_game_coverage_detects_set_gap_when_distinct_counts_match(self, conn):
        conn.execute("""
            CREATE TABLE fact_game_result (
                game_id VARCHAR, season_year VARCHAR, pts_home INTEGER, pts_away INTEGER
            )
        """)
        conn.execute("""
            INSERT INTO fact_game_result VALUES
                ('0021400001', '2024-25', 110, 100),
                ('0021400002', '2024-25', 105, 95),
                ('ORPHAN_GAME', '2024-25', 115, 108)
        """)

        scanner = DataScanner(conn)
        report = scanner.scan(categories=[ScanCategory.CROSS_TABLE])

        coverage = [f for f in report.findings if f.check == "game_coverage"]
        assert len(coverage) == 1
        assert coverage[0].details["dim_game_count"] == 3
        assert coverage[0].details["fact_game_count"] == 3
        assert coverage[0].details["missing"] == 1

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
            patch(_VALIDATOR),
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

    def test_warning_report_is_not_labeled_all_clear(self):
        report = ScanReport(
            findings=[
                ScanFinding(
                    category="missing_table",
                    severity="warning",
                    table="fact_optional",
                    check="empty_transform_table",
                    message="fact_optional is empty",
                )
            ]
        )

        md = report.to_markdown()

        assert "1 warning(s)" in md
        assert "All clear" not in md

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
    def test_errors_warnings_and_notices(self):
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
        assert len(annotations) == 3
        assert annotations[0] == "::error::err msg"
        assert annotations[1] == "::warning::warn msg"
        assert annotations[2] == "::notice::info msg"

    def test_empty_report_no_annotations(self):
        report = ScanReport()
        assert report.to_github_annotations() == []

    def test_annotations_capped_at_max(self):
        """More than _MAX_ANNOTATIONS findings are truncated with a summary notice."""
        findings = [
            ScanFinding(
                category="data_quality",
                severity="warning",
                table=f"t_{i}",
                check="c",
                message=f"msg {i}",
            )
            for i in range(80)
        ]
        report = ScanReport(findings=findings)
        annotations = report.to_github_annotations()
        # 50 kept + 1 summary notice = 51
        assert len(annotations) == 51
        assert "30 more findings" in annotations[-1]
        assert "::notice::" in annotations[-1]
