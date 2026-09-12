from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class AggPlayerBioTransformer(SqlTransformer):
    output_table: ClassVar[str] = "agg_player_bio"
    depends_on: ClassVar[list[str]] = ["stg_league_player_bio"]

    _SQL: ClassVar[str] = """
        WITH projected AS (
            SELECT
                player_id,
                player_name,
                team_id,
                team_abbreviation,
                age,
                player_height,
                player_height_inches,
                player_weight,
                college,
                country,
                draft_year,
                draft_round,
                draft_number,
                gp,
                pts,
                reb,
                ast,
                net_rating,
                oreb_pct,
                dreb_pct,
                usg_pct,
                ts_pct,
                ast_pct,
                season_year,
                season_type
            FROM stg_league_player_bio
        ), validated AS (
            SELECT
                CASE
                    WHEN player_id IS NULL OR player_id <= 0
                        THEN error('player bio source has invalid player_id')
                    ELSE player_id
                END AS player_id,
                player_name,
                CASE
                    WHEN team_id IS NOT NULL AND team_id <= 0
                        THEN error('player bio source has invalid team_id')
                    ELSE team_id
                END AS team_id,
                team_abbreviation,
                age,
                player_height,
                player_height_inches,
                player_weight,
                college,
                country,
                draft_year,
                draft_round,
                draft_number,
                gp,
                pts,
                reb,
                ast,
                net_rating,
                oreb_pct,
                dreb_pct,
                usg_pct,
                ts_pct,
                ast_pct,
                CASE
                    WHEN season_year IS NULL OR trim(season_year) = ''
                        THEN error('player bio source has invalid season_year')
                    ELSE season_year
                END AS season_year,
                CASE
                    WHEN season_type IS NULL OR trim(season_type) = ''
                        THEN error('player bio source has invalid season_type')
                    ELSE season_type
                END AS season_type
            FROM projected
        ), deduplicated AS (
            SELECT DISTINCT
                player_id,
                player_name,
                team_id,
                team_abbreviation,
                age,
                player_height,
                player_height_inches,
                player_weight,
                college,
                country,
                draft_year,
                draft_round,
                draft_number,
                gp,
                pts,
                reb,
                ast,
                net_rating,
                oreb_pct,
                dreb_pct,
                usg_pct,
                ts_pct,
                ast_pct,
                season_year,
                season_type
            FROM validated
        ), reconciled AS (
            SELECT
                CASE WHEN count(*) > 1
                    THEN error('conflicting player bio tuple for player-team-season-type')
                    ELSE player_id END AS player_id,
                min(player_name) AS player_name,
                team_id,
                min(team_abbreviation) AS team_abbreviation,
                min(age) AS age,
                min(player_height) AS player_height,
                min(player_height_inches) AS player_height_inches,
                min(player_weight) AS player_weight,
                min(college) AS college,
                min(country) AS country,
                min(draft_year) AS draft_year,
                min(draft_round) AS draft_round,
                min(draft_number) AS draft_number,
                min(gp) AS gp,
                min(pts) AS pts,
                min(reb) AS reb,
                min(ast) AS ast,
                min(net_rating) AS net_rating,
                min(oreb_pct) AS oreb_pct,
                min(dreb_pct) AS dreb_pct,
                min(usg_pct) AS usg_pct,
                min(ts_pct) AS ts_pct,
                min(ast_pct) AS ast_pct,
                season_year,
                season_type
            FROM deduplicated
            GROUP BY player_id, team_id, season_year, season_type
        )
        SELECT
            player_id,
            player_name,
            team_id,
            team_abbreviation,
            age,
            player_height,
            player_height_inches,
            player_weight,
            college,
            country,
            draft_year,
            draft_round,
            draft_number,
            gp,
            pts,
            reb,
            ast,
            net_rating,
            oreb_pct,
            dreb_pct,
            usg_pct,
            ts_pct,
            ast_pct,
            season_year,
            season_type
        FROM reconciled
        ORDER BY player_id, team_id, season_year, season_type
    """
