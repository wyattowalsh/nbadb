from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactLeaguePlayerOnDetailsTransformer(SqlTransformer):
    """Publish one lossless row per team/player on-off scope."""

    output_table: ClassVar[str] = "fact_league_player_on_details"
    depends_on: ClassVar[list[str]] = ["stg_player_on_details"]

    _SQL: ClassVar[str] = """
        WITH source_unique AS (
            SELECT DISTINCT *
            FROM stg_player_on_details
        ),
        source_authority AS (
            SELECT
                CASE
                    WHEN group_set IS NULL OR trim(group_set) = ''
                      OR team_id IS NULL
                      OR vs_player_id IS NULL
                      OR court_status IS NULL OR trim(court_status) = ''
                      OR season_year IS NULL OR trim(season_year) = ''
                      OR season_type IS NULL OR trim(season_type) = ''
                        THEN error(
                            'fact_league_player_on_details: missing natural-key field'
                        )
                    WHEN COUNT(*) OVER (
                        PARTITION BY
                            group_set,
                            team_id,
                            vs_player_id,
                            court_status,
                            season_year,
                            season_type
                    ) = 1
                        THEN group_set
                    ELSE error(
                        'fact_league_player_on_details: conflicting distinct payloads '
                        'at natural key'
                    )
                END AS group_set,
                * EXCLUDE (group_set)
            FROM source_unique
        )
        SELECT
            group_set,
            team_id,
            team_abbreviation,
            team_name,
            vs_player_id,
            vs_player_name,
            court_status,
            gp,
            w,
            l,
            w_pct,
            min,
            fgm,
            fga,
            fg_pct,
            fg3m,
            fg3a,
            fg3_pct,
            ftm,
            fta,
            ft_pct,
            oreb,
            dreb,
            reb,
            ast,
            tov,
            stl,
            blk,
            blka,
            pf,
            pfd,
            pts,
            plus_minus,
            gp_rank,
            w_rank,
            l_rank,
            w_pct_rank,
            min_rank,
            fgm_rank,
            fga_rank,
            fg_pct_rank,
            fg3m_rank,
            fg3a_rank,
            fg3_pct_rank,
            ftm_rank,
            fta_rank,
            ft_pct_rank,
            oreb_rank,
            dreb_rank,
            reb_rank,
            ast_rank,
            tov_rank,
            stl_rank,
            blk_rank,
            blka_rank,
            pf_rank,
            pfd_rank,
            pts_rank,
            plus_minus_rank,
            season_year,
            season_type
        FROM source_authority
    """


__all__ = ["FactLeaguePlayerOnDetailsTransformer"]
