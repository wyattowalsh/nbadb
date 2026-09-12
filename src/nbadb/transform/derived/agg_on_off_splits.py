from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggOnOffSplitsTransformer(SqlTransformer):
    """Reconcile provider player on/off detail and summary packets."""

    output_table: ClassVar[str] = "agg_on_off_splits"
    depends_on: ClassVar[list[str]] = [
        "stg_on_off_details_overall",
        "stg_on_off_details_off_court",
        "stg_on_off_details_on_court",
        "stg_on_off_summary_off_court",
        "stg_on_off_summary_on_court",
    ]

    _SQL: ClassVar[str] = """
        WITH summary_distinct AS (
            SELECT DISTINCT
                vs_player_id AS entity_id,
                team_id,
                season_year,
                season_type,
                'Off' AS on_off,
                gp,
                min,
                plus_minus,
                off_rating,
                def_rating,
                net_rating
            FROM stg_on_off_summary_off_court
            WHERE vs_player_id IS NOT NULL
            UNION ALL
            SELECT DISTINCT
                vs_player_id AS entity_id,
                team_id,
                season_year,
                season_type,
                'On' AS on_off,
                gp,
                min,
                plus_minus,
                off_rating,
                def_rating,
                net_rating
            FROM stg_on_off_summary_on_court
            WHERE vs_player_id IS NOT NULL
        ),
        summary AS (
            SELECT
                entity_id,
                team_id,
                season_year,
                season_type,
                on_off,
                CASE WHEN COUNT(*) > 1
                    THEN error('conflicting provider on/off summary rows')
                    ELSE MIN(gp) END AS summary_gp,
                MIN(min) AS summary_min,
                MIN(plus_minus) AS summary_plus_minus,
                MIN(off_rating) AS summary_off_rating,
                MIN(def_rating) AS summary_def_rating,
                MIN(net_rating) AS summary_net_rating
            FROM summary_distinct
            GROUP BY entity_id, team_id, season_year, season_type, on_off
        ),
        detail_distinct AS (
            SELECT DISTINCT
                vs_player_id AS entity_id,
                team_id,
                season_year,
                season_type,
                'Off' AS on_off,
                gp,
                min,
                w,
                l,
                w_pct,
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
                plus_minus
            FROM stg_on_off_details_off_court
            WHERE vs_player_id IS NOT NULL
            UNION ALL
            SELECT DISTINCT
                vs_player_id AS entity_id,
                team_id,
                season_year,
                season_type,
                'On' AS on_off,
                gp,
                min,
                w,
                l,
                w_pct,
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
                plus_minus
            FROM stg_on_off_details_on_court
            WHERE vs_player_id IS NOT NULL
        ),
        detail AS (
            SELECT
                entity_id,
                team_id,
                season_year,
                season_type,
                on_off,
                CASE WHEN COUNT(*) > 1
                    THEN error('conflicting provider on/off detail rows')
                    ELSE MIN(gp) END AS detail_gp,
                MIN(min) AS detail_min,
                MIN(w) AS w,
                MIN(l) AS l,
                MIN(w_pct) AS w_pct,
                MIN(fgm) AS fgm,
                MIN(fga) AS fga,
                MIN(fg_pct) AS provider_fg_pct,
                MIN(fg3m) AS fg3m,
                MIN(fg3a) AS fg3a,
                MIN(fg3_pct) AS provider_fg3_pct,
                MIN(ftm) AS ftm,
                MIN(fta) AS fta,
                MIN(ft_pct) AS provider_ft_pct,
                MIN(oreb) AS oreb,
                MIN(dreb) AS dreb,
                MIN(reb) AS reb,
                MIN(ast) AS ast,
                MIN(tov) AS tov,
                MIN(stl) AS stl,
                MIN(blk) AS blk,
                MIN(blka) AS blka,
                MIN(pf) AS pf,
                MIN(pfd) AS pfd,
                MIN(pts) AS pts,
                MIN(plus_minus) AS detail_plus_minus
            FROM detail_distinct
            GROUP BY entity_id, team_id, season_year, season_type, on_off
        ),
        player_base AS (
            SELECT
                COALESCE(s.entity_id, d.entity_id) AS entity_id,
                COALESCE(s.team_id, d.team_id) AS team_id,
                COALESCE(s.season_year, d.season_year) AS season_year,
                COALESCE(s.season_type, d.season_type) AS season_type,
                COALESCE(s.on_off, d.on_off) AS on_off,
                CASE WHEN s.summary_gp IS NOT NULL
                    AND d.detail_gp IS NOT NULL
                    AND s.summary_gp IS DISTINCT FROM d.detail_gp
                    THEN error('conflicting provider on/off summary/detail gp')
                    ELSE COALESCE(s.summary_gp, d.detail_gp)
                END AS reconciled_gp,
                CASE WHEN s.summary_min IS NOT NULL
                    AND d.detail_min IS NOT NULL
                    AND s.summary_min IS DISTINCT FROM d.detail_min
                    THEN error('conflicting provider on/off summary/detail min')
                    ELSE COALESCE(s.summary_min, d.detail_min)
                END AS reconciled_min,
                d.w,
                d.l,
                d.w_pct,
                d.fgm,
                d.fga,
                d.provider_fg_pct,
                d.fg3m,
                d.fg3a,
                d.provider_fg3_pct,
                d.ftm,
                d.fta,
                d.provider_ft_pct,
                d.oreb,
                d.dreb,
                d.reb,
                d.ast,
                d.tov,
                d.stl,
                d.blk,
                d.blka,
                d.pf,
                d.pfd,
                d.pts,
                CASE WHEN s.summary_plus_minus IS NOT NULL
                    AND d.detail_plus_minus IS NOT NULL
                    AND s.summary_plus_minus IS DISTINCT FROM d.detail_plus_minus
                    THEN error('conflicting provider on/off summary/detail plus_minus')
                    ELSE COALESCE(s.summary_plus_minus, d.detail_plus_minus)
                END AS reconciled_plus_minus,
                s.summary_off_rating AS off_rating,
                s.summary_def_rating AS def_rating,
                s.summary_net_rating AS net_rating
            FROM summary s
            FULL OUTER JOIN detail d
                USING (entity_id, team_id, season_year, season_type, on_off)
        ),
        player_paired AS (
            SELECT
                p.*,
                on_row.reconciled_gp AS on_gp,
                off_row.reconciled_gp AS off_gp,
                on_row.reconciled_min AS on_min,
                off_row.reconciled_min AS off_min,
                on_row.off_rating - off_row.off_rating AS off_rating_diff,
                on_row.def_rating - off_row.def_rating AS def_rating_diff,
                on_row.net_rating - off_row.net_rating AS net_rating_diff,
                on_row.reconciled_plus_minus - off_row.reconciled_plus_minus
                    AS plus_minus_diff,
                on_row.entity_id IS NOT NULL AND off_row.entity_id IS NOT NULL
                    AS on_off_pair_complete
            FROM player_base p
            LEFT JOIN player_base on_row
                ON p.entity_id = on_row.entity_id
                AND p.team_id = on_row.team_id
                AND p.season_year = on_row.season_year
                AND p.season_type = on_row.season_type
                AND on_row.on_off = 'On'
            LEFT JOIN player_base off_row
                ON p.entity_id = off_row.entity_id
                AND p.team_id = off_row.team_id
                AND p.season_year = off_row.season_year
                AND p.season_type = off_row.season_type
                AND off_row.on_off = 'Off'
        ),
        team_distinct AS (
            SELECT DISTINCT
                team_id,
                season_year,
                season_type,
                gp,
                min,
                w,
                l,
                w_pct,
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
                plus_minus
            FROM stg_on_off_details_overall
        ),
        team_overall AS (
            SELECT
                team_id,
                season_year,
                season_type,
                CASE WHEN COUNT(*) > 1
                    THEN error('conflicting provider team on/off overall rows')
                    ELSE MIN(gp) END AS team_overall_gp,
                MIN(min) AS team_overall_min,
                MIN(w) AS w,
                MIN(l) AS l,
                MIN(w_pct) AS w_pct,
                MIN(fgm) AS fgm,
                MIN(fga) AS fga,
                MIN(fg_pct) AS provider_fg_pct,
                MIN(fg3m) AS fg3m,
                MIN(fg3a) AS fg3a,
                MIN(fg3_pct) AS provider_fg3_pct,
                MIN(ftm) AS ftm,
                MIN(fta) AS fta,
                MIN(ft_pct) AS provider_ft_pct,
                MIN(oreb) AS oreb,
                MIN(dreb) AS dreb,
                MIN(reb) AS reb,
                MIN(ast) AS ast,
                MIN(tov) AS tov,
                MIN(stl) AS stl,
                MIN(blk) AS blk,
                MIN(blka) AS blka,
                MIN(pf) AS pf,
                MIN(pfd) AS pfd,
                MIN(pts) AS pts,
                MIN(plus_minus) AS team_overall_plus_minus
            FROM team_distinct
            GROUP BY team_id, season_year, season_type
        ),
        output_measures AS (
            SELECT
                'player' AS entity_type,
                'reconciled_summary_detail' AS source_kind,
                entity_id,
                team_id,
                season_year,
                season_type,
                on_off,
                reconciled_gp AS gp,
                reconciled_min AS min,
                w,
                l,
                w_pct,
                fgm,
                fga,
                provider_fg_pct,
                fg3m,
                fg3a,
                provider_fg3_pct,
                ftm,
                fta,
                provider_ft_pct,
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
                reconciled_plus_minus AS plus_minus,
                off_rating,
                def_rating,
                net_rating,
                on_off_pair_complete,
                on_gp,
                off_gp,
                on_min,
                off_min,
                off_rating_diff,
                def_rating_diff,
                net_rating_diff,
                plus_minus_diff
            FROM player_paired
            UNION ALL BY NAME
            SELECT
                'player_detail' AS entity_type,
                'provider_detail' AS source_kind,
                entity_id,
                team_id,
                season_year,
                season_type,
                on_off,
                detail_gp AS gp,
                detail_min AS min,
                w,
                l,
                w_pct,
                fgm,
                fga,
                provider_fg_pct,
                fg3m,
                fg3a,
                provider_fg3_pct,
                ftm,
                fta,
                provider_ft_pct,
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
                detail_plus_minus AS plus_minus,
                NULL::DOUBLE AS off_rating,
                NULL::DOUBLE AS def_rating,
                NULL::DOUBLE AS net_rating,
                NULL::BOOLEAN AS on_off_pair_complete,
                NULL::INTEGER AS on_gp,
                NULL::INTEGER AS off_gp,
                NULL::DOUBLE AS on_min,
                NULL::DOUBLE AS off_min,
                NULL::DOUBLE AS off_rating_diff,
                NULL::DOUBLE AS def_rating_diff,
                NULL::DOUBLE AS net_rating_diff,
                NULL::DOUBLE AS plus_minus_diff
            FROM detail
            UNION ALL BY NAME
            SELECT
                'team' AS entity_type,
                'provider_detail_overall' AS source_kind,
                team_id AS entity_id,
                team_id,
                season_year,
                season_type,
                'Overall' AS on_off,
                team_overall_gp AS gp,
                team_overall_min AS min,
                w,
                l,
                w_pct,
                fgm,
                fga,
                provider_fg_pct,
                fg3m,
                fg3a,
                provider_fg3_pct,
                ftm,
                fta,
                provider_ft_pct,
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
                team_overall_plus_minus AS plus_minus,
                NULL::DOUBLE AS off_rating,
                NULL::DOUBLE AS def_rating,
                NULL::DOUBLE AS net_rating,
                FALSE AS on_off_pair_complete,
                NULL::INTEGER AS on_gp,
                NULL::INTEGER AS off_gp,
                NULL::DOUBLE AS on_min,
                NULL::DOUBLE AS off_min,
                NULL::DOUBLE AS off_rating_diff,
                NULL::DOUBLE AS def_rating_diff,
                NULL::DOUBLE AS net_rating_diff,
                NULL::DOUBLE AS plus_minus_diff
            FROM team_overall
        )
        SELECT
            entity_type,
            source_kind,
            entity_id,
            team_id,
            season_year,
            season_type,
            on_off,
            gp,
            min,
            w,
            l,
            w_pct,
            fgm,
            fga,
            CASE WHEN fga > 0 THEN fgm / fga END AS fg_pct,
            provider_fg_pct,
            fg3m,
            fg3a,
            CASE WHEN fg3a > 0 THEN fg3m / fg3a END AS fg3_pct,
            provider_fg3_pct,
            ftm,
            fta,
            CASE WHEN fta > 0 THEN ftm / fta END AS ft_pct,
            provider_ft_pct,
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
            off_rating,
            def_rating,
            net_rating,
            CASE WHEN fga + 0.44 * fta > 0
                THEN pts / (2.0 * (fga + 0.44 * fta)) END AS ts_pct,
            CASE WHEN fga > 0 THEN (fgm + 0.5 * fg3m) / fga END AS efg_pct,
            CASE WHEN min > 0 THEN pts * 48.0 / min END AS pts_per48,
            CASE WHEN min > 0 THEN reb * 48.0 / min END AS reb_per48,
            CASE WHEN min > 0 THEN ast * 48.0 / min END AS ast_per48,
            on_off_pair_complete,
            on_gp,
            off_gp,
            on_min,
            off_min,
            off_rating_diff,
            def_rating_diff,
            net_rating_diff,
            plus_minus_diff
        FROM output_measures
    """
