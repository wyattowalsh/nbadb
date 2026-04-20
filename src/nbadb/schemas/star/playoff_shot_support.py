from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.raw.shot_chart import RawShotChartLeagueWideSchema
from nbadb.schemas.staging.playoff_shot_support import StagingShotChartLineupSchema


class FactPlayoffPictureSchema(BaseSchema):
    conference: str | None = pa.Field(nullable=True)
    high_seed_rank: int | None = pa.Field(nullable=True, ge=0)
    high_seed_team: str | None = pa.Field(nullable=True)
    high_seed_team_id: int | None = pa.Field(nullable=True, gt=0)
    low_seed_rank: int | None = pa.Field(nullable=True, ge=0)
    low_seed_team: str | None = pa.Field(nullable=True)
    low_seed_team_id: int | None = pa.Field(nullable=True, gt=0)
    high_seed_series_w: int | None = pa.Field(nullable=True, ge=0)
    high_seed_series_l: int | None = pa.Field(nullable=True, ge=0)
    high_seed_series_remaining_g: int | None = pa.Field(nullable=True, ge=0)
    high_seed_series_remaining_home_g: int | None = pa.Field(nullable=True, ge=0)
    high_seed_series_remaining_away_g: int | None = pa.Field(nullable=True, ge=0)
    team: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    remaining_g: int | None = pa.Field(nullable=True, ge=0)
    remaining_home_g: int | None = pa.Field(nullable=True, ge=0)
    remaining_away_g: int | None = pa.Field(nullable=True, ge=0)
    rank: int | None = pa.Field(nullable=True, ge=0)
    team_slug: str | None = pa.Field(nullable=True)
    wins: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0)
    pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    div: str | None = pa.Field(nullable=True)
    conf: str | None = pa.Field(nullable=True)
    home: str | None = pa.Field(nullable=True)
    away: str | None = pa.Field(nullable=True)
    gb: float | None = pa.Field(nullable=True)
    gr_over_500: str | None = pa.Field(nullable=True)
    gr_over_500_home: str | None = pa.Field(nullable=True)
    gr_over_500_away: str | None = pa.Field(nullable=True)
    gr_under_500: str | None = pa.Field(nullable=True)
    gr_under_500_home: str | None = pa.Field(nullable=True)
    gr_under_500_away: str | None = pa.Field(nullable=True)
    ranking_criteria: str | None = pa.Field(nullable=True)
    clinched_playoffs: int | None = pa.Field(nullable=True)
    clinched_conference: int | None = pa.Field(nullable=True)
    clinched_division: int | None = pa.Field(nullable=True)
    clinched_play_in: int | None = pa.Field(nullable=True)
    eliminated_playoffs: int | None = pa.Field(nullable=True)
    sosa_remaining: float | None = pa.Field(nullable=True)
    return_to_play_east_pi_flag: int | None = pa.Field(nullable=True)
    return_to_play_west_pi_flag: int | None = pa.Field(nullable=True)
    return_to_play_already_eliminated: int | None = pa.Field(nullable=True)
    seeding_game_1_outcome: str | None = pa.Field(nullable=True)
    seeding_game_2_outcome: str | None = pa.Field(nullable=True)
    seeding_game_3_outcome: str | None = pa.Field(nullable=True)
    seeding_game_4_outcome: str | None = pa.Field(nullable=True)
    seeding_game_5_outcome: str | None = pa.Field(nullable=True)
    seeding_game_6_outcome: str | None = pa.Field(nullable=True)
    seeding_game_7_outcome: str | None = pa.Field(nullable=True)
    seeding_game_8_outcome: str | None = pa.Field(nullable=True)
    seeding_game_1_id: str | None = pa.Field(nullable=True)
    seeding_game_2_id: str | None = pa.Field(nullable=True)
    seeding_game_3_id: str | None = pa.Field(nullable=True)
    seeding_game_4_id: str | None = pa.Field(nullable=True)
    seeding_game_5_id: str | None = pa.Field(nullable=True)
    seeding_game_6_id: str | None = pa.Field(nullable=True)
    seeding_game_7_id: str | None = pa.Field(nullable=True)
    seeding_game_8_id: str | None = pa.Field(nullable=True)
    seeding_game_1_opponent: str | None = pa.Field(nullable=True)
    seeding_game_2_opponent: str | None = pa.Field(nullable=True)
    seeding_game_3_opponent: str | None = pa.Field(nullable=True)
    seeding_game_4_opponent: str | None = pa.Field(nullable=True)
    seeding_game_5_opponent: str | None = pa.Field(nullable=True)
    seeding_game_6_opponent: str | None = pa.Field(nullable=True)
    seeding_game_7_opponent: str | None = pa.Field(nullable=True)
    seeding_game_8_opponent: str | None = pa.Field(nullable=True)
    seeding_game_1_label: str | None = pa.Field(nullable=True)
    seeding_game_2_label: str | None = pa.Field(nullable=True)
    seeding_game_3_label: str | None = pa.Field(nullable=True)
    seeding_game_4_label: str | None = pa.Field(nullable=True)
    seeding_game_5_label: str | None = pa.Field(nullable=True)
    seeding_game_6_label: str | None = pa.Field(nullable=True)
    seeding_game_7_label: str | None = pa.Field(nullable=True)
    seeding_game_8_label: str | None = pa.Field(nullable=True)


class FactShotChartLeagueSchema(RawShotChartLeagueWideSchema):
    pass


class FactShotChartLineupSchema(StagingShotChartLineupSchema):
    chart_type: str = pa.Field(
        isin=["lineup", "lineup_detail"],
        metadata={
            "source": "derived.fact_shot_chart_lineup.chart_type",
            "description": "Packet discriminator for lineup-level or detail-level shot chart rows",
        },
    )


derived_output_schema()(FactPlayoffPictureSchema)
derived_output_schema()(FactShotChartLeagueSchema)
derived_output_schema(literal_fields={"chart_type"})(FactShotChartLineupSchema)
