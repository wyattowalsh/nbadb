from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamGameTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_game"
    depends_on: ClassVar[list[str]] = [
        "stg_box_score_traditional_team",
        "stg_line_score",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH team_payload AS (
            SELECT
                game_id, team_id,
                fgm, fga, fg_pct,
                fg3m, fg3a, fg3_pct,
                ftm, fta, ft_pct,
                oreb, dreb, reb,
                ast, stl, blk, tov, pf, pts
            FROM stg_box_score_traditional_team
        ),
        team_unique AS (
            SELECT DISTINCT *
            FROM team_payload
        ),
        team_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id, team_id) = 1
                        THEN game_id
                    ELSE error(
                        'fact_team_game: conflicting official TeamStats rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM team_unique
        ),
        line_payload AS (
            SELECT
                game_id, team_id,
                pts_qtr1, pts_qtr2, pts_qtr3, pts_qtr4
            FROM stg_line_score
        ),
        line_unique AS (
            SELECT DISTINCT *
            FROM line_payload
        ),
        line_authority AS (
            SELECT
                CASE
                    WHEN COUNT(*) OVER (PARTITION BY game_id, team_id) = 1
                        THEN game_id
                    ELSE error(
                        'fact_team_game: conflicting LineScore rows for one key'
                    )
                END AS game_id,
                * EXCLUDE (game_id)
            FROM line_unique
        )
        SELECT
            t.*,
            g.season_year,
            l.pts_qtr1, l.pts_qtr2, l.pts_qtr3, l.pts_qtr4
        FROM team_authority t
        LEFT JOIN dim_game g ON t.game_id = g.game_id
        LEFT JOIN line_authority l
            ON t.game_id = l.game_id AND t.team_id = l.team_id
    """
