from __future__ import annotations

from typing import ClassVar

from nbadb.transform.base import SqlTransformer


class DimScheduleIntTransformer(SqlTransformer):
    """International schedule dimension — one row per game from ScheduleLeagueV2Int."""

    output_table: ClassVar[str] = "dim_schedule_int"
    depends_on: ClassVar[list[str]] = ["stg_schedule_int", "stg_schedule_int_weeks"]

    _SQL: ClassVar[str] = """
        WITH games AS (
            SELECT
                gameId              AS game_id,
                gameCode            AS game_code,
                leagueId            AS league_id,
                seasonYear          AS season_year,
                gameDate            AS game_date,
                gameDateEst         AS game_date_est,
                gameDateTimeEst     AS game_date_time_est,
                gameDateUTC         AS game_date_utc,
                gameTimeUTC         AS game_time_utc,
                gameDateTimeUTC     AS game_date_time_utc,
                gameStatus          AS game_status,
                gameStatusText      AS game_status_text,
                gameSequence        AS game_sequence,
                weekNumber          AS week_number,
                weekName            AS week_name,
                day                 AS day_of_week,
                arenaName           AS arena_name,
                arenaCity           AS arena_city,
                arenaState          AS arena_state,
                homeTeam_teamId     AS home_team_id,
                homeTeam_teamName   AS home_team_name,
                homeTeam_teamCity   AS home_team_city,
                homeTeam_teamTricode AS home_team_tricode,
                homeTeam_wins       AS home_team_wins,
                homeTeam_losses     AS home_team_losses,
                homeTeam_score      AS home_team_score,
                awayTeam_teamId     AS away_team_id,
                awayTeam_teamName   AS away_team_name,
                awayTeam_teamCity   AS away_team_city,
                awayTeam_teamTricode AS away_team_tricode,
                awayTeam_wins       AS away_team_wins,
                awayTeam_losses     AS away_team_losses,
                awayTeam_score      AS away_team_score,
                ifNecessary         AS if_necessary,
                seriesText          AS series_text,
                gameSubtype         AS game_subtype,
                isNeutral           AS is_neutral,
                postponedStatus     AS postponed_status,
            FROM stg_schedule_int
            QUALIFY ROW_NUMBER() OVER (PARTITION BY gameId ORDER BY gameStatus DESC) = 1
        ),
        weeks AS (
            SELECT DISTINCT
                seasonYear   AS season_year,
                weekNumber   AS week_number,
                weekName     AS week_name,
                startDate    AS week_start_date,
                endDate      AS week_end_date,
            FROM stg_schedule_int_weeks
        )
        SELECT
            g.*,
            w.week_start_date,
            w.week_end_date,
        FROM games g
        LEFT JOIN weeks w
            ON g.season_year = w.season_year
            AND g.week_number = w.week_number
        ORDER BY g.game_date, g.game_id
    """
