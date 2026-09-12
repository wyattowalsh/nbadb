from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class FactTeamOnOffOverallTransformer(SqlTransformer):
    """Reconcile the duplicate team-overall packets from both on/off endpoints."""

    output_table: ClassVar[str] = "fact_team_on_off_overall"
    depends_on: ClassVar[list[str]] = [
        "stg_team_dashboard_on_off",
        "stg_on_off",
    ]

    _SQL: ClassVar[str] = """
        WITH detail_distinct AS (
            SELECT DISTINCT
                group_set, group_value, team_id, team_abbreviation, team_name,
                season_year, season_type,
                gp, w, l, w_pct, min,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
                oreb, dreb, reb, ast, tov, stl, blk, blka, pf, pfd, pts, plus_minus,
                gp_rank, w_rank, l_rank, w_pct_rank, min_rank,
                fgm_rank, fga_rank, fg_pct_rank,
                fg3m_rank, fg3a_rank, fg3_pct_rank,
                ftm_rank, fta_rank, ft_pct_rank,
                oreb_rank, dreb_rank, reb_rank, ast_rank, tov_rank, stl_rank,
                blk_rank, blka_rank, pf_rank, pfd_rank, pts_rank, plus_minus_rank
            FROM stg_team_dashboard_on_off
        ),
        detail AS (
            SELECT *, COUNT(*) OVER (
                PARTITION BY team_id, season_year, season_type, group_set, group_value
            ) AS key_versions
            FROM detail_distinct
        ),
        summary_distinct AS (
            SELECT DISTINCT
                group_set, group_value, team_id, team_abbreviation, team_name,
                season_year, season_type,
                gp, w, l, w_pct, min,
                fgm, fga, fg_pct, fg3m, fg3a, fg3_pct, ftm, fta, ft_pct,
                oreb, dreb, reb, ast, tov, stl, blk, blka, pf, pfd, pts, plus_minus,
                gp_rank, w_rank, l_rank, w_pct_rank, min_rank,
                fgm_rank, fga_rank, fg_pct_rank,
                fg3m_rank, fg3a_rank, fg3_pct_rank,
                ftm_rank, fta_rank, ft_pct_rank,
                oreb_rank, dreb_rank, reb_rank, ast_rank, tov_rank, stl_rank,
                blk_rank, blka_rank, pf_rank, pfd_rank, pts_rank, plus_minus_rank
            FROM stg_on_off
        ),
        summary AS (
            SELECT *, COUNT(*) OVER (
                PARTITION BY team_id, season_year, season_type, group_set, group_value
            ) AS key_versions
            FROM summary_distinct
        ),
        joined AS (
            SELECT
                d.team_id AS detail_team_id,
                s.team_id AS summary_team_id,
                s.season_year AS summary_season_year,
                s.season_type AS summary_season_type,
                s.group_set AS summary_group_set,
                s.group_value AS summary_group_value,
                d.key_versions AS detail_key_versions,
                s.key_versions AS summary_key_versions,
                d.* EXCLUDE (team_id, key_versions),
                s.* EXCLUDE (
                    team_id, season_year, season_type, group_set, group_value, key_versions
                ) RENAME (
                    team_abbreviation AS summary_team_abbreviation,
                    team_name AS summary_team_name,
                    gp AS summary_gp,
                    w AS summary_w,
                    l AS summary_l,
                    w_pct AS summary_w_pct,
                    min AS summary_min,
                    fgm AS summary_fgm,
                    fga AS summary_fga,
                    fg_pct AS summary_fg_pct,
                    fg3m AS summary_fg3m,
                    fg3a AS summary_fg3a,
                    fg3_pct AS summary_fg3_pct,
                    ftm AS summary_ftm,
                    fta AS summary_fta,
                    ft_pct AS summary_ft_pct,
                    oreb AS summary_oreb,
                    dreb AS summary_dreb,
                    reb AS summary_reb,
                    ast AS summary_ast,
                    tov AS summary_tov,
                    stl AS summary_stl,
                    blk AS summary_blk,
                    blka AS summary_blka,
                    pf AS summary_pf,
                    pfd AS summary_pfd,
                    pts AS summary_pts,
                    plus_minus AS summary_plus_minus,
                    gp_rank AS summary_gp_rank,
                    w_rank AS summary_w_rank,
                    l_rank AS summary_l_rank,
                    w_pct_rank AS summary_w_pct_rank,
                    min_rank AS summary_min_rank,
                    fgm_rank AS summary_fgm_rank,
                    fga_rank AS summary_fga_rank,
                    fg_pct_rank AS summary_fg_pct_rank,
                    fg3m_rank AS summary_fg3m_rank,
                    fg3a_rank AS summary_fg3a_rank,
                    fg3_pct_rank AS summary_fg3_pct_rank,
                    ftm_rank AS summary_ftm_rank,
                    fta_rank AS summary_fta_rank,
                    ft_pct_rank AS summary_ft_pct_rank,
                    oreb_rank AS summary_oreb_rank,
                    dreb_rank AS summary_dreb_rank,
                    reb_rank AS summary_reb_rank,
                    ast_rank AS summary_ast_rank,
                    tov_rank AS summary_tov_rank,
                    stl_rank AS summary_stl_rank,
                    blk_rank AS summary_blk_rank,
                    blka_rank AS summary_blka_rank,
                    pf_rank AS summary_pf_rank,
                    pfd_rank AS summary_pfd_rank,
                    pts_rank AS summary_pts_rank,
                    plus_minus_rank AS summary_plus_minus_rank
                )
            FROM detail d
            FULL OUTER JOIN summary s
                ON d.team_id = s.team_id
                AND d.season_year = s.season_year
                AND d.season_type = s.season_type
                AND d.group_set IS NOT DISTINCT FROM s.group_set
                AND d.group_value IS NOT DISTINCT FROM s.group_value
        ),
        reconciled AS (
            SELECT
                '00' AS league_id,
                COALESCE(detail_team_id, summary_team_id) AS team_id,
                COALESCE(season_year, summary_season_year) AS season_year,
                COALESCE(season_type, summary_season_type) AS season_type,
                COALESCE(group_set, summary_group_set) AS group_set,
                COALESCE(group_value, summary_group_value) AS group_value,
                COALESCE(team_abbreviation, summary_team_abbreviation) AS team_abbreviation,
                COALESCE(team_name, summary_team_name) AS team_name,
                0 AS request_last_n_games,
                'Base' AS request_measure_type,
                0 AS request_month,
                0 AS request_opponent_team_id,
                'N' AS request_pace_adjust,
                'Totals' AS request_per_mode,
                0 AS request_period,
                'N' AS request_plus_minus,
                'N' AS request_rank,
                NULL::VARCHAR AS request_date_from,
                NULL::VARCHAR AS request_date_to,
                NULL::VARCHAR AS request_game_segment,
                NULL::VARCHAR AS request_location,
                NULL::VARCHAR AS request_outcome,
                NULL::VARCHAR AS request_season_segment,
                NULL::VARCHAR AS request_vs_conference,
                NULL::VARCHAR AS request_vs_division,
                COALESCE(gp, summary_gp) AS gp,
                COALESCE(w, summary_w) AS w,
                COALESCE(l, summary_l) AS l,
                COALESCE(w_pct, summary_w_pct) AS provider_w_pct,
                COALESCE(min, summary_min) AS min,
                COALESCE(fgm, summary_fgm) AS fgm,
                COALESCE(fga, summary_fga) AS fga,
                COALESCE(fg_pct, summary_fg_pct) AS provider_fg_pct,
                COALESCE(fg3m, summary_fg3m) AS fg3m,
                COALESCE(fg3a, summary_fg3a) AS fg3a,
                COALESCE(fg3_pct, summary_fg3_pct) AS provider_fg3_pct,
                COALESCE(ftm, summary_ftm) AS ftm,
                COALESCE(fta, summary_fta) AS fta,
                COALESCE(ft_pct, summary_ft_pct) AS provider_ft_pct,
                COALESCE(oreb, summary_oreb) AS oreb,
                COALESCE(dreb, summary_dreb) AS dreb,
                COALESCE(reb, summary_reb) AS reb,
                COALESCE(ast, summary_ast) AS ast,
                COALESCE(tov, summary_tov) AS tov,
                COALESCE(stl, summary_stl) AS stl,
                COALESCE(blk, summary_blk) AS blk,
                COALESCE(blka, summary_blka) AS blka,
                COALESCE(pf, summary_pf) AS pf,
                COALESCE(pfd, summary_pfd) AS pfd,
                COALESCE(pts, summary_pts) AS pts,
                COALESCE(plus_minus, summary_plus_minus) AS plus_minus,
                COALESCE(gp_rank, summary_gp_rank) AS gp_rank,
                COALESCE(w_rank, summary_w_rank) AS w_rank,
                COALESCE(l_rank, summary_l_rank) AS l_rank,
                COALESCE(w_pct_rank, summary_w_pct_rank) AS w_pct_rank,
                COALESCE(min_rank, summary_min_rank) AS min_rank,
                COALESCE(fgm_rank, summary_fgm_rank) AS fgm_rank,
                COALESCE(fga_rank, summary_fga_rank) AS fga_rank,
                COALESCE(fg_pct_rank, summary_fg_pct_rank) AS fg_pct_rank,
                COALESCE(fg3m_rank, summary_fg3m_rank) AS fg3m_rank,
                COALESCE(fg3a_rank, summary_fg3a_rank) AS fg3a_rank,
                COALESCE(fg3_pct_rank, summary_fg3_pct_rank) AS fg3_pct_rank,
                COALESCE(ftm_rank, summary_ftm_rank) AS ftm_rank,
                COALESCE(fta_rank, summary_fta_rank) AS fta_rank,
                COALESCE(ft_pct_rank, summary_ft_pct_rank) AS ft_pct_rank,
                COALESCE(oreb_rank, summary_oreb_rank) AS oreb_rank,
                COALESCE(dreb_rank, summary_dreb_rank) AS dreb_rank,
                COALESCE(reb_rank, summary_reb_rank) AS reb_rank,
                COALESCE(ast_rank, summary_ast_rank) AS ast_rank,
                COALESCE(tov_rank, summary_tov_rank) AS tov_rank,
                COALESCE(stl_rank, summary_stl_rank) AS stl_rank,
                COALESCE(blk_rank, summary_blk_rank) AS blk_rank,
                COALESCE(blka_rank, summary_blka_rank) AS blka_rank,
                COALESCE(pf_rank, summary_pf_rank) AS pf_rank,
                COALESCE(pfd_rank, summary_pfd_rank) AS pfd_rank,
                COALESCE(pts_rank, summary_pts_rank) AS pts_rank,
                COALESCE(plus_minus_rank, summary_plus_minus_rank) AS plus_minus_rank,
                detail_team_id IS NOT NULL AS detail_source_present,
                summary_team_id IS NOT NULL AS summary_source_present,
                CASE
                    WHEN detail_key_versions > 1
                        THEN error('conflicting duplicate details on/off overall rows')
                    WHEN summary_key_versions > 1
                        THEN error('conflicting duplicate summary on/off overall rows')
                    WHEN detail_team_id IS NOT NULL AND summary_team_id IS NOT NULL AND (
                        team_abbreviation IS DISTINCT FROM summary_team_abbreviation
                        OR team_name IS DISTINCT FROM summary_team_name
                        OR gp IS DISTINCT FROM summary_gp
                        OR w IS DISTINCT FROM summary_w
                        OR l IS DISTINCT FROM summary_l
                        OR w_pct IS DISTINCT FROM summary_w_pct
                        OR min IS DISTINCT FROM summary_min
                        OR fgm IS DISTINCT FROM summary_fgm
                        OR fga IS DISTINCT FROM summary_fga
                        OR fg_pct IS DISTINCT FROM summary_fg_pct
                        OR fg3m IS DISTINCT FROM summary_fg3m
                        OR fg3a IS DISTINCT FROM summary_fg3a
                        OR fg3_pct IS DISTINCT FROM summary_fg3_pct
                        OR ftm IS DISTINCT FROM summary_ftm
                        OR fta IS DISTINCT FROM summary_fta
                        OR ft_pct IS DISTINCT FROM summary_ft_pct
                        OR oreb IS DISTINCT FROM summary_oreb
                        OR dreb IS DISTINCT FROM summary_dreb
                        OR reb IS DISTINCT FROM summary_reb
                        OR ast IS DISTINCT FROM summary_ast
                        OR tov IS DISTINCT FROM summary_tov
                        OR stl IS DISTINCT FROM summary_stl
                        OR blk IS DISTINCT FROM summary_blk
                        OR blka IS DISTINCT FROM summary_blka
                        OR pf IS DISTINCT FROM summary_pf
                        OR pfd IS DISTINCT FROM summary_pfd
                        OR pts IS DISTINCT FROM summary_pts
                        OR plus_minus IS DISTINCT FROM summary_plus_minus
                        OR gp_rank IS DISTINCT FROM summary_gp_rank
                        OR w_rank IS DISTINCT FROM summary_w_rank
                        OR l_rank IS DISTINCT FROM summary_l_rank
                        OR w_pct_rank IS DISTINCT FROM summary_w_pct_rank
                        OR min_rank IS DISTINCT FROM summary_min_rank
                        OR fgm_rank IS DISTINCT FROM summary_fgm_rank
                        OR fga_rank IS DISTINCT FROM summary_fga_rank
                        OR fg_pct_rank IS DISTINCT FROM summary_fg_pct_rank
                        OR fg3m_rank IS DISTINCT FROM summary_fg3m_rank
                        OR fg3a_rank IS DISTINCT FROM summary_fg3a_rank
                        OR fg3_pct_rank IS DISTINCT FROM summary_fg3_pct_rank
                        OR ftm_rank IS DISTINCT FROM summary_ftm_rank
                        OR fta_rank IS DISTINCT FROM summary_fta_rank
                        OR ft_pct_rank IS DISTINCT FROM summary_ft_pct_rank
                        OR oreb_rank IS DISTINCT FROM summary_oreb_rank
                        OR dreb_rank IS DISTINCT FROM summary_dreb_rank
                        OR reb_rank IS DISTINCT FROM summary_reb_rank
                        OR ast_rank IS DISTINCT FROM summary_ast_rank
                        OR tov_rank IS DISTINCT FROM summary_tov_rank
                        OR stl_rank IS DISTINCT FROM summary_stl_rank
                        OR blk_rank IS DISTINCT FROM summary_blk_rank
                        OR blka_rank IS DISTINCT FROM summary_blka_rank
                        OR pf_rank IS DISTINCT FROM summary_pf_rank
                        OR pfd_rank IS DISTINCT FROM summary_pfd_rank
                        OR pts_rank IS DISTINCT FROM summary_pts_rank
                        OR plus_minus_rank IS DISTINCT FROM summary_plus_minus_rank
                    ) THEN error('details and summary on/off overall packets conflict')
                    WHEN detail_team_id IS NOT NULL AND summary_team_id IS NOT NULL
                        THEN 'both_exact_match'
                    WHEN detail_team_id IS NOT NULL THEN 'details_only'
                    ELSE 'summary_only'
                END AS reconciliation_status,
                CASE WHEN detail_team_id IS NOT NULL
                    THEN 'OverallTeamPlayerOnOffDetails' END AS source_detail_result_set,
                CASE WHEN summary_team_id IS NOT NULL
                    THEN 'OverallTeamPlayerOnOffSummary' END AS source_summary_result_set
            FROM joined
        )
        SELECT
            * EXCLUDE (provider_w_pct, provider_fg_pct, provider_fg3_pct, provider_ft_pct),
            provider_w_pct,
            CASE WHEN COALESCE(w, 0) + COALESCE(l, 0) > 0
                THEN w::DOUBLE / (w + l) END AS w_pct,
            provider_fg_pct,
            CASE WHEN fga > 0 THEN fgm / fga END AS fg_pct,
            provider_fg3_pct,
            CASE WHEN fg3a > 0 THEN fg3m / fg3a END AS fg3_pct,
            provider_ft_pct,
            CASE WHEN fta > 0 THEN ftm / fta END AS ft_pct,
            CASE WHEN fga > 0 THEN (fgm + 0.5 * fg3m) / fga END AS efg_pct,
            CASE WHEN fga + 0.44 * fta > 0
                THEN pts / (2 * (fga + 0.44 * fta)) END AS ts_pct,
            CASE WHEN fga + 0.44 * fta - oreb + tov >= 0
                THEN fga + 0.44 * fta - oreb + tov END AS estimated_possessions,
            CASE WHEN fga + 0.44 * fta - oreb + tov > 0
                THEN 100 * pts / (fga + 0.44 * fta - oreb + tov)
                END AS pts_per_100_estimated_possessions,
            CASE WHEN tov > 0 THEN ast / tov END AS ast_to_ratio
        FROM reconciled
    """
