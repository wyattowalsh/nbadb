"""Golden NL corpus for thin catalog chat/ask (G5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.agent.query import QueryAgent
from nbadb.agent.season_bind import previous_season_year
from nbadb.orchestrate.seasons import current_season

if TYPE_CHECKING:
    from pathlib import Path


class TestGoldenChat:
    def test_g5_01_last_season_scoring(self, agent: QueryAgent) -> None:
        result = agent.ask_result("who led scoring last season?")
        assert result.ok is True
        assert result.route == "player_season_scoring"
        assert result.sql is not None
        assert previous_season_year(current_season()) in result.sql
        assert "Regular Season" in result.sql

    def test_g5_02_default_scoring(self, agent: QueryAgent) -> None:
        result = agent.ask_result("who led scoring?")
        assert result.ok is True
        assert result.sql is not None
        assert "Regular Season" in result.sql
        assert current_season() in result.sql

    def test_g5_03_playoff_scoring(self, agent: QueryAgent) -> None:
        result = agent.ask_result("playoff scoring leaders")
        assert result.route == "player_season_scoring"
        assert result.sql is not None
        assert "Playoffs" in result.sql

    def test_g5_04_game_count(self, agent: QueryAgent) -> None:
        result = agent.ask_result("how many games are there?")
        assert result.ok is True
        assert result.route == "game_count"
        assert result.sql is not None
        assert "dim_game" in result.sql
        assert "_pipeline_metadata" not in result.sql
        assert result.rows == ((2,),)
        for key in ("season_year", "season_type", "season_source"):
            assert key not in result.metadata

    def test_g5_05_pipeline_inventory(self, agent: QueryAgent) -> None:
        result = agent.ask_result("show pipeline inventory")
        assert result.route == "pipeline_inventory"
        assert result.sql is not None
        assert "_pipeline_metadata" in result.sql
        for key in ("season_year", "season_type", "season_source"):
            assert key not in result.metadata

    def test_g5_06_standings(self, agent: QueryAgent) -> None:
        result = agent.ask_result("what are the standings?")
        assert result.route == "team_standings"
        assert result.sql is not None
        assert "fact_standings" in result.sql
        assert "Regular Season" in result.sql

    def test_g5_08_assists_this_season(self, agent: QueryAgent) -> None:
        result = agent.ask_result("most assists this season")
        assert result.route == "player_season_assists"
        assert result.sql is not None
        assert current_season() in result.sql

    def test_g5_09_unsupported_ranked_pack(self, agent: QueryAgent) -> None:
        result = agent.ask_result("unmatchable xyzzy 999")
        assert result.ok is False
        assert result.route == "unsupported"
        assert result.schema_context is not None
        # Bounded pack: not every warehouse table.
        table_headers = [
            line for line in result.schema_context.splitlines() if line and not line.startswith(" ")
        ]
        # Heuristic: pack stays short relative to a full 254-table dump.
        assert len(result.schema_context) < 20_000
        assert "NBA rules:" in result.schema_context
        assert "Top tables" in result.schema_context or "Relevant semantic" in result.schema_context
        assert table_headers  # non-empty

    def test_g5_12_empty_matched_still_ok(self, tmp_path: Path) -> None:
        import duckdb

        db = tmp_path / "empty_match.duckdb"
        with duckdb.connect(str(db)) as conn:
            conn.execute(
                "CREATE TABLE dim_player (player_id INTEGER, full_name VARCHAR, is_current BOOLEAN)"
            )
            conn.execute(
                "CREATE TABLE agg_player_season ("
                "player_id INTEGER, season_year VARCHAR, season_type VARCHAR, total_pts INTEGER)"
            )
            # Empty warehouse tables → calendar default season binds, still empty ok.
            conn.execute("INSERT INTO dim_player VALUES (1, 'X', TRUE)")
        agent = QueryAgent(db)
        result = agent.ask_result("who led scoring?")
        assert result.route == "player_season_scoring"
        assert result.ok is True
        assert result.row_count == 0
        assert result.render_text() == "No results found."
