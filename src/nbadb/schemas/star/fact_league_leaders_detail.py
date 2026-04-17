from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


class FactLeagueLeadersDetailSchema(BaseSchema):
    leader_type: str = pa.Field(
        isin=["league", "assist", "assist_tracker", "dunk_score", "gravity"],
        metadata={"description": "Leaderboard packet discriminator"},
    )
    player_id: int | None = pa.Field(nullable=True, gt=0)
    playerid: int | None = pa.Field(nullable=True, gt=0)
    rank: int | None = pa.Field(nullable=True, ge=1)
    player: str | None = pa.Field(nullable=True)
    team: str | None = pa.Field(nullable=True)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    min: float | None = pa.Field(nullable=True, ge=0.0)
    fgm: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ftm: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    oreb: float | None = pa.Field(nullable=True, ge=0.0)
    dreb: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    assists: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    tov: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    eff: float | None = pa.Field(nullable=True)
    ast_tov: float | None = pa.Field(nullable=True)
    stl_tov: float | None = pa.Field(nullable=True)
    dunk_score: float | None = pa.Field(nullable=True, ge=0.0)
    gravityscore: float | None = pa.Field(nullable=True)


derived_output_schema(literal_fields={"leader_type"})(FactLeagueLeadersDetailSchema)
