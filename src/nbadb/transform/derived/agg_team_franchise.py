from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggTeamFranchiseTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_team_franchise"
    depends_on: ClassVar[list[str]] = ["stg_franchise"]

    _SQL: ClassVar[str] = """
        WITH franchise_rows AS (
            SELECT
                CASE
                    WHEN team_id IS NULL OR team_id <= 0
                        THEN error('agg_team_franchise: invalid team_id')
                    ELSE team_id
                END AS team_id,
                team_city,
                team_name,
                CAST(start_year AS INTEGER) AS start_year,
                CAST(end_year AS INTEGER) AS end_year,
                years,
                games,
                wins,
                losses,
                win_pct,
                po_appearances,
                div_titles,
                conf_titles,
                league_titles
            FROM stg_franchise
        ), franchise_authority AS (
            SELECT
                CASE
                    WHEN COUNT(DISTINCT ROW(
                        team_city,
                        team_name,
                        start_year,
                        end_year,
                        years,
                        games,
                        wins,
                        losses,
                        win_pct,
                        po_appearances,
                        div_titles,
                        conf_titles,
                        league_titles
                    )) = 1 THEN team_id
                    ELSE error('agg_team_franchise: conflicting projected rows')
                END AS team_id,
                MAX(team_city) AS team_city,
                MAX(team_name) AS team_name,
                MAX(start_year) AS start_year,
                MAX(end_year) AS end_year,
                MAX(years) AS years,
                MAX(games) AS games,
                MAX(wins) AS wins,
                MAX(losses) AS losses,
                MAX(win_pct) AS win_pct,
                MAX(po_appearances) AS po_appearances,
                MAX(div_titles) AS div_titles,
                MAX(conf_titles) AS conf_titles,
                MAX(league_titles) AS league_titles
            FROM franchise_rows
            GROUP BY team_id
        )
        SELECT
            team_id,
            team_city,
            team_name,
            start_year,
            end_year,
            years,
            games,
            wins,
            losses,
            win_pct,
            po_appearances,
            div_titles,
            conf_titles,
            league_titles,
            CASE
                WHEN start_year IS NULL OR end_year IS NULL THEN NULL
                WHEN end_year < start_year
                    THEN error('agg_team_franchise: end_year precedes start_year')
                ELSE end_year - start_year + 1
            END AS franchise_age_years,
            CASE WHEN games > 0
                 THEN ROUND(wins * 1.0 / games, 3)
                 ELSE NULL
            END AS computed_win_pct
        FROM franchise_authority
        ORDER BY team_id
    """
