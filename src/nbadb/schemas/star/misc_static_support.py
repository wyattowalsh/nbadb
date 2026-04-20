from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema
from nbadb.schemas.staging.misc_static_support import (
    StagingLeagueGameFinderSchema,
    StagingStaticPlayersSchema,
    StagingStaticTeamsSchema,
    StagingTeamStreakFinderSchema,
)


class FactLeagueGameFinderSchema(StagingLeagueGameFinderSchema):
    pass


class FactSeasonMatchupsSchema(BaseSchema):
    season_id: str | None = pa.Field(nullable=True)
    off_player_id: int | None = pa.Field(nullable=True, gt=0)
    off_player_name: str | None = pa.Field(nullable=True)
    def_player_id: int | None = pa.Field(nullable=True, gt=0)
    def_player_name: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    matchup_min: float | None = pa.Field(nullable=True, ge=0.0)
    partial_poss: float | None = pa.Field(nullable=True, ge=0.0)
    player_pts: float | None = pa.Field(nullable=True, ge=0.0)
    team_pts: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_ast: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_tov: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_blk: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fgm: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fga: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    matchup_fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    help_blk: float | None = pa.Field(nullable=True, ge=0.0)
    help_fgm: float | None = pa.Field(nullable=True, ge=0.0)
    help_fga: float | None = pa.Field(nullable=True, ge=0.0)
    help_fg_perc: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    matchup_ftm: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_fta: float | None = pa.Field(nullable=True, ge=0.0)
    sfl: float | None = pa.Field(nullable=True, ge=0.0)
    position: str | None = pa.Field(nullable=True)
    percent_of_time: float | None = pa.Field(nullable=True, ge=0.0)
    matchup_type: str = pa.Field(
        isin=["detail", "rollup"],
        metadata={
            "source": "derived.fact_season_matchups.matchup_type",
            "description": "Whether the row came from the detail or rollup matchup packet",
        },
    )


class FactStaticPlayersSchema(StagingStaticPlayersSchema):
    pass


class FactStaticTeamsSchema(StagingStaticTeamsSchema):
    pass


class FactStreakFinderSchema(BaseSchema):
    entity_type: str = pa.Field(isin=["player", "player_game", "team"])
    player_name_last_first: str | None = pa.Field(nullable=True)
    player_id: int | None = pa.Field(nullable=True, gt=0)
    team_name: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    gamestreak: str | None = pa.Field(nullable=True)
    startdate: str | None = pa.Field(nullable=True)
    enddate: str | None = pa.Field(nullable=True)
    activestreak: str | None = pa.Field(nullable=True)
    numseasons: int | None = pa.Field(nullable=True, ge=0)
    lastseason: str | None = pa.Field(nullable=True)
    firstseason: str | None = pa.Field(nullable=True)
    abbreviation: str | None = pa.Field(nullable=True)


class FactTeamStreakFinderSchema(StagingTeamStreakFinderSchema):
    pass


derived_output_schema()(FactLeagueGameFinderSchema)
derived_output_schema(literal_fields={"matchup_type"})(FactSeasonMatchupsSchema)
derived_output_schema()(FactStaticPlayersSchema)
derived_output_schema()(FactStaticTeamsSchema)
derived_output_schema(literal_fields={"entity_type"})(FactStreakFinderSchema)
derived_output_schema()(FactTeamStreakFinderSchema)
