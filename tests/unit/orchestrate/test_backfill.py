from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from nbadb.orchestrate.backfill import BackfillPlanner
from nbadb.orchestrate.journal import PipelineJournal
from nbadb.orchestrate.workload_contract import PlayerTeamSeasonWorkloadStore

if TYPE_CHECKING:
    import duckdb

_ALL_SEASON_TYPES = ("Regular Season", "Playoffs", "Pre Season", "All Star")

# ── fixtures ─────────────────────────────────────────────────────


@pytest.fixture
def conn(
    duckdb_memory_with_pipeline_tables: duckdb.DuckDBPyConnection,
) -> duckdb.DuckDBPyConnection:
    """Alias for canonical duckdb_memory_with_pipeline_tables fixture."""
    return duckdb_memory_with_pipeline_tables


@pytest.fixture
def journal(conn: duckdb.DuckDBPyConnection) -> PipelineJournal:
    return PipelineJournal(conn)


@pytest.fixture
def planner(
    conn: duckdb.DuckDBPyConnection,
    journal: PipelineJournal,
) -> BackfillPlanner:
    return BackfillPlanner(conn, journal)


def _seed_done(journal: PipelineJournal, endpoint: str, params: dict) -> None:
    """Helper to seed a done journal entry."""
    params_json = json.dumps(params, sort_keys=True)
    journal.record_start(endpoint, params_json)
    journal.record_success(endpoint, params_json, rows=10)


def _seed_failed(journal: PipelineJournal, endpoint: str, params: dict) -> None:
    """Helper to seed a failed journal entry."""
    params_json = json.dumps(params, sort_keys=True)
    journal.record_start(endpoint, params_json)
    journal.record_failure(endpoint, params_json, "test_error")


# ── journal selective operations ─────────────────────────────────


class TestJournalResetEntries:
    def test_reset_by_endpoint(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        count = journal.reset_entries(endpoint="ep1")
        assert count == 1

        # ep1 should now be retryable
        assert not journal.was_extracted("ep1", json.dumps({"season": "2024-25"}, sort_keys=True))
        # ep2 should still be done
        assert journal.was_extracted("ep2", json.dumps({"season": "2024-25"}, sort_keys=True))

    def test_reset_by_status(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_failed(journal, "ep2", {"season": "2024-25"})

        count = journal.reset_entries(status_filter="done")
        assert count == 1

    def test_reset_by_season(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})

        count = journal.reset_entries(season_like="2024-25")
        assert count == 1

    def test_reset_combined_filters(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        count = journal.reset_entries(endpoint="ep1", season_like="2024-25")
        assert count == 1

    def test_reset_requires_filter(self, journal: PipelineJournal) -> None:
        with pytest.raises(ValueError, match="at least one filter"):
            journal.reset_entries()


class TestJournalClearEntries:
    def test_clear_by_endpoint(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        count = journal.clear_entries(endpoint="ep1")
        assert count == 1

    def test_clear_by_status(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_failed(journal, "ep2", {"season": "2024-25"})

        count = journal.clear_entries(status_filter="failed")
        assert count == 1

    def test_clear_requires_filter(self, journal: PipelineJournal) -> None:
        with pytest.raises(ValueError, match="at least one filter"):
            journal.clear_entries()


class TestJournalCounts:
    def test_count_by_endpoint_and_status(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})
        _seed_failed(journal, "ep2", {"season": "2024-25"})

        counts = journal.count_by_endpoint_and_status()
        assert len(counts) == 2

        ep1_done = [c for c in counts if c[0] == "ep1" and c[1] == "done"]
        assert len(ep1_done) == 1
        assert ep1_done[0][2] == 2

    def test_count_done_by_endpoint_and_season(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        counts = journal.count_done_by_endpoint_and_season()
        assert len(counts) == 3

        ep1_2024 = [c for c in counts if c[0] == "ep1" and c[1] == "2024-25"]
        assert len(ep1_2024) == 1
        assert ep1_2024[0][2] == 1

    def test_count_done_by_endpoint_season_type(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25", "season_type": "Regular Season"})
        _seed_done(journal, "ep1", {"season": "2024-25", "season_type": "Playoffs"})

        counts = journal.count_done_by_endpoint_season_type()

        assert counts == [
            ("ep1", "2024-25", "Playoffs", 1),
            ("ep1", "2024-25", "Regular Season", 1),
        ]

    def test_count_done_no_season(self, journal: PipelineJournal) -> None:
        """Entries without season param should have None as season."""
        _seed_done(journal, "ep1", {"game_id": "001"})

        counts = journal.count_done_by_endpoint_and_season()
        assert len(counts) == 1
        assert counts[0][1] is None  # no season in params


# ── BackfillPlanner gap detection ────────────────────────────────


class TestBackfillPlannerGaps:
    def test_static_gap(self, planner: BackfillPlanner) -> None:
        """Static endpoints with no done entries should report as gap."""
        report = planner.detect_gaps(
            endpoints=["franchise_history"],
            patterns=["static"],
        )
        static_gaps = [g for g in report.gaps if g.pattern == "static"]
        assert len(static_gaps) >= 1
        assert static_gaps[0].expected == 1
        assert static_gaps[0].actual == 0
        assert static_gaps[0].missing == 1

    def test_season_gap_detected(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        """Season endpoints missing for specific seasons should be detected."""
        # Seed one season as done
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )

        report = planner.detect_gaps(
            endpoints=["league_game_log"],
            patterns=["season"],
            seasons=["2024-25"],
        )
        # The strict historical contract now expects every declared season type.
        league_gaps = [g for g in report.gaps if g.endpoint == "league_game_log"]
        assert len(league_gaps) == 1
        assert league_gaps[0].expected == 5
        assert league_gaps[0].actual == 1
        assert league_gaps[0].missing == 4

    def test_no_gap_when_complete(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        """No gap should be reported when all expected extractions are done."""
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Playoffs"},
        )
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Pre Season"},
        )
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "PlayIn"},
        )
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "All Star"},
        )

        report = planner.detect_gaps(
            endpoints=["league_game_log"],
            patterns=["season"],
            seasons=["2024-25"],
        )
        league_gaps = [g for g in report.gaps if g.endpoint == "league_game_log"]
        assert len(league_gaps) == 0

    def test_season_gap_respects_requested_season_types(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )

        report = planner.detect_gaps(
            endpoints=["league_game_log"],
            patterns=["season"],
            seasons=["2024-25"],
            season_types=["Playoffs"],
        )

        league_gaps = [g for g in report.gaps if g.endpoint == "league_game_log"]
        assert len(league_gaps) == 1
        assert league_gaps[0].expected == 1
        assert league_gaps[0].actual == 0
        assert league_gaps[0].missing == 1

    def test_game_gap_with_staging(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        """Game gaps should use stg_league_game_log for expected count."""
        # Create staging table with 3 unique game IDs
        conn.execute("""
            CREATE TABLE stg_league_game_log AS
            SELECT * FROM (VALUES
                ('001', '2024-25', '2024-10-01'),
                ('002', '2024-25', '2024-10-02'),
                ('003', '2024-25', '2024-10-03')
            ) AS t(game_id, season_id, game_date)
        """)

        # Seed 2 of 3 games as done
        _seed_done(journal, "box_score_traditional", {"game_id": "001"})
        _seed_done(journal, "box_score_traditional", {"game_id": "002"})

        report = planner.detect_gaps(
            endpoints=["box_score_traditional"],
            patterns=["game"],
        )
        game_gaps = [g for g in report.gaps if g.endpoint == "box_score_traditional"]
        assert len(game_gaps) == 1
        assert game_gaps[0].expected == 3
        assert game_gaps[0].actual == 2
        assert game_gaps[0].missing == 1

    def test_game_gap_no_staging(
        self,
        planner: BackfillPlanner,
    ) -> None:
        """Without staging table, game gaps report expected=None."""
        report = planner.detect_gaps(
            endpoints=["box_score_traditional"],
            patterns=["game"],
        )
        game_gaps = [g for g in report.gaps if g.endpoint == "box_score_traditional"]
        assert len(game_gaps) == 1
        assert game_gaps[0].expected is None
        assert game_gaps[0].missing is None

    def test_completeness_report_summary(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        """CompletenessReport.summary should aggregate missing by pattern."""
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )

        report = planner.detect_gaps(
            endpoints=["league_game_log"],
            patterns=["season"],
            seasons=["2024-25"],
        )
        assert "season" in report.summary
        assert report.summary["season"] >= 1

    def test_production_staging_entries_do_not_suppress_pre_modern_gaps(
        self,
        planner: BackfillPlanner,
    ) -> None:
        """Production staging entries should report gaps back to 1946."""
        report = planner.detect_gaps(
            endpoints=["league_dash_pt_defend"],
            patterns=["season"],
            seasons=["2010-11"],
        )
        gaps = [g for g in report.gaps if g.endpoint == "league_dash_pt_defend"]
        assert len(gaps) == 1
        assert gaps[0].min_season is None


# ── BackfillPlanner plan building ────────────────────────────────


class TestBackfillPlannerBuildPlan:
    def test_static_plan(self, planner: BackfillPlanner) -> None:
        plan = planner.build_plan(patterns=["static"])
        assert plan.total_tasks > 0
        assert "static" in plan.patterns

    def test_season_plan_scoped(self, planner: BackfillPlanner) -> None:
        plan = planner.build_plan(
            seasons=["2024-25"],
            patterns=["season"],
        )
        assert plan.total_tasks > 0
        assert plan.seasons == ["2024-25"]
        season_items = [i for i in plan.items if i.pattern == "season"]
        assert len(season_items) >= 1
        assert any(len(item.params) == len(_ALL_SEASON_TYPES) for item in season_items)

    def test_endpoint_filter(self, planner: BackfillPlanner) -> None:
        plan = planner.build_plan(
            endpoints=["league_game_log"],
            seasons=["2024-25"],
        )
        all_endpoints = {e.endpoint_name for item in plan.items for e in item.entries}
        assert all_endpoints == {"league_game_log"}

    def test_force_resets_journal(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )
        assert journal.was_extracted(
            "league_game_log",
            json.dumps({"season": "2024-25", "season_type": "Regular Season"}, sort_keys=True),
        )

        planner.build_plan(
            endpoints=["league_game_log"],
            seasons=["2024-25"],
            force=True,
        )

        # After force, the entry should be reset
        assert not journal.was_extracted(
            "league_game_log",
            json.dumps({"season": "2024-25", "season_type": "Regular Season"}, sort_keys=True),
        )

    def test_dry_run_summary(self, planner: BackfillPlanner) -> None:
        plan = planner.build_plan(
            seasons=["2024-25"],
            patterns=["season"],
        )
        assert "Backfill plan:" in plan.dry_run_summary
        assert "2024-25" in plan.dry_run_summary

    def test_entity_patterns_return_empty_params(self, planner: BackfillPlanner) -> None:
        """Entity-dependent patterns (game, player, etc.) return empty params."""
        plan = planner.build_plan(patterns=["game"])
        # Game pattern needs runtime discovery, so no plan items generated
        assert len([i for i in plan.items if i.pattern == "game"]) == 0

    def test_player_team_season_plan_uses_persisted_workload_contract(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        tmp_path,
    ) -> None:
        store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
        store.upsert(
            [
                {
                    "player_id": 201939,
                    "team_id": 1610612744,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                }
            ],
            seasons=["2024-25"],
            season_types=["Regular Season"],
        )
        planner = BackfillPlanner(conn, journal, player_team_season_workloads=store)

        plan = planner.build_plan(
            seasons=["2024-25"],
            patterns=["player_team_season"],
            season_types=["Regular Season"],
        )

        assert plan.total_tasks == 2
        assert plan.patterns == ["player_team_season"]
        assert len(plan.items) == 1
        assert [entry.endpoint_name for entry in plan.items[0].entries] == [
            "video_details",
            "video_details_asset",
        ]
        assert plan.items[0].params == [
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            }
        ]


# ── staging_map helpers ──────────────────────────────────────────


class TestStagingMapHelpers:
    def test_get_by_endpoint(self) -> None:
        from nbadb.orchestrate.staging_map import get_by_endpoint

        entries = get_by_endpoint("box_score_traditional")
        assert len(entries) >= 1
        assert all(e.endpoint_name == "box_score_traditional" for e in entries)

    def test_get_by_endpoint_unknown(self) -> None:
        from nbadb.orchestrate.staging_map import get_by_endpoint

        assert get_by_endpoint("nonexistent_endpoint") == []

    def test_get_unique_endpoints(self) -> None:
        from nbadb.orchestrate.staging_map import get_unique_endpoints

        endpoints = get_unique_endpoints()
        assert len(endpoints) > 0
        assert endpoints == sorted(endpoints)
        assert len(endpoints) == len(set(endpoints))

    def test_get_unique_patterns(self) -> None:
        from nbadb.orchestrate.staging_map import get_unique_patterns

        patterns = get_unique_patterns()
        assert "season" in patterns
        assert "game" in patterns
        assert "static" in patterns
        assert patterns == sorted(patterns)


# ── CLI season parsing ───────────────────────────────────────────


class TestSeasonParsing:
    def test_parse_seasons_none(self) -> None:
        from nbadb.cli.commands.backfill import _parse_seasons

        assert _parse_seasons(None) is None

    def test_parse_seasons_single(self) -> None:
        from nbadb.cli.commands.backfill import _parse_seasons

        result = _parse_seasons("2024-25")
        assert result == ["2024-25"]

    def test_parse_seasons_csv(self) -> None:
        from nbadb.cli.commands.backfill import _parse_seasons

        result = _parse_seasons("2023-24,2024-25")
        assert result == ["2023-24", "2024-25"]

    def test_parse_seasons_range(self) -> None:
        from nbadb.cli.commands.backfill import _parse_seasons

        result = _parse_seasons("2020:2022")
        assert result == ["2020-21", "2021-22", "2022-23"]

    def test_parse_seasons_year_only(self) -> None:
        from nbadb.cli.commands.backfill import _parse_seasons

        result = _parse_seasons("2024")
        assert result == ["2024-25"]

    def test_parse_seasons_reversed_range(self) -> None:
        import typer

        from nbadb.cli.commands.backfill import _parse_seasons

        with pytest.raises(typer.BadParameter, match="Reversed season range"):
            _parse_seasons("2025:2020")

    def test_parse_seasons_invalid_int(self) -> None:
        import typer

        from nbadb.cli.commands.backfill import _parse_seasons

        with pytest.raises(typer.BadParameter, match="Invalid season"):
            _parse_seasons("abc")

    def test_parse_seasons_invalid_range(self) -> None:
        import typer

        from nbadb.cli.commands.backfill import _parse_seasons

        with pytest.raises(typer.BadParameter, match="Invalid season range"):
            _parse_seasons("foo:bar")

    def test_parse_csv_none(self) -> None:
        from nbadb.cli.commands.backfill import _parse_csv

        assert _parse_csv(None) is None

    def test_parse_csv_values(self) -> None:
        from nbadb.cli.commands.backfill import _parse_csv

        assert _parse_csv("a,b, c") == ["a", "b", "c"]


# ── LIKE wildcard escape ─────────────────────────────────────────


class TestLikeWildcardEscape:
    def test_reset_entries_escapes_wildcards(
        self,
        journal: PipelineJournal,
    ) -> None:
        """LIKE wildcards in season_like should not over-match."""
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})

        # "202%" would match both if not escaped
        count = journal.reset_entries(endpoint="ep1", season_like="202%")
        assert count == 0  # no exact match for literal "202%"

    def test_clear_entries_escapes_wildcards(
        self,
        journal: PipelineJournal,
    ) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})

        count = journal.clear_entries(endpoint="ep1", season_like="2024_25")
        assert count == 0  # "_" should not match "-"


# ── journal fetch_entries ────────────────────────────────────────


class TestFetchEntries:
    def test_fetch_entries_no_filters(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        rows = journal.fetch_entries()
        assert len(rows) == 2

    def test_fetch_entries_by_endpoints(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        rows = journal.fetch_entries(endpoints=["ep1"])
        assert len(rows) == 1
        assert rows[0][0] == "ep1"

    def test_fetch_entries_by_status(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_failed(journal, "ep2", {"season": "2024-25"})

        rows = journal.fetch_entries(status_filter="done")
        assert len(rows) == 1
        assert rows[0][2] == "done"

    def test_fetch_entries_by_season(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep1", {"season": "2023-24"})

        rows = journal.fetch_entries(seasons=["2024-25"])
        assert len(rows) == 1

    def test_fetch_entries_limit(self, journal: PipelineJournal) -> None:
        for i in range(5):
            _seed_done(journal, f"ep{i}", {"season": "2024-25"})

        rows = journal.fetch_entries(limit=3)
        assert len(rows) == 3


# ── batch endpoint reset ─────────────────────────────────────────


class TestBatchEndpointReset:
    def test_reset_entries_batch(self, journal: PipelineJournal) -> None:
        """Batched endpoint list resets all matching in single call."""
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})
        _seed_done(journal, "ep3", {"season": "2024-25"})

        count = journal.reset_entries(endpoint=["ep1", "ep2"])
        assert count == 2

        # ep3 should still be done
        assert journal.was_extracted("ep3", json.dumps({"season": "2024-25"}, sort_keys=True))
        # ep1 should be reset
        assert not journal.was_extracted("ep1", json.dumps({"season": "2024-25"}, sort_keys=True))

    def test_clear_entries_batch(self, journal: PipelineJournal) -> None:
        _seed_done(journal, "ep1", {"season": "2024-25"})
        _seed_done(journal, "ep2", {"season": "2024-25"})

        count = journal.clear_entries(endpoint=["ep1", "ep2"])
        assert count == 2


# ── gap detection: entity & date patterns ────────────────────────


class TestGapDetectionEntityDate:
    def test_player_gap_with_staging(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        conn.execute("""
            CREATE TABLE stg_common_all_players AS
            SELECT * FROM (VALUES (101), (102), (103)) AS t(person_id)
        """)
        _seed_done(journal, "common_player_info", {"player_id": "101"})

        report = planner.detect_gaps(
            endpoints=["common_player_info"],
            patterns=["player"],
        )
        gaps = [g for g in report.gaps if g.endpoint == "common_player_info"]
        assert len(gaps) == 1
        assert gaps[0].expected == 3
        assert gaps[0].actual == 1
        assert gaps[0].missing == 2

    def test_date_gap_with_staging(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        conn.execute("""
            CREATE TABLE stg_league_game_log AS
            SELECT * FROM (VALUES
                ('001', '2024-25', '2024-10-01'),
                ('002', '2024-25', '2024-10-01'),
                ('003', '2024-25', '2024-10-02')
            ) AS t(game_id, season_id, game_date)
        """)
        _seed_done(journal, "scoreboard_v3", {"game_date": "2024-10-01"})

        report = planner.detect_gaps(
            endpoints=["scoreboard_v3"],
            patterns=["date"],
        )
        gaps = [g for g in report.gaps if g.endpoint == "scoreboard_v3"]
        assert len(gaps) == 1
        assert gaps[0].expected == 2  # 2 distinct dates
        assert gaps[0].actual == 1

    def test_game_gap_season_filtered(
        self,
        conn: duckdb.DuckDBPyConnection,
        planner: BackfillPlanner,
    ) -> None:
        """_count_from_table should filter by season_id when seasons provided."""
        conn.execute("""
            CREATE TABLE stg_league_game_log AS
            SELECT * FROM (VALUES
                ('001', '2024-25', '2024-10-01'),
                ('002', '2024-25', '2024-10-02'),
                ('003', '2023-24', '2024-01-01')
            ) AS t(game_id, season_id, game_date)
        """)

        report = planner.detect_gaps(
            endpoints=["box_score_traditional"],
            patterns=["game"],
            seasons=["2024-25"],
        )
        game_gaps = [g for g in report.gaps if g.endpoint == "box_score_traditional"]
        assert len(game_gaps) == 1
        assert game_gaps[0].expected == 2  # only 2024-25 games


# ── rowcount fix verification ────────────────────────────────────


class TestRowcountFix:
    def test_abandon_exhausted_returns_correct_count(
        self,
        journal: PipelineJournal,
    ) -> None:
        """abandon_exhausted should return actual count, not -1."""
        params_json = json.dumps({"season": "2024-25"}, sort_keys=True)
        journal.record_start("ep1", params_json)
        # Exhaust retries
        for _ in range(PipelineJournal.MAX_RETRIES):
            journal.record_failure("ep1", params_json, "error")
            journal.record_start("ep1", params_json)
            journal.record_failure("ep1", params_json, "error")

        count = journal.abandon_exhausted()
        assert count >= 0  # must not be -1
        assert count == 1


# ── force_reset edge cases ─────────────────────────────────────


class TestForceResetEdgeCases:
    def test_force_reset_empty_seasons_list(
        self,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        """force_reset(seasons=[]) should reset all entries (same as seasons=None)."""
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2024-25", "season_type": "Regular Season"},
        )
        _seed_done(
            journal,
            "league_game_log",
            {"season": "2023-24", "season_type": "Regular Season"},
        )

        planner.force_reset(seasons=[], endpoints=["league_game_log"], patterns=None)

        # With seasons=[], `if seasons:` is falsy, so it resets ALL entries for the endpoint
        p1 = json.dumps({"season": "2024-25", "season_type": "Regular Season"}, sort_keys=True)
        p2 = json.dumps({"season": "2023-24", "season_type": "Regular Season"}, sort_keys=True)
        assert not journal.was_extracted("league_game_log", p1)
        assert not journal.was_extracted("league_game_log", p2)


# ── narrowed exceptions ────────────────────────────────────────


class TestNarrowedExceptions:
    def test_count_from_table_binder_exception_propagates(
        self,
        conn: duckdb.DuckDBPyConnection,
        planner: BackfillPlanner,
    ) -> None:
        """After HR-S-002 fix, BinderException (wrong column) should NOT be caught."""
        conn.execute("""
            CREATE TABLE stg_test_table AS
            SELECT * FROM (VALUES ('001', '2024-25')) AS t(game_id, season_id)
        """)

        # Access the private method directly to test the exception behavior
        # Passing a nonexistent column should raise BinderException, not return None
        import duckdb as _duckdb

        with pytest.raises(_duckdb.BinderException):
            planner._count_from_table("stg_test_table", "nonexistent_column")


# ── completeness summary unknown gaps ──────────────────────────


class TestCompletenessSummaryUnknown:
    def test_summary_tracks_unknown_gaps(
        self,
        planner: BackfillPlanner,
    ) -> None:
        """Cross-product patterns should produce '{pattern}_unknown' keys in summary."""
        # video_details uses player_team_season pattern → _gaps_cross_product
        report = planner.detect_gaps(
            endpoints=["video_details"],
            patterns=["player_team_season"],
        )
        # Cross-product gaps should NOT show as numeric 0 in summary
        # They should show under a separate _unknown key
        assert "player_team_season_unknown" in report.summary
        assert report.summary["player_team_season_unknown"] >= 1
        # The numeric key should NOT be present (or should be 0)
        assert report.summary.get("player_team_season", 0) == 0

    def test_supported_cross_product_uses_season_type_aware_expected_counts(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        planner: BackfillPlanner,
    ) -> None:
        conn.execute("""
            CREATE TABLE stg_common_all_players AS
            SELECT * FROM (VALUES
                (201939, 1610612744, '2024-25'),
                (2544, 1610612747, '2024-25')
            ) AS t(person_id, team_id, season)
        """)
        _seed_done(
            journal,
            "video_details",
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
        )

        report = planner.detect_gaps(
            endpoints=["video_details"],
            patterns=["player_team_season"],
            seasons=["2024-25"],
            season_types=["Regular Season", "Playoffs"],
        )

        gaps = [g for g in report.gaps if g.endpoint == "video_details"]
        assert len(gaps) == 1
        assert gaps[0].season == "2024-25"
        assert gaps[0].expected == 4
        assert gaps[0].actual == 1
        assert gaps[0].missing == 3

    def test_supported_cross_product_uses_persisted_workload_contract(
        self,
        conn: duckdb.DuckDBPyConnection,
        journal: PipelineJournal,
        tmp_path,
    ) -> None:
        store = PlayerTeamSeasonWorkloadStore.from_duckdb_path(tmp_path / "planner.duckdb")
        store.upsert(
            [
                {
                    "player_id": 201939,
                    "team_id": 1610612744,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 2544,
                    "team_id": 1610612747,
                    "season": "2024-25",
                    "season_type": "Regular Season",
                },
                {
                    "player_id": 201939,
                    "team_id": 1610612744,
                    "season": "2024-25",
                    "season_type": "Playoffs",
                },
                {
                    "player_id": 2544,
                    "team_id": 1610612747,
                    "season": "2024-25",
                    "season_type": "Playoffs",
                },
            ],
            seasons=["2024-25"],
            season_types=["Regular Season", "Playoffs"],
        )
        planner = BackfillPlanner(conn, journal, player_team_season_workloads=store)
        _seed_done(
            journal,
            "video_details",
            {
                "player_id": 201939,
                "team_id": 1610612744,
                "season": "2024-25",
                "season_type": "Regular Season",
            },
        )

        report = planner.detect_gaps(
            endpoints=["video_details"],
            patterns=["player_team_season"],
            seasons=["2024-25"],
            season_types=["Regular Season", "Playoffs"],
        )

        gaps = [g for g in report.gaps if g.endpoint == "video_details"]
        assert len(gaps) == 1
        assert gaps[0].expected == 4
        assert gaps[0].actual == 1
        assert gaps[0].missing == 3

    def test_blocked_cross_product_remains_unknown_even_with_discovery_state(
        self,
        conn: duckdb.DuckDBPyConnection,
        planner: BackfillPlanner,
    ) -> None:
        conn.execute("""
            CREATE TABLE stg_common_all_players AS
            SELECT * FROM (VALUES
                (201939, 1610612744, '2024-25'),
                (2544, 1610612747, '2024-25')
            ) AS t(person_id, team_id, season)
        """)

        report = planner.detect_gaps(
            endpoints=["player_vs_player"],
            patterns=["player_team_season"],
            seasons=["2024-25"],
        )

        gaps = [g for g in report.gaps if g.endpoint == "player_vs_player"]
        assert len(gaps) == 1
        assert gaps[0].expected is None
        assert gaps[0].missing is None
