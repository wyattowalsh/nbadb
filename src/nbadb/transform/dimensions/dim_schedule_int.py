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
                game_id,
                game_code,
                league_id,
                season_year,
                game_date,
                game_date_est,
                game_date_time_est,
                game_date_utc,
                game_time_utc,
                game_date_time_utc,
                game_status,
                game_status_text,
                game_sequence,
                week_number,
                week_name,
                day                 AS day_of_week,
                arena_name,
                arena_city,
                arena_state,
                home_team_team_id   AS home_team_id,
                home_team_team_name AS home_team_name,
                home_team_team_city AS home_team_city,
                home_team_team_tricode AS home_team_tricode,
                home_team_wins,
                home_team_losses,
                home_team_score,
                away_team_team_id   AS away_team_id,
                away_team_team_name AS away_team_name,
                away_team_team_city AS away_team_city,
                away_team_team_tricode AS away_team_tricode,
                away_team_wins,
                away_team_losses,
                away_team_score,
                if_necessary,
                series_text,
                game_subtype,
                is_neutral,
                postponed_status
            FROM stg_schedule_int
            QUALIFY ROW_NUMBER() OVER (PARTITION BY game_id ORDER BY game_status DESC) = 1
        ),
        weeks AS (
            SELECT DISTINCT
                season_year,
                week_number,
                week_name,
                start_date   AS week_start_date,
                end_date     AS week_end_date
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
