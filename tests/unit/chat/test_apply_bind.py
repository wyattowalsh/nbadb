from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from nbadb.agent.season_bind import SeasonBind
from nbadb.chat.catalog.apply_bind import apply_season_bind
from nbadb.chat.catalog.route_meta import RouteSeasonMeta
from nbadb.chat.catalog.sql_shape import SQLShapeError

_REPO_ROOT = Path(__file__).resolve().parents[3]


def test_apply_bind_imports_first_in_a_clean_interpreter() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from nbadb.chat.catalog.apply_bind import apply_season_bind; "
                "assert callable(apply_season_bind)"
            ),
        ],
        cwd=_REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr


def test_apply_bind_injects_before_order_by() -> None:
    sql = "SELECT s.player_id FROM agg_player_season s ORDER BY s.total_pts DESC"
    bind = SeasonBind("2024-25", "Regular Season", "default")
    out = apply_season_bind(
        sql,
        bind,
        meta=RouteSeasonMeta("s.season_year", "s.season_type"),
    )
    assert "WHERE s.season_year = '2024-25'" in out
    assert "s.season_type = 'Regular Season'" in out
    assert out.index("WHERE") < out.upper().index("ORDER BY")


def test_apply_bind_rejects_invalid_by_omission() -> None:
    sql = "SELECT 1 FROM t ORDER BY 1"
    bind = SeasonBind("'; DROP TABLE x; --", "HACK", "extracted")
    out = apply_season_bind(
        sql,
        bind,
        meta=RouteSeasonMeta("s.season_year", "s.season_type"),
    )
    assert "DROP" not in out
    assert out == sql


def test_apply_bind_year_only_skips_type() -> None:
    sql = "SELECT s.game_date FROM analytics_team_game_complete s ORDER BY s.game_date DESC"
    bind = SeasonBind("2024-25", "Regular Season", "default")
    out = apply_season_bind(
        sql,
        bind,
        meta=RouteSeasonMeta("s.season_year", None),
    )
    assert "s.season_year = '2024-25'" in out
    assert "season_type" not in out


def test_apply_bind_box_routes_use_declared_aliases() -> None:
    from nbadb.chat.catalog.route_meta import season_meta_for

    player_sql = (
        "SELECT b.game_id, b.pts FROM fact_player_game_traditional b ORDER BY b.game_id DESC"
    )
    team_sql = (
        "SELECT b.game_id, b.pts FROM fact_box_score_team b "
        "JOIN dim_game g ON b.game_id = g.game_id "
        "ORDER BY g.game_date DESC"
    )
    bind = SeasonBind("2024-25", "Regular Season", "default")
    player_out = apply_season_bind(
        player_sql, bind, route="player_box_score", meta=season_meta_for("player_box_score")
    )
    team_out = apply_season_bind(
        team_sql, bind, route="team_box_score", meta=season_meta_for("team_box_score")
    )
    assert "b.season_year = '2024-25'" in player_out
    assert "g.season_year = '2024-25'" in team_out


def test_apply_bind_parenthesizes_existing_or_predicate() -> None:
    sql = "SELECT * FROM t WHERE visible = TRUE OR featured = TRUE ORDER BY score DESC"
    bind = SeasonBind("2024-25", "Regular Season", "default")

    out = apply_season_bind(
        sql,
        bind,
        meta=RouteSeasonMeta("season_year", "season_type"),
    )

    assert out == (
        "SELECT * FROM t WHERE (visible = TRUE OR featured = TRUE) "
        "AND season_year = '2024-25' AND season_type = 'Regular Season' "
        "ORDER BY score DESC"
    )


def test_apply_bind_ignores_nested_and_quoted_clause_words() -> None:
    sql = (
        "SELECT * FROM (SELECT * FROM t ORDER BY score) q "
        "WHERE q.label = 'ORDER BY' ORDER BY q.score DESC"
    )

    out = apply_season_bind(
        sql,
        SeasonBind("2024-25", None, "default"),
        meta=RouteSeasonMeta("q.season_year", None),
    )

    assert out == (
        "SELECT * FROM (SELECT * FROM t ORDER BY score) q "
        "WHERE (q.label = 'ORDER BY') AND q.season_year = '2024-25' "
        "ORDER BY q.score DESC"
    )


def test_apply_bind_rejects_top_level_set_operations() -> None:
    sql = "SELECT season_year FROM a UNION ALL SELECT season_year FROM b"

    with pytest.raises(SQLShapeError, match="set operations"):
        apply_season_bind(
            sql,
            SeasonBind("2024-25", None, "default"),
            meta=RouteSeasonMeta("season_year", None),
        )
