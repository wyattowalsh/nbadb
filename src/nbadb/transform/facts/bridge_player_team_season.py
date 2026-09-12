from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class BridgePlayerTeamSeasonTransformer(SqlTransformer):
    output_table: ClassVar[str] = "bridge_player_team_season"
    depends_on: ClassVar[list[str]] = [
        "stg_player_career_regular",
        "stg_player_career_postseason",
        "stg_player_career_allstar",
    ]

    _SQL: ClassVar[str] = """
        WITH memberships AS (
            SELECT DISTINCT
                player_id,
                team_id,
                season_id AS season_year,
                league_id,
                team_abbreviation,
                'Regular Season' AS season_type
            FROM stg_player_career_regular
            UNION ALL
            SELECT DISTINCT
                player_id,
                team_id,
                season_id AS season_year,
                league_id,
                team_abbreviation,
                'Playoffs' AS season_type
            FROM stg_player_career_postseason
            UNION ALL
            SELECT DISTINCT
                player_id,
                team_id,
                season_id AS season_year,
                league_id,
                team_abbreviation,
                'All Star' AS season_type
            FROM stg_player_career_allstar
        ), membership_authority AS (
            SELECT
                player_id,
                team_id,
                season_year,
                league_id,
                season_type,
                CASE WHEN COUNT(DISTINCT team_abbreviation) > 1
                    THEN error('conflicting player-team-season membership rows')
                    ELSE MIN(team_abbreviation) END AS team_abbreviation
            FROM memberships
            WHERE player_id IS NOT NULL
              AND team_id IS NOT NULL
              AND team_id > 0
              AND season_year IS NOT NULL
            GROUP BY player_id, team_id, season_year, league_id, season_type
        )
        SELECT
            player_id,
            team_id,
            season_year,
            league_id,
            season_type,
            team_abbreviation,
            CAST(NULL AS VARCHAR) AS jersey_number,
            CAST(NULL AS VARCHAR) AS position
        FROM membership_authority
    """
