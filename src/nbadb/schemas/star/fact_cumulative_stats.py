from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema, derived_output_schema


class _CumulativeStatsBaseSchema(BaseSchema):
    date_est: str | None = pa.Field(nullable=True)
    visitor_team: str | None = pa.Field(nullable=True)
    home_team: str | None = pa.Field(nullable=True)
    display_fi_last: str | None = pa.Field(nullable=True)
    jersey_num: str | None = pa.Field(nullable=True)
    player: str | None = pa.Field(nullable=True)
    person_id: int | None = pa.Field(nullable=True, gt=0)
    team_id: int | None = pa.Field(nullable=True, gt=0)
    city: str | None = pa.Field(nullable=True)
    nickname: str | None = pa.Field(nullable=True)
    matchup: str | None = pa.Field(nullable=True)
    game_id: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    gs: int | None = pa.Field(nullable=True, ge=0)
    w: int | None = pa.Field(nullable=True, ge=0)
    l: int | None = pa.Field(nullable=True, ge=0)  # noqa: E741
    w_home: int | None = pa.Field(nullable=True, ge=0)
    l_home: int | None = pa.Field(nullable=True, ge=0)
    w_road: int | None = pa.Field(nullable=True, ge=0)
    l_road: int | None = pa.Field(nullable=True, ge=0)
    team_turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    team_rebounds: float | None = pa.Field(nullable=True, ge=0.0)
    total_turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    actual_minutes: float | None = pa.Field(nullable=True, ge=0.0)
    actual_seconds: float | None = pa.Field(nullable=True, ge=0.0)
    fg: float | None = pa.Field(nullable=True, ge=0.0)
    fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    fg3: float | None = pa.Field(nullable=True, ge=0.0)
    fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    ft: float | None = pa.Field(nullable=True, ge=0.0)
    fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True, ge=0.0, le=1.0)
    off_reb: float | None = pa.Field(nullable=True, ge=0.0)
    def_reb: float | None = pa.Field(nullable=True, ge=0.0)
    tot_reb: float | None = pa.Field(nullable=True, ge=0.0)
    avg_tot_reb: float | None = pa.Field(nullable=True, ge=0.0)
    avg_reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    pf: float | None = pa.Field(nullable=True, ge=0.0)
    dq: float | None = pa.Field(nullable=True, ge=0.0)
    stl: float | None = pa.Field(nullable=True, ge=0.0)
    turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    blk: float | None = pa.Field(nullable=True, ge=0.0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    max_actual_minutes: float | None = pa.Field(nullable=True, ge=0.0)
    max_actual_seconds: float | None = pa.Field(nullable=True, ge=0.0)
    max_reb: float | None = pa.Field(nullable=True, ge=0.0)
    max_ast: float | None = pa.Field(nullable=True, ge=0.0)
    max_stl: float | None = pa.Field(nullable=True, ge=0.0)
    max_turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    max_blk: float | None = pa.Field(nullable=True, ge=0.0)
    max_blkp: float | None = pa.Field(nullable=True, ge=0.0)
    max_pts: float | None = pa.Field(nullable=True, ge=0.0)
    avg_actual_minutes: float | None = pa.Field(nullable=True, ge=0.0)
    avg_actual_seconds: float | None = pa.Field(nullable=True, ge=0.0)
    avg_ast: float | None = pa.Field(nullable=True, ge=0.0)
    avg_stl: float | None = pa.Field(nullable=True, ge=0.0)
    avg_turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    avg_blk: float | None = pa.Field(nullable=True, ge=0.0)
    avg_blkp: float | None = pa.Field(nullable=True, ge=0.0)
    avg_pts: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_tot_reb: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_reb: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_ast: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_stl: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_turnovers: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_blk: float | None = pa.Field(nullable=True, ge=0.0)
    per_min_pts: float | None = pa.Field(nullable=True, ge=0.0)


class FactCumulativeStatsSchema(_CumulativeStatsBaseSchema):
    entity_type: str = pa.Field(isin=["player", "team"])
    stat_type: str = pa.Field(isin=["stats", "games"])


class FactCumulativeStatsDetailSchema(_CumulativeStatsBaseSchema):
    cume_type: str = pa.Field(
        isin=["player_game_by_game", "player_totals", "team_game_by_game", "team_totals"]
    )


derived_output_schema(literal_fields={"entity_type", "stat_type"})(FactCumulativeStatsSchema)
derived_output_schema(literal_fields={"cume_type"})(FactCumulativeStatsDetailSchema)
