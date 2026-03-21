from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class FactTeamAwardsConfSchema(BaseSchema):
    yearawarded: str | None = pa.Field(nullable=True)
    oppositeteam: str | None = pa.Field(nullable=True)


class FactTeamAwardsDivSchema(BaseSchema):
    yearawarded: str | None = pa.Field(nullable=True)
    oppositeteam: str | None = pa.Field(nullable=True)


class FactTeamBackgroundSchema(BaseSchema):
    team_id: int = pa.Field(gt=0)
    abbreviation: str = pa.Field()
    nickname: str = pa.Field()
    yearfounded: int | None = pa.Field(nullable=True, gt=1900)
    city: str | None = pa.Field(nullable=True)
    arena: str | None = pa.Field(nullable=True)
    arenacapacity: int | None = pa.Field(nullable=True, gt=0)
    owner: str | None = pa.Field(nullable=True)
    generalmanager: str | None = pa.Field(nullable=True)
    headcoach: str | None = pa.Field(nullable=True)
    dleagueaffiliation: str | None = pa.Field(nullable=True)


class FactTeamHofSchema(BaseSchema):
    playerid: int | None = pa.Field(nullable=True, gt=0)
    player: str | None = pa.Field(nullable=True)
    position: str | None = pa.Field(nullable=True)
    jersey: str | None = pa.Field(nullable=True)
    seasonswithteam: str | None = pa.Field(nullable=True)
    year: str | None = pa.Field(nullable=True)


class FactTeamRetiredSchema(BaseSchema):
    playerid: int | None = pa.Field(nullable=True, gt=0)
    player: str | None = pa.Field(nullable=True)
    position: str | None = pa.Field(nullable=True)
    jersey: str | None = pa.Field(nullable=True)
    seasonswithteam: str | None = pa.Field(nullable=True)
    year: str | None = pa.Field(nullable=True)


class FactTeamSocialSitesSchema(BaseSchema):
    accounttype: str | None = pa.Field(nullable=True)
    website_link: str | None = pa.Field(nullable=True)


class FactTeamSeasonRanksSchema(BaseSchema):
    league_id: str | None = pa.Field(nullable=True)
    season_id: str | None = pa.Field(nullable=True)
    team_id: int = pa.Field(gt=0)
    pts_rank: int | None = pa.Field(nullable=True, gt=0)
    pts_pg: float | None = pa.Field(nullable=True, ge=0.0)
    reb_rank: int | None = pa.Field(nullable=True, gt=0)
    reb_pg: float | None = pa.Field(nullable=True, ge=0.0)
    ast_rank: int | None = pa.Field(nullable=True, gt=0)
    ast_pg: float | None = pa.Field(nullable=True, ge=0.0)
    opp_pts_rank: int | None = pa.Field(nullable=True, gt=0)
    opp_pts_pg: float | None = pa.Field(nullable=True, ge=0.0)
    season_type: str | None = pa.Field(nullable=True)
