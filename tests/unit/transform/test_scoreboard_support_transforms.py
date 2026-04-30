from __future__ import annotations

import duckdb
import polars as pl
import pytest

from nbadb.transform.facts.fact_box_score_summary_v3_support import (
    FactBoxScoreSummaryV3AvailableVideoTransformer,
    FactBoxScoreSummaryV3GameInfoTransformer,
    FactBoxScoreSummaryV3GameSummaryTransformer,
    FactBoxScoreSummaryV3InactivePlayersTransformer,
    FactBoxScoreSummaryV3LastFiveMeetingsTransformer,
    FactBoxScoreSummaryV3LineScoreTransformer,
    FactBoxScoreSummaryV3OfficialsTransformer,
    FactBoxScoreSummaryV3OtherStatsTransformer,
)
from nbadb.transform.facts.fact_scoreboard_support import (
    FactScoreboardConferenceStandingsTransformer,
    FactScoreboardGameHeaderTransformer,
    FactScoreboardLastMeetingTransformer,
    FactScoreboardLineScoreTransformer,
    FactScoreboardSeriesStandingsTransformer,
    FactScoreboardTeamLeadersTransformer,
    FactScoreboardTicketLinksTransformer,
    FactScoreboardV3BroadcasterTransformer,
    FactScoreboardV3GameSummaryTransformer,
    FactScoreboardV3LineScoreTransformer,
    FactScoreboardV3MetadataTransformer,
    FactScoreboardV3TeamLeadersTransformer,
)


def _run(transformer, staging: dict[str, pl.LazyFrame]) -> pl.DataFrame:
    conn = duckdb.connect()
    try:
        for key, val in staging.items():
            conn.register(key, val.collect())
        transformer._conn = conn
        return transformer.transform(staging)
    finally:
        conn.close()


def _frame(row: dict) -> pl.LazyFrame:
    return pl.DataFrame({k: [v] for k, v in row.items()}).lazy()


def _full_row(transformer_cls: type, values: dict) -> dict:
    row = {column: None for column in transformer_cls._COLUMNS}
    row.update(values)
    return row


@pytest.mark.parametrize(
    ("transformer_cls", "output_table", "staging_key", "row"),
    [
        (
            FactScoreboardGameHeaderTransformer,
            "fact_scoreboard_game_header",
            "stg_scoreboard",
            {"game_date_est": "2025-01-01", "game_id": "0022400001"},
        ),
        (
            FactScoreboardLastMeetingTransformer,
            "fact_scoreboard_last_meeting",
            "stg_scoreboard_last_meeting",
            {"game_id": "0022400001", "last_game_id": "0022300001"},
        ),
        (
            FactScoreboardLineScoreTransformer,
            "fact_scoreboard_line_score",
            "stg_scoreboard_line_score",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactScoreboardTeamLeadersTransformer,
            "fact_scoreboard_team_leaders",
            "stg_scoreboard_team_leaders",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactScoreboardTicketLinksTransformer,
            "fact_scoreboard_ticket_links",
            "stg_scoreboard_ticket_links",
            {"game_id": "0022400001", "leag_tix": "https://nba.com/tix"},
        ),
        (
            FactScoreboardV3MetadataTransformer,
            "fact_scoreboard_v3_metadata",
            "stg_scoreboard_v3_metadata",
            {"game_date": "2025-01-01", "league_id": "00", "league_name": "NBA"},
        ),
        (
            FactScoreboardV3GameSummaryTransformer,
            "fact_scoreboard_v3_game_summary",
            "stg_scoreboard_v3_summary",
            {"game_id": "0022400001", "game_status": 2},
        ),
        (
            FactScoreboardV3LineScoreTransformer,
            "fact_scoreboard_v3_line_score",
            "stg_scoreboard_v3_line_score",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactScoreboardV3TeamLeadersTransformer,
            "fact_scoreboard_v3_team_leaders",
            "stg_scoreboard_v3_team_stats",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactScoreboardV3BroadcasterTransformer,
            "fact_scoreboard_v3_broadcaster",
            "stg_scoreboard_v3_broadcaster",
            {"game_id": "0022400001", "broadcaster_type": "tv"},
        ),
        (
            FactBoxScoreSummaryV3GameSummaryTransformer,
            "fact_box_score_summary_v3_game_summary",
            "stg_summary_v3_game_summary",
            {"game_id": "0022400001", "game_status": 3},
        ),
        (
            FactBoxScoreSummaryV3GameInfoTransformer,
            "fact_box_score_summary_v3_game_info",
            "stg_summary_v3_game_info",
            {"game_id": "0022400001", "game_date": "2025-01-01"},
        ),
        (
            FactBoxScoreSummaryV3OfficialsTransformer,
            "fact_box_score_summary_v3_officials",
            "stg_summary_v3_officials",
            {"game_id": "0022400001", "person_id": 44},
        ),
        (
            FactBoxScoreSummaryV3LineScoreTransformer,
            "fact_box_score_summary_v3_line_score",
            "stg_summary_v3_line_score",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactBoxScoreSummaryV3InactivePlayersTransformer,
            "fact_box_score_summary_v3_inactive_players",
            "stg_summary_v3_inactive_players",
            {"game_id": "0022400001", "person_id": 2544},
        ),
        (
            FactBoxScoreSummaryV3LastFiveMeetingsTransformer,
            "fact_box_score_summary_v3_last_five_meetings",
            "stg_summary_v3_last_five_meetings",
            {"game_id": "0022300001", "recency_order": 1},
        ),
        (
            FactBoxScoreSummaryV3OtherStatsTransformer,
            "fact_box_score_summary_v3_other_stats",
            "stg_summary_v3_other_stats",
            {"game_id": "0022400001", "team_id": 1610612738},
        ),
        (
            FactBoxScoreSummaryV3AvailableVideoTransformer,
            "fact_box_score_summary_v3_available_video",
            "stg_summary_v3_available_video",
            {"game_id": "0022400001", "video_available_flag": 1},
        ),
    ],
)
def test_scoreboard_support_transforms_select_explicit_columns(
    transformer_cls: type,
    output_table: str,
    staging_key: str,
    row: dict,
) -> None:
    transformer = transformer_cls()
    assert transformer.output_table == output_table
    assert transformer.depends_on == [staging_key]

    full_row = _full_row(transformer_cls, row)
    result = _run(transformer, {staging_key: _frame(full_row)})
    assert result.to_dict(as_series=False) == {k: [v] for k, v in full_row.items()}


def test_scoreboard_conference_standings_union_preserves_scope() -> None:
    staging = {
        "stg_scoreboard_east_conf": _frame(
            _full_row(
                FactScoreboardConferenceStandingsTransformer,
                {"team_id": 1610612738, "conference": "East"},
            )
        ),
        "stg_scoreboard_west_conf": _frame(
            _full_row(
                FactScoreboardConferenceStandingsTransformer,
                {"team_id": 1610612747, "conference": "West"},
            )
        ),
    }

    result = _run(FactScoreboardConferenceStandingsTransformer(), staging)

    assert result.shape[0] == 2
    assert set(result["conference_scope"].to_list()) == {"east", "west"}


def test_scoreboard_series_standings_union_preserves_scope() -> None:
    staging = {
        "stg_scoreboard_series_standings": _frame(
            _full_row(
                FactScoreboardSeriesStandingsTransformer,
                {"game_id": "001", "series_leader": "BOS"},
            )
        ),
        "stg_scoreboard_v2_series_standings": _frame(
            _full_row(
                FactScoreboardSeriesStandingsTransformer,
                {"game_id": "002", "series_leader": "LAL"},
            )
        ),
    }

    result = _run(FactScoreboardSeriesStandingsTransformer(), staging)

    assert result.shape[0] == 2
    assert set(result["series_scope"].to_list()) == {
        "scoreboard_v2",
        "scoreboard_v2_alternate",
    }
