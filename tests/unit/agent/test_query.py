"""Tests for nbadb.agent.query.QueryAgent."""

from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import duckdb
import pytest

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.agent.query import QueryAgent, QueryPlan
from nbadb.agent.safety import MAX_RESULT_ROWS

# Fixtures: tmp_db, agent, agent_empty from conftest.py


class TestQueryAgentInit:
    def test_creates_with_path(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        assert agent._path == tmp_db

    def test_has_readonly_guard(self, agent: QueryAgent) -> None:
        from nbadb.agent.safety import ReadOnlyGuard

        assert isinstance(agent._guard, ReadOnlyGuard)

    def test_has_schema_context(self, agent: QueryAgent) -> None:
        from nbadb.agent.context import SchemaContext

        assert isinstance(agent._context, SchemaContext)


class TestQueryAgentPatternMatching:
    @pytest.mark.parametrize(
        "question,expected_fragment",
        [
            ("who led in scoring last season?", "total_pts"),
            ("who led scoring this year?", "total_pts"),
            ("which player had the most points?", "total_pts"),
            ("who had the most assists this season?", "total_ast"),
            ("who had the most rebounds?", "total_reb"),
            ("show team standings", "fact_standings"),
            ("what are the standings?", "fact_standings"),
            ("how many games are there?", "dim_game"),
            ("how many records do you have?", "_pipeline_metadata"),
        ],
    )
    def test_pattern_matches_trigger_phrase(
        self, agent: QueryAgent, question: str, expected_fragment: str
    ) -> None:
        plan = agent._match_pattern(question)
        assert plan is not None, f"No pattern matched for: {question!r}"
        assert expected_fragment in plan.sql

    def test_unmatched_input_returns_schema_context(self, agent: QueryAgent) -> None:
        result = agent.ask("what is the meaning of life?")
        assert "couldn't match" in result.lower()
        lowered = result.lower()
        assert "schema" in lowered or "tables" in lowered or "nba rules" in lowered
        assert "DuckDB SQL directly" not in result

    def test_unmatched_input_does_not_contain_traceback(self, agent: QueryAgent) -> None:
        result = agent.ask("random gibberish xyz 12345")
        assert "Traceback" not in result

    def test_no_legacy_pattern_registry(self) -> None:
        import nbadb.agent.query as query_mod

        assert not hasattr(query_mod, "_PATTERNS")

    def test_catalog_route_count(self) -> None:
        from nbadb.chat.catalog import default_catalog

        catalog = default_catalog()
        routed = [entry for entry in catalog.entries if entry.route and entry.sql_template]
        assert len(routed) >= 26

    @pytest.mark.parametrize(
        "question,route_fragment",
        [
            ("who had the fastest pace?", "team_pace"),
            ("show shot chart zones", "shot_chart"),
            ("draft picks by value", "draft_value"),
            ("head to head records", "head_to_head"),
            ("team season stats", "team_season"),
            ("player season profile", "player_season_complete"),
            ("show game log", "player_game_log"),
            ("clutch performance leaders", "clutch_performance"),
            ("player matchup stats", "player_matchups"),
            ("franchise history titles", "franchise_history"),
        ],
    )
    def test_catalog_routes_match_extended_intents(
        self, agent: QueryAgent, question: str, route_fragment: str
    ) -> None:
        plan = agent._match_pattern(question)
        assert plan is not None, f"No route matched for: {question!r}"
        assert route_fragment in plan.route

    def test_season_filters_injected_for_scoring(self, agent: QueryAgent) -> None:
        from nbadb.orchestrate.seasons import current_season

        plan = agent._match_pattern("who led scoring?")
        assert plan is not None
        assert "season_year" in plan.sql
        # Warehouse max matches seeded current_season in tmp_db.
        assert current_season() in plan.sql
        assert "Regular Season" in plan.sql
        assert plan.season_source in {"warehouse_default", "default"}

    def test_warehouse_default_preferred_over_calendar(self, tmp_path: Path) -> None:
        import duckdb

        db = tmp_path / "wh.duckdb"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
            )
            conn.execute(
                "CREATE TABLE agg_player_season ("
                "player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                "total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
            )
            conn.execute("INSERT INTO dim_player VALUES (1, 'A', TRUE)")
            conn.execute(
                "INSERT INTO agg_player_season VALUES (1, '2022-23', 'Regular Season', 100, 10, 10)"
            )
        agent = QueryAgent(db)
        plan = agent._match_pattern("who led scoring?")
        assert plan is not None
        assert plan.season_year == "2022-23"
        assert plan.season_source == "warehouse_default"

    def test_each_route_uses_its_own_visible_warehouse_max(self, tmp_path: Path) -> None:
        db = tmp_path / "route-max.duckdb"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
            )
            conn.execute(
                "CREATE TABLE agg_player_season ("
                "player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                "total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
            )
            conn.execute("CREATE TABLE dim_team (team_id INTEGER, full_name VARCHAR)")
            conn.execute(
                "CREATE TABLE fact_standings ("
                "team_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                "wins INTEGER, losses INTEGER, win_pct DOUBLE)"
            )
            conn.execute("INSERT INTO dim_player VALUES (1, 'Player', TRUE)")
            conn.execute(
                "INSERT INTO agg_player_season VALUES (1, '2022-23', 'Regular Season', 100, 10, 10)"
            )
            conn.execute("INSERT INTO dim_team VALUES (1, 'Team')")
            conn.execute(
                "INSERT INTO fact_standings VALUES (1, '2023-24', 'Regular Season', 50, 32, 0.61)"
            )

        agent = QueryAgent(db)
        scoring = agent._match_pattern("who led scoring?")
        standings = agent._match_pattern("show team standings")

        assert scoring is not None
        assert scoring.season_year == "2022-23"
        assert standings is not None
        assert standings.season_year == "2023-24"
        assert agent.ask_result("show team standings").row_count == 1

    def test_route_probe_is_type_specific_and_request_local(self, tmp_path: Path) -> None:
        db = tmp_path / "type-max.duckdb"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
            )
            conn.execute(
                "CREATE TABLE agg_player_season ("
                "player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                "total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
            )
            conn.execute("INSERT INTO dim_player VALUES (1, 'Player', TRUE)")
            conn.execute(
                "INSERT INTO agg_player_season VALUES "
                "(1, '2022-23', 'Regular Season', 100, 10, 10),"
                "(1, '2023-24', 'Playoffs', 80, 8, 8)"
            )

        agent = QueryAgent(db)
        with patch.object(
            agent,
            "_warehouse_season_year",
            wraps=agent._warehouse_season_year,
        ) as probe:
            regular = agent._match_pattern("who led scoring?")
            playoffs = agent._match_pattern("playoff scoring leaders")
            regular_again = agent._match_pattern("who led scoring?")

        assert regular is not None
        assert regular.season_year == "2022-23"
        assert playoffs is not None
        assert playoffs.season_year == "2023-24"
        assert playoffs.season_source == "warehouse_default"
        assert regular_again is not None
        assert probe.call_count == 3
        assert not hasattr(agent, "_warehouse_season_cache")

    def test_route_probe_mirrors_current_player_visibility(self, tmp_path: Path) -> None:
        db = tmp_path / "visible-max.duckdb"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
            )
            conn.execute(
                "CREATE TABLE agg_player_season ("
                "player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                "total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
            )
            conn.execute("INSERT INTO dim_player VALUES (1, 'Visible', TRUE)")
            conn.execute(
                "INSERT INTO agg_player_season VALUES "
                "(1, '2022-23', 'Regular Season', 100, 10, 10),"
                "(2, '2023-24', 'Regular Season', 200, 20, 20)"
            )

        plan = QueryAgent(db)._match_pattern("who led scoring?")

        assert plan is not None
        assert plan.season_year == "2022-23"

    def test_explicit_year_bypasses_warehouse_probe(self, agent: QueryAgent) -> None:
        with patch.object(agent, "_warehouse_season_year") as probe:
            plan = agent._match_pattern("who led scoring 2023-24?")

        assert plan is not None
        assert plan.season_year == "2023-24"
        probe.assert_not_called()

    @pytest.mark.parametrize(
        "question",
        [
            "most points 2024-9",
            "most points 2024-025",
            "most points 2024/25",
            "most points 2024–25",
            "most points 2024\u00a0-\u00a025",
            "most points ２０２４-２５",
            "most points 2024-99",
            "most points 2024-99-01",
            "most points 2024/99/01",
            "most points 2024-02-30",
            "most points 2023-24 and 2024/25 last season",
        ],
    )
    def test_malformed_season_fails_before_probe_or_sql_binding(
        self,
        agent: QueryAgent,
        question: str,
    ) -> None:
        with (
            patch.object(agent, "_warehouse_season_year") as probe,
            patch("nbadb.agent.query.apply_season_bind") as apply_bind,
        ):
            result = agent.ask_result(question)

        assert result.route == "needs_params"
        assert result.sql is None
        assert result.metadata["needs_reason"] == "invalid_season_year"
        for key in ("sql_hash", "season_year", "season_type", "season_source"):
            assert key not in result.metadata
        probe.assert_not_called()
        apply_bind.assert_not_called()

    @pytest.mark.parametrize(
        ("question", "reason"),
        [
            ("most points 2024-99", "invalid_season_year"),
            ("how many games 2023-24", "unsupported_season_year"),
            ("shot chart playoffs 2023-24", "unsupported_season_type"),
            ("clutch performance playoffs 2023-24", "unsupported_season_type"),
            ("player matchups playoffs 2023-24", "unsupported_season_type"),
        ],
    )
    def test_invalid_or_unsupported_season_dimensions_fail_closed(
        self,
        agent: QueryAgent,
        question: str,
        reason: str,
    ) -> None:
        plan = agent._match_pattern(question)

        assert plan is not None
        assert plan.route == "needs_params"
        assert plan.needs_reason == reason
        assert plan.sql == ""
        assert plan.season_year is None
        assert plan.season_type is None
        assert plan.season_source is None

    def test_needs_params_response_omits_sql_and_season_provenance(self, agent: QueryAgent) -> None:
        result = agent.ask_result("shot chart playoffs 2023-24")

        assert result.route == "needs_params"
        assert result.sql is None
        assert result.metadata["needs_reason"] == "unsupported_season_type"
        assert result.metadata["catalog_entry"] == "shot chart"
        for key in ("sql_hash", "season_year", "season_type", "season_source"):
            assert key not in result.metadata

    @pytest.mark.parametrize("mode", ["missing", "empty", "invalid"])
    def test_probe_failure_falls_back_with_sanitized_warning(
        self, tmp_path: Path, mode: str
    ) -> None:
        from nbadb.orchestrate.seasons import current_season

        db = tmp_path / f"probe-{mode}.duckdb"
        with duckdb.connect(str(db)) as conn:
            if mode != "missing":
                conn.execute(
                    "CREATE TABLE dim_player ("
                    "player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
                )
                conn.execute(
                    "CREATE TABLE agg_player_season ("
                    "player_id INTEGER, season_year VARCHAR, season_type VARCHAR,"
                    "total_pts INTEGER, total_ast INTEGER, total_reb INTEGER)"
                )
            if mode == "invalid":
                conn.execute("INSERT INTO dim_player VALUES (1, 'Player', TRUE)")
                conn.execute(
                    "INSERT INTO agg_player_season VALUES "
                    "(1, 'not-a-season', 'Regular Season', 1, 1, 1)"
                )

        plan = QueryAgent(db)._match_pattern("who led scoring?")

        assert plan is not None
        assert plan.season_year == current_season()
        assert plan.season_source == "default"
        assert len(plan.warnings) == 1
        assert "used the calendar season" in plan.warnings[0]
        assert "CatalogException" not in plan.warnings[0]


class TestQueryAgentExecution:
    def test_execute_returns_formatted_table(self, agent: QueryAgent) -> None:
        mock_explain = MagicMock()
        mock_result = MagicMock()
        mock_result.description = [("player_id",), ("full_name",), ("season_year",), ("total_pts",)]
        mock_result.fetchall.return_value = [(1, "Test Player", "2024-25", 2500)]

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, mock_explain, mock_result]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("nbadb.agent.query.duckdb.connect", return_value=mock_conn):
            result = agent.ask("who led scoring 2024-25?")

        assert "Test Player" in result
        assert "player_id" in result
        assert " | " in result

    def test_execute_no_results(self, agent: QueryAgent) -> None:
        mock_explain = MagicMock()
        mock_result = MagicMock()
        mock_result.description = [("player_id",), ("full_name",), ("total_pts",)]
        mock_result.fetchall.return_value = []

        mock_conn = MagicMock()
        mock_conn.execute.side_effect = [None, mock_explain, mock_result]
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)

        with patch("nbadb.agent.query.duckdb.connect", return_value=mock_conn):
            result = agent.ask("who led scoring 2024-25?")

        assert result == "No results found."

    def test_execute_live_duckdb_query_returns_rows(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        result = agent.ask_result("who led scoring?")
        assert result.ok is True
        assert result.route == "player_season_scoring"
        assert "total_pts" in result.columns
        assert result.row_count == 1
        assert result.rows[0][1] == "Test Player"

    def test_enable_external_access_disabled(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, MagicMock(), mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?")

            first = mock_conn.execute.call_args_list[0].args[0]
            assert "enable_external_access" in first
            assert "false" in first.lower()


class TestQueryAgentSafety:
    def test_duckdb_error_returns_safe_message(self, tmp_path: Path) -> None:
        db_path = tmp_path / "bad.duckdb"
        with duckdb.connect(str(db_path)) as conn:
            conn.execute("SELECT 1")

        agent = QueryAgent(db_path)
        result = agent.ask("who led scoring?")
        assert result == "Query could not be planned safely. Please try a different question."
        assert "agg_player_season" not in result
        assert "Traceback" not in result

    def test_readonly_connection_used(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("col1",)]
            mock_result.fetchall.return_value = [("val1",)]
            mock_conn.execute.return_value = mock_result
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?")

            mock_connect.assert_called_once_with(str(tmp_db), read_only=True)

    def test_guard_blocks_write_query(self, agent: QueryAgent) -> None:
        bad_plan = QueryPlan(sql="DROP TABLE dim_player", route="bad", tables=("dim_player",))
        with patch.object(agent, "_match_pattern", return_value=bad_plan):
            result = agent.ask("anything")
            assert "blocked" in result.lower()

    def test_guard_wraps_with_limit(self, agent: QueryAgent) -> None:
        wrapped = agent._guard.wrap_with_limit("SELECT 1 FROM t")
        assert "LIMIT" in wrapped

    def test_ask_applies_custom_limit(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, MagicMock(), mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?", limit=3)

            sql = mock_conn.execute.call_args_list[2].args[0]
            assert "LIMIT 3" in sql.upper()

    @pytest.mark.parametrize("limit", [0, -5])
    def test_ask_clamps_non_positive_limit(self, tmp_db: Path, limit: int) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, MagicMock(), mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?", limit=limit)

            sql = mock_conn.execute.call_args_list[2].args[0]
            assert "LIMIT 1" in sql.upper()

    def test_ask_clamps_very_large_limit(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, MagicMock(), mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?", limit=MAX_RESULT_ROWS + 1)

            sql = mock_conn.execute.call_args_list[2].args[0]
            assert f"LIMIT {MAX_RESULT_ROWS}" in sql.upper()

    def test_ask_result_exposes_query_provenance(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.side_effect = [None, MagicMock(), mock_result]
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            result = agent.ask_result("who led scoring 2024-25?", limit=3)

        assert result.route == "player_season_scoring"
        assert result.sql is not None
        assert "agg_player_season" in result.sql
        assert result.tables == ("agg_player_season", "dim_player")
        assert result.max_rows == 3
        assert result.metadata["catalog_entry"] == "player season scoring"
        assert result.metadata["sql_hash"]
        assert result.metadata["scd2_notes"]
        assert result.metadata["season_year"]
        assert result.metadata["season_type"] == "Regular Season"

    def test_unsupported_is_not_ok(self, agent: QueryAgent) -> None:
        result = agent.ask_result("completely unknown question abcxyz")
        assert result.ok is False
        assert result.route == "unsupported"

    def test_unsupported_duckdb_timeout_is_not_set(self, tmp_db: Path) -> None:
        agent = QueryAgent(tmp_db)
        with patch("nbadb.agent.query.duckdb.connect") as mock_connect:
            mock_conn = MagicMock()
            mock_result = MagicMock()
            mock_result.description = [("c",)]
            mock_result.fetchall.return_value = [("v",)]
            mock_conn.execute.return_value = mock_result
            mock_conn.__enter__ = MagicMock(return_value=mock_conn)
            mock_conn.__exit__ = MagicMock(return_value=False)
            mock_connect.return_value = mock_conn

            agent.ask("who led scoring 2024-25?")

            for call in mock_conn.execute.call_args_list:
                sql = call.args[0] if call.args else ""
                assert "statement_timeout" not in str(sql).lower()
