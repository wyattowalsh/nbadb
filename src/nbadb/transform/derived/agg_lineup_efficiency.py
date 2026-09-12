from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggLineupEfficiencyTransformer(SqlTransformer):
    """Project one canonical lineup fact into metric-local totals and rates."""

    output_table: ClassVar[str] = "agg_lineup_efficiency"
    depends_on: ClassVar[list[str]] = ["fact_lineup_stats"]

    _SQL: ClassVar[str] = """
        WITH projected_payload AS (
            SELECT
                group_id,
                team_id,
                season_year,
                season_type,
                lineup_source,
                lineup_source_count::BIGINT AS lineup_source_count,
                lineup_source_coverage,
                gp::BIGINT AS gp,
                w::BIGINT AS w,
                l::BIGINT AS l,
                min::DOUBLE AS min,
                fgm::BIGINT AS fgm,
                fga::BIGINT AS fga,
                fg3m::BIGINT AS fg3m,
                fg3a::BIGINT AS fg3a,
                ftm::BIGINT AS ftm,
                fta::BIGINT AS fta,
                oreb::BIGINT AS oreb,
                dreb::BIGINT AS dreb,
                reb::BIGINT AS reb,
                ast::BIGINT AS ast,
                tov::BIGINT AS tov,
                stl::BIGINT AS stl,
                blk::BIGINT AS blk,
                blka::BIGINT AS blka,
                pf::BIGINT AS pf,
                pfd::BIGINT AS pfd,
                pts::BIGINT AS pts,
                plus_minus::DOUBLE AS plus_minus
            FROM fact_lineup_stats
        ),
        exact_unique AS (
            SELECT DISTINCT *
            FROM projected_payload
        ),
        guarded AS (
            SELECT
                *,
                COUNT(*) OVER (
                    PARTITION BY group_id, team_id, season_year, season_type
                ) AS key_row_count,
                CASE
                    WHEN fga IS NOT NULL
                        AND fta IS NOT NULL
                        AND oreb IS NOT NULL
                        AND tov IS NOT NULL
                        THEN fga::DOUBLE + 0.44::DOUBLE * fta::DOUBLE
                            - oreb::DOUBLE + tov::DOUBLE
                    ELSE NULL
                END AS estimated_possessions_value
            FROM exact_unique
        )
        SELECT
            CASE
                WHEN group_id IS NULL
                    OR regexp_matches(group_id, '^[[:space:]]*$')
                    OR team_id IS NULL
                    OR team_id <= 0
                    OR season_year IS NULL
                    OR regexp_matches(season_year, '^[[:space:]]*$')
                    OR season_type IS NULL
                    OR regexp_matches(season_type, '^[[:space:]]*$')
                    THEN error(
                        'agg_lineup_efficiency: null, blank, or nonpositive key'
                    )
                WHEN key_row_count <> 1
                    THEN error(
                        'agg_lineup_efficiency: conflicting consumed fields for one key'
                    )
                ELSE group_id
            END AS group_id,
            team_id,
            season_year,
            season_type,
            CASE
                WHEN key_row_count <> 1
                    THEN error(
                        'agg_lineup_efficiency: conflicting consumed fields for one key'
                    )
                WHEN lineup_source = 'league'
                    AND lineup_source_count = 1
                    AND lineup_source_coverage = 'league'
                    THEN lineup_source
                WHEN lineup_source = 'team'
                    AND lineup_source_count = 1
                    AND lineup_source_coverage = 'team'
                    THEN lineup_source
                WHEN lineup_source = 'league'
                    AND lineup_source_count = 2
                    AND lineup_source_coverage = 'league+team'
                    THEN lineup_source
                ELSE error(
                    'agg_lineup_efficiency: invalid canonical source tuple'
                )
            END AS lineup_source,
            lineup_source_count,
            lineup_source_coverage,
            1::BIGINT AS canonical_observation_count,
            CASE WHEN gp IS NOT NULL THEN 1 ELSE 0 END::BIGINT
                AS gp_covered_observations,
            CASE WHEN min IS NOT NULL THEN 1 ELSE 0 END::BIGINT
                AS minutes_covered_observations,
            CASE
                WHEN fga IS NOT NULL
                    AND fta IS NOT NULL
                    AND oreb IS NOT NULL
                    AND tov IS NOT NULL
                    THEN 1
                ELSE 0
            END::BIGINT AS estimated_possessions_covered_observations,
            CASE
                WHEN w IS NOT NULL AND gp IS NOT NULL AND gp > 0 THEN 1
                ELSE 0
            END::BIGINT AS win_pct_covered_observations,
            CASE
                WHEN fgm IS NOT NULL AND fga IS NOT NULL AND fga > 0 THEN 1
                ELSE 0
            END::BIGINT AS fg_pct_covered_observations,
            CASE
                WHEN fg3m IS NOT NULL AND fg3a IS NOT NULL AND fg3a > 0 THEN 1
                ELSE 0
            END::BIGINT AS fg3_pct_covered_observations,
            CASE
                WHEN ftm IS NOT NULL AND fta IS NOT NULL AND fta > 0 THEN 1
                ELSE 0
            END::BIGINT AS ft_pct_covered_observations,
            CASE
                WHEN fgm IS NOT NULL
                    AND fg3m IS NOT NULL
                    AND fga IS NOT NULL
                    AND fga > 0
                    THEN 1
                ELSE 0
            END::BIGINT AS efg_pct_covered_observations,
            CASE
                WHEN pts IS NOT NULL
                    AND fga IS NOT NULL
                    AND fta IS NOT NULL
                    AND 2.0::DOUBLE * (fga::DOUBLE + 0.44::DOUBLE * fta::DOUBLE) > 0
                    THEN 1
                ELSE 0
            END::BIGINT AS ts_pct_covered_observations,
            CASE
                WHEN fg3a IS NOT NULL AND fga IS NOT NULL AND fga > 0 THEN 1
                ELSE 0
            END::BIGINT AS fg3a_per_fga_covered_observations,
            CASE
                WHEN fta IS NOT NULL AND fga IS NOT NULL AND fga > 0 THEN 1
                ELSE 0
            END::BIGINT AS fta_per_fga_covered_observations,
            CASE
                WHEN ast IS NOT NULL AND tov IS NOT NULL AND tov > 0 THEN 1
                ELSE 0
            END::BIGINT AS ast_tov_ratio_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND pts IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS pts_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND reb IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS reb_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND ast IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS ast_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND tov IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS tov_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND stl IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS stl_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND blk IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS blk_per48_covered_observations,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND plus_minus IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS plus_minus_per48_covered_observations,
            CASE
                WHEN estimated_possessions_value > 0 AND pts IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS estimated_off_rating_covered_observations,
            CASE
                WHEN estimated_possessions_value > 0
                    AND pts IS NOT NULL
                    AND plus_minus IS NOT NULL
                    THEN 1
                ELSE 0
            END::BIGINT AS estimated_def_rating_covered_observations,
            CASE
                WHEN estimated_possessions_value > 0 AND plus_minus IS NOT NULL THEN 1
                ELSE 0
            END::BIGINT AS estimated_net_rating_covered_observations,
            gp AS total_gp,
            w AS total_w,
            l AS total_l,
            min AS total_min,
            fgm AS total_fgm,
            fga AS total_fga,
            fg3m AS total_fg3m,
            fg3a AS total_fg3a,
            ftm AS total_ftm,
            fta AS total_fta,
            oreb AS total_oreb,
            dreb AS total_dreb,
            reb AS total_reb,
            ast AS total_ast,
            tov AS total_tov,
            stl AS total_stl,
            blk AS total_blk,
            blka AS total_blka,
            pf AS total_pf,
            pfd AS total_pfd,
            pts AS total_pts,
            plus_minus AS total_plus_minus,
            CASE
                WHEN w IS NOT NULL AND gp IS NOT NULL AND gp > 0
                    THEN w::DOUBLE / gp::DOUBLE
                ELSE NULL
            END AS win_pct,
            CASE
                WHEN fgm IS NOT NULL AND fga IS NOT NULL AND fga > 0
                    THEN fgm::DOUBLE / fga::DOUBLE
                ELSE NULL
            END AS fg_pct,
            CASE
                WHEN fg3m IS NOT NULL AND fg3a IS NOT NULL AND fg3a > 0
                    THEN fg3m::DOUBLE / fg3a::DOUBLE
                ELSE NULL
            END AS fg3_pct,
            CASE
                WHEN ftm IS NOT NULL AND fta IS NOT NULL AND fta > 0
                    THEN ftm::DOUBLE / fta::DOUBLE
                ELSE NULL
            END AS ft_pct,
            CASE
                WHEN fgm IS NOT NULL
                    AND fg3m IS NOT NULL
                    AND fga IS NOT NULL
                    AND fga > 0
                    THEN (fgm::DOUBLE + 0.5::DOUBLE * fg3m::DOUBLE) / fga::DOUBLE
                ELSE NULL
            END AS efg_pct,
            CASE
                WHEN pts IS NOT NULL
                    AND fga IS NOT NULL
                    AND fta IS NOT NULL
                    AND 2.0::DOUBLE * (fga::DOUBLE + 0.44::DOUBLE * fta::DOUBLE) > 0
                    THEN pts::DOUBLE
                        / (2.0::DOUBLE * (fga::DOUBLE + 0.44::DOUBLE * fta::DOUBLE))
                ELSE NULL
            END AS ts_pct,
            CASE
                WHEN fg3a IS NOT NULL AND fga IS NOT NULL AND fga > 0
                    THEN fg3a::DOUBLE / fga::DOUBLE
                ELSE NULL
            END AS fg3a_per_fga,
            CASE
                WHEN fta IS NOT NULL AND fga IS NOT NULL AND fga > 0
                    THEN fta::DOUBLE / fga::DOUBLE
                ELSE NULL
            END AS fta_per_fga,
            CASE
                WHEN ast IS NOT NULL AND tov IS NOT NULL AND tov > 0
                    THEN ast::DOUBLE / tov::DOUBLE
                ELSE NULL
            END AS ast_tov_ratio,
            CASE
                WHEN estimated_possessions_value < 0
                    THEN error(
                        'agg_lineup_efficiency: negative estimated possessions'
                    )
                ELSE estimated_possessions_value
            END AS estimated_possessions,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND pts IS NOT NULL
                    THEN 48.0::DOUBLE * pts::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS pts_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND reb IS NOT NULL
                    THEN 48.0::DOUBLE * reb::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS reb_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND ast IS NOT NULL
                    THEN 48.0::DOUBLE * ast::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS ast_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND tov IS NOT NULL
                    THEN 48.0::DOUBLE * tov::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS tov_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND stl IS NOT NULL
                    THEN 48.0::DOUBLE * stl::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS stl_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND blk IS NOT NULL
                    THEN 48.0::DOUBLE * blk::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS blk_per48,
            CASE
                WHEN min IS NOT NULL AND min > 0 AND plus_minus IS NOT NULL
                    THEN 48.0::DOUBLE * plus_minus::DOUBLE / min::DOUBLE
                ELSE NULL
            END AS plus_minus_per48,
            CASE
                WHEN estimated_possessions_value > 0 AND pts IS NOT NULL
                    THEN 100.0::DOUBLE * pts::DOUBLE / estimated_possessions_value
                ELSE NULL
            END AS estimated_off_rating,
            CASE
                WHEN estimated_possessions_value > 0
                    AND pts IS NOT NULL
                    AND plus_minus IS NOT NULL
                    THEN 100.0::DOUBLE * (pts::DOUBLE - plus_minus::DOUBLE)
                        / estimated_possessions_value
                ELSE NULL
            END AS estimated_def_rating,
            CASE
                WHEN estimated_possessions_value > 0 AND plus_minus IS NOT NULL
                    THEN 100.0::DOUBLE * plus_minus::DOUBLE
                        / estimated_possessions_value
                ELSE NULL
            END AS estimated_net_rating
        FROM guarded
        ORDER BY group_id, team_id, season_year, season_type
    """
