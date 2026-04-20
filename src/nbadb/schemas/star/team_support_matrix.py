from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import derived_output_schema
from nbadb.schemas.staging.team_support_matrix import _TeamComparisonStatsSchema
from nbadb.schemas.star.fact_team_tracking import FactTeamLineupsOverallSchema


class FactTeamLineupsDetailSchema(FactTeamLineupsOverallSchema):
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    season_year: str | None = pa.Field(nullable=True)


class FactTeamMatchupsSchema(_TeamComparisonStatsSchema):
    matchup_type: str = pa.Field(
        nullable=False,
        isin=["team_vs_player", "team_and_players_vs", "team_and_players_vs_players"],
    )


derived_output_schema()(FactTeamLineupsDetailSchema)
derived_output_schema(literal_fields={"matchup_type"})(FactTeamMatchupsSchema)
