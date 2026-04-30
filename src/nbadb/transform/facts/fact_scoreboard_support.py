from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from nbadb.transform.base import SqlTransformer

if TYPE_CHECKING:
    from collections.abc import Sequence


def _select_list(columns: Sequence[str], *extras: str) -> str:
    return ",\n            ".join([*columns, *extras])


def _select_sql(source_table: str, columns: Sequence[str]) -> str:
    return f"""
        SELECT
            {_select_list(columns)}
        FROM {source_table}
    """


class FactScoreboardGameHeaderTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_game_header"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_date_est",
        "game_sequence",
        "game_id",
        "game_status_id",
        "game_status_text",
        "gamecode",
        "home_team_id",
        "visitor_team_id",
        "season",
        "live_period",
        "live_pc_time",
        "natl_tv_broadcaster_abbreviation",
        "home_tv_broadcaster_abbreviation",
        "away_tv_broadcaster_abbreviation",
        "live_period_time_bcast",
        "arena_name",
        "wh_status",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard", _COLUMNS)


class FactScoreboardConferenceStandingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_conference_standings"
    depends_on: ClassVar[list[str]] = [
        "stg_scoreboard_east_conf",
        "stg_scoreboard_west_conf",
    ]
    _COLUMNS: ClassVar[list[str]] = [
        "team_id",
        "league_id",
        "season_id",
        "standings_date",
        "conference",
        "team",
        "g",
        "w",
        "l",
        "w_pct",
        "home_record",
        "road_record",
        "return_to_play",
    ]
    _SQL: ClassVar[str] = f"""
        SELECT
            {_select_list(_COLUMNS, "'east' AS conference_scope")}
        FROM stg_scoreboard_east_conf
        UNION ALL BY NAME
        SELECT
            {_select_list(_COLUMNS, "'west' AS conference_scope")}
        FROM stg_scoreboard_west_conf
    """


class FactScoreboardLastMeetingTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_last_meeting"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_last_meeting"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "last_game_id",
        "last_game_date_est",
        "last_game_home_team_id",
        "last_game_home_team_city",
        "last_game_home_team_name",
        "last_game_home_team_abbreviation",
        "last_game_home_team_points",
        "last_game_visitor_team_id",
        "last_game_visitor_team_city",
        "last_game_visitor_team_name",
        "last_game_visitor_team_city1",
        "last_game_visitor_team_points",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_last_meeting", _COLUMNS)


class FactScoreboardLineScoreTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_line_score"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_line_score"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_date_est",
        "game_sequence",
        "game_id",
        "team_id",
        "team_abbreviation",
        "team_city_name",
        "team_name",
        "team_wins_losses",
        "pts_qtr1",
        "pts_qtr2",
        "pts_qtr3",
        "pts_qtr4",
        "pts_ot1",
        "pts_ot2",
        "pts_ot3",
        "pts_ot4",
        "pts_ot5",
        "pts_ot6",
        "pts_ot7",
        "pts_ot8",
        "pts_ot9",
        "pts_ot10",
        "pts",
        "fg_pct",
        "ft_pct",
        "fg3_pct",
        "ast",
        "reb",
        "tov",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_line_score", _COLUMNS)


class FactScoreboardSeriesStandingsTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_series_standings"
    depends_on: ClassVar[list[str]] = [
        "stg_scoreboard_series_standings",
        "stg_scoreboard_v2_series_standings",
    ]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "home_team_id",
        "visitor_team_id",
        "game_date_est",
        "home_team_wins",
        "home_team_losses",
        "series_leader",
    ]
    _SQL: ClassVar[str] = f"""
        SELECT
            {_select_list(_COLUMNS, "'scoreboard_v2' AS series_scope")}
        FROM stg_scoreboard_series_standings
        UNION ALL BY NAME
        SELECT
            {_select_list(_COLUMNS, "'scoreboard_v2_alternate' AS series_scope")}
        FROM stg_scoreboard_v2_series_standings
    """


class FactScoreboardTeamLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_team_leaders"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_team_leaders"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "team_city",
        "team_nickname",
        "team_abbreviation",
        "pts_player_id",
        "pts_player_name",
        "pts",
        "reb_player_id",
        "reb_player_name",
        "reb",
        "ast_player_id",
        "ast_player_name",
        "ast",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_team_leaders", _COLUMNS)


class FactScoreboardTicketLinksTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_ticket_links"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_ticket_links"]
    _COLUMNS: ClassVar[list[str]] = ["game_id", "leag_tix"]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_ticket_links", _COLUMNS)


class FactScoreboardV3MetadataTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3_metadata"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_v3_metadata"]
    _COLUMNS: ClassVar[list[str]] = ["game_date", "league_id", "league_name"]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_v3_metadata", _COLUMNS)


class FactScoreboardV3GameSummaryTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3_game_summary"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_v3_summary"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "game_code",
        "game_status",
        "game_status_text",
        "period",
        "game_clock",
        "game_time_utc",
        "game_et",
        "regulation_periods",
        "series_game_number",
        "game_label",
        "game_sub_label",
        "series_text",
        "if_necessary",
        "series_conference",
        "po_round_desc",
        "game_subtype",
        "is_neutral",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_v3_summary", _COLUMNS)


class FactScoreboardV3LineScoreTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3_line_score"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_v3_line_score"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "team_city",
        "team_name",
        "team_tricode",
        "team_slug",
        "wins",
        "losses",
        "score",
        "seed",
        "in_bonus",
        "timeouts_remaining",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_v3_line_score", _COLUMNS)


class FactScoreboardV3TeamLeadersTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3_team_leaders"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_v3_team_stats"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "team_id",
        "leader_type",
        "person_id",
        "name",
        "player_slug",
        "jersey_num",
        "position",
        "team_tricode",
        "points",
        "rebounds",
        "assists",
        "season_leaders_flag",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_v3_team_stats", _COLUMNS)


class FactScoreboardV3BroadcasterTransformer(SqlTransformer):
    output_table: ClassVar[str] = "fact_scoreboard_v3_broadcaster"
    depends_on: ClassVar[list[str]] = ["stg_scoreboard_v3_broadcaster"]
    _COLUMNS: ClassVar[list[str]] = [
        "game_id",
        "broadcaster_type",
        "broadcaster_id",
        "broadcast_display",
        "broadcaster_team_id",
        "broadcaster_description",
    ]
    _SQL: ClassVar[str] = _select_sql("stg_scoreboard_v3_broadcaster", _COLUMNS)
