from __future__ import annotations

from typing import TYPE_CHECKING
from unittest.mock import patch

if TYPE_CHECKING:
    from nbadb.agent.query import QueryAgent


def test_distinct_player_game_log_plans_and_results(agent: QueryAgent, season_year: str) -> None:
    lebron_plan = agent._match_pattern(f"show LeBron James game log {season_year}")
    curry_plan = agent._match_pattern("show Stephen Curry game log 2023-24")

    assert lebron_plan is not None
    assert curry_plan is not None
    assert lebron_plan.route == curry_plan.route == "player_game_log"
    assert lebron_plan.parameters == (2544,)
    assert curry_plan.parameters == (201939,)
    assert "s.player_id = ?" in lebron_plan.sql

    lebron = agent.ask_result(f"show LeBron James game log {season_year}")
    curry = agent.ask_result("show Stephen Curry game log 2023-24")
    assert lebron.ok and curry.ok
    assert lebron.rows == (("2024-10-01", "LeBron James", 31, 8, 9),)
    assert curry.rows == (("2024-01-10", "Stephen Curry", 42, 5, 6),)
    assert lebron.metadata["entity_ids"] == [2544]
    assert curry.metadata["entity_ids"] == [201939]


def test_distinct_team_roster_plans_and_results(agent: QueryAgent, season_year: str) -> None:
    boston_plan = agent._match_pattern(f"show Boston roster {season_year}")
    miami_plan = agent._match_pattern(f"show Miami roster {season_year}")

    assert boston_plan is not None
    assert miami_plan is not None
    assert boston_plan.parameters == (1610612738,)
    assert miami_plan.parameters == (1610612748,)
    assert "b.team_id = ?" in boston_plan.sql

    boston = agent.ask_result(f"show Boston roster {season_year}")
    miami = agent.ask_result(f"show Miami roster {season_year}")
    assert boston.ok and miami.ok
    assert boston.rows == ((season_year, "Test Player", "Boston Celtics"),)
    assert miami.rows == ((season_year, "LeBron James", "Miami Heat"),)


def test_entity_scopes_missing_year_route_probe(agent: QueryAgent, season_year: str) -> None:
    lebron = agent._match_pattern("show LeBron James game log")
    curry = agent._match_pattern("show Stephen Curry game log")

    assert lebron is not None and curry is not None
    assert lebron.season_year == season_year
    assert curry.season_year == "2023-24"
    assert lebron.parameters == (2544,)
    assert curry.parameters == (201939,)


def test_generic_entity_capable_route_remains_league_wide(
    agent: QueryAgent,
    season_year: str,
) -> None:
    plan = agent._match_pattern(f"show game log {season_year}")

    assert plan is not None
    assert plan.route == "player_game_log"
    assert plan.parameters == ()
    assert "s.player_id = ?" not in plan.sql
    assert agent.ask_result(f"show game log {season_year}").row_count == 1


def test_ambiguous_and_unresolved_entity_fail_before_probe_or_sql(
    agent: QueryAgent,
) -> None:
    with (
        patch.object(agent, "_warehouse_season_year") as probe,
        patch("nbadb.agent.query.apply_season_bind") as season_bind,
        patch("nbadb.agent.query.apply_entity_bind") as entity_bind,
    ):
        ambiguous = agent.ask_result("show Curry game log 2023-24")
        unresolved = agent.ask_result("who played for Atlantis 2023-24")

    assert ambiguous.route == unresolved.route == "needs_params"
    assert ambiguous.metadata["needs_reason"] == "ambiguous_entity"
    assert unresolved.metadata["needs_reason"] == "unresolved_entity"
    for response in (ambiguous, unresolved):
        assert response.sql is None
        for key in (
            "sql_hash",
            "season_year",
            "season_type",
            "season_source",
            "entity_ids",
            "entity_names",
        ):
            assert key not in response.metadata
    probe.assert_not_called()
    season_bind.assert_not_called()
    entity_bind.assert_not_called()


def test_required_roster_cue_without_entity_fails_before_probe(agent: QueryAgent) -> None:
    with patch.object(agent, "_warehouse_season_year") as probe:
        result = agent.ask_result("who played for 2023-24?")

    assert result.route == "needs_params"
    assert result.metadata["needs_reason"] == "unresolved_entity"
    probe.assert_not_called()
