from __future__ import annotations

import polars as pl

from nbadb.schemas.star.fact_box_score_summary_v3_support import (
    FactBoxScoreSummaryV3AvailableVideoSchema,
    FactBoxScoreSummaryV3OfficialsSchema,
    FactBoxScoreSummaryV3OtherStatsSchema,
)
from nbadb.schemas.star.fact_scoreboard_support import (
    FactScoreboardConferenceStandingsSchema,
    FactScoreboardGameHeaderSchema,
    FactScoreboardV3BroadcasterSchema,
)


def test_scoreboard_support_output_schemas_validate_rows() -> None:
    header = pl.DataFrame(
        {
            "game_date_est": ["2025-01-01"],
            "game_id": ["0022400001"],
        }
    )
    standings = pl.DataFrame(
        {
            "team_id": [1610612738],
            "conference_scope": ["east"],
        }
    )
    broadcaster = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "broadcaster_type": ["tv"],
        }
    )

    assert FactScoreboardGameHeaderSchema.validate(header).shape == (1, 2)
    assert FactScoreboardConferenceStandingsSchema.validate(standings).shape == (1, 2)
    assert FactScoreboardV3BroadcasterSchema.validate(broadcaster).shape == (1, 2)


def test_box_score_summary_v3_support_output_schemas_validate_rows() -> None:
    officials = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "person_id": [44],
        }
    )
    other_stats = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "team_id": [1610612738],
        }
    )
    available_video = pl.DataFrame(
        {
            "game_id": ["0022400001"],
            "video_available_flag": [1],
        }
    )

    assert FactBoxScoreSummaryV3OfficialsSchema.validate(officials).shape == (1, 2)
    assert FactBoxScoreSummaryV3OtherStatsSchema.validate(other_stats).shape == (1, 2)
    assert FactBoxScoreSummaryV3AvailableVideoSchema.validate(available_video).shape == (1, 2)
