from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamGameTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_team_game"
    depends_on: ClassVar[list[str]] = [
        "stg_box_score_traditional",
        "stg_line_score",
        "dim_game",
    ]

    _SQL: ClassVar[str] = """
        WITH team_agg AS (
            SELECT
                game_id, team_id,
                SUM(fgm) AS fgm, SUM(fga) AS fga,
                SUM(fgm)::FLOAT / NULLIF(SUM(fga), 0) AS fg_pct,
                SUM(fg3m) AS fg3m, SUM(fg3a) AS fg3a,
                SUM(fg3m)::FLOAT / NULLIF(SUM(fg3a), 0) AS fg3_pct,
                SUM(ftm) AS ftm, SUM(fta) AS fta,
                SUM(ftm)::FLOAT / NULLIF(SUM(fta), 0) AS ft_pct,
                SUM(oreb) AS oreb, SUM(dreb) AS dreb,
                SUM(reb) AS reb,
                SUM(ast) AS ast, SUM(stl) AS stl,
                SUM(blk) AS blk, SUM(tov) AS tov,
                SUM(pf) AS pf, SUM(pts) AS pts
            FROM stg_box_score_traditional
            WHERE player_id IS NOT NULL
            GROUP BY game_id, team_id
        )
        SELECT
            t.*,
            g.season_year,
            l.pts_qtr1, l.pts_qtr2, l.pts_qtr3, l.pts_qtr4
        FROM team_agg t
        LEFT JOIN dim_game g ON t.game_id = g.game_id
        LEFT JOIN stg_line_score l
            ON t.game_id = l.game_id AND t.team_id = l.team_id
        QUALIFY ROW_NUMBER() OVER (PARTITION BY t.game_id, t.team_id ORDER BY t.game_id) = 1
    """
