from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import SqlTransformer

if TYPE_CHECKING:
    from collections.abc import Sequence


def _select_list(columns: Sequence[str]) -> str:
    return ",\n            ".join(columns)


def _select_sql(source_table: str, columns: Sequence[str]) -> str:
    return f"""
        SELECT
            {_select_list(columns)}
        FROM {source_table}
    """


class FactBoxScoreSummaryV3GameSummaryTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_game_summary"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_game_summary"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "game_code",
        "game_status",
        "game_status_text",
        "period",
        "game_clock",
        "game_time_utc",
        "game_et",
        "away_team_id",
        "home_team_id",
        "duration",
        "attendance",
        "sellout",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_game_summary", _COLUMNS)


class FactBoxScoreSummaryV3GameInfoTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_game_info"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_game_info"]
    _COLUMNS: ClassVar[list[str]] = ["game_id", "game_date", "attendance", "game_duration"]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_game_info", _COLUMNS)


class FactBoxScoreSummaryV3OfficialsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_officials"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_officials"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "person_id",
        "name",
        "name_i",
        "first_name",
        "family_name",
        "jersey_num",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_officials", _COLUMNS)


class FactBoxScoreSummaryV3LineScoreTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_line_score"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_line_score"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "team_city",
        "team_name",
        "team_tricode",
        "team_slug",
        "team_wins",
        "team_losses",
        "period1_score",
        "period2_score",
        "period3_score",
        "period4_score",
        "score",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_line_score", _COLUMNS)


class FactBoxScoreSummaryV3InactivePlayersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_inactive_players"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_inactive_players"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "person_id",
        "first_name",
        "family_name",
        "jersey_num",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_inactive_players", _COLUMNS)


class FactBoxScoreSummaryV3LastFiveMeetingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_last_five_meetings"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_last_five_meetings"]
    _COLUMNS: ClassVar[list[str]] = [
        "recency_order",
        "game_id",
        "game_time_utc",
        "game_et",
        "game_status",
        "game_status_text",
        "away_team_id",
        "away_team_city",
        "away_team_name",
        "away_team_tricode",
        "away_team_score",
        "away_team_wins",
        "away_team_losses",
        "home_team_id",
        "home_team_city",
        "home_team_name",
        "home_team_tricode",
        "home_team_score",
        "home_team_wins",
        "home_team_losses",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_last_five_meetings", _COLUMNS)


class FactBoxScoreSummaryV3OtherStatsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_other_stats"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_other_stats"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "team_city",
        "team_name",
        "team_tricode",
        "points",
        "rebounds_total",
        "assists",
        "steals",
        "blocks",
        "turnovers",
        "field_goals_percentage",
        "three_pointers_percentage",
        "free_throws_percentage",
        "points_in_the_paint",
        "points_second_chance",
        "points_fast_break",
        "biggest_lead",
        "lead_changes",
        "times_tied",
        "biggest_scoring_run",
        "turnovers_team",
        "turnovers_total",
        "rebounds_team",
        "points_from_turnovers",
        "bench_points",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_other_stats", _COLUMNS)


class FactBoxScoreSummaryV3AvailableVideoTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_box_score_summary_v3_available_video"
    depends_on: ClassVar[list[str]] = ["stg_summary_v3_available_video"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "video_available_flag",
        "pt_available",
        "pt_xyz_available",
        "wh_status",
        "hustle_status",
        "historical_status",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_summary_v3_available_video", _COLUMNS)
