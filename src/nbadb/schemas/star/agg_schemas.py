"""Pandera star-schema contracts for all 15 agg_* aggregate output tables."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class AggAllTimeLeadersSchema(BaseSchema):
    """All-time career leaders with computed ranking columns."""

    player_id: int = pa.Field(gt=0)
    player_name: str = pa.Field()
    pts: int | None = pa.Field(nullable=True, ge=0)
    ast: int | None = pa.Field(nullable=True, ge=0)
    reb: int | None = pa.Field(nullable=True, ge=0)
    pts_rank: int = pa.Field(ge=1)
    ast_rank: int = pa.Field(ge=1)
    reb_rank: int = pa.Field(ge=1)


class AggClutchStatsSchema(BaseSchema):
    """Clutch-time statistics merged from dashboard and league clutch sources."""

    player_id: int | None = pa.Field(nullable=True, gt=0)
    season_year: str | None = pa.Field(nullable=True)
    clutch_gp: int | None = pa.Field(nullable=True, ge=0)
    clutch_min: float | None = pa.Field(nullable=True, ge=0.0)
    clutch_pts: float | None = pa.Field(nullable=True, ge=0.0)
    clutch_fg_pct: float | None = pa.Field(nullable=True)
    clutch_ft_pct: float | None = pa.Field(nullable=True)
    league_clutch_pts: float | None = pa.Field(nullable=True, ge=0.0)
    league_clutch_fg_pct: float | None = pa.Field(nullable=True)


class AggLeagueLeadersSchema(BaseSchema):
    """Per-season player rankings derived from agg_player_season."""

    player_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int | None = pa.Field(nullable=True, ge=0)
    avg_pts: float | None = pa.Field(nullable=True, ge=0.0)
    avg_reb: float | None = pa.Field(nullable=True, ge=0.0)
    avg_ast: float | None = pa.Field(nullable=True, ge=0.0)
    avg_stl: float | None = pa.Field(nullable=True, ge=0.0)
    avg_blk: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True)
    fg3_pct: float | None = pa.Field(nullable=True)
    ft_pct: float | None = pa.Field(nullable=True)
    pts_rank: int = pa.Field(ge=1)
    reb_rank: int = pa.Field(ge=1)
    ast_rank: int = pa.Field(ge=1)
    stl_rank: int = pa.Field(ge=1)
    blk_rank: int = pa.Field(ge=1)


class AggLineupEfficiencySchema(BaseSchema):
    """Lineup-level efficiency aggregated from fact_lineup_stats."""

    group_id: str = pa.Field()
    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    total_gp: int | None = pa.Field(nullable=True, ge=0)
    total_min: float | None = pa.Field(nullable=True, ge=0.0)
    pts_per48: float | None = pa.Field(nullable=True)
    avg_net_rating: float | None = pa.Field(nullable=True)
    total_plus_minus: float | None = pa.Field(nullable=True)


class AggPlayerBioSchema(BaseSchema):
    """Player biographical and physical information from league bio stats."""

    player_id: int = pa.Field(gt=0)
    player_name: str = pa.Field()
    team_id: int | None = pa.Field(nullable=True, gt=0)
    team_abbreviation: str | None = pa.Field(nullable=True)
    age: float | None = pa.Field(nullable=True, ge=0.0)
    player_height: str | None = pa.Field(nullable=True)
    player_height_inches: float | None = pa.Field(nullable=True, ge=0.0)
    player_weight: str | None = pa.Field(nullable=True)
    college: str | None = pa.Field(nullable=True)
    country: str | None = pa.Field(nullable=True)
    draft_year: str | None = pa.Field(nullable=True)
    draft_round: str | None = pa.Field(nullable=True)
    draft_number: str | None = pa.Field(nullable=True)
    gp: int | None = pa.Field(nullable=True, ge=0)
    pts: float | None = pa.Field(nullable=True, ge=0.0)
    reb: float | None = pa.Field(nullable=True, ge=0.0)
    ast: float | None = pa.Field(nullable=True, ge=0.0)
    net_rating: float | None = pa.Field(nullable=True)
    oreb_pct: float | None = pa.Field(nullable=True)
    dreb_pct: float | None = pa.Field(nullable=True)
    usg_pct: float | None = pa.Field(nullable=True)
    ts_pct: float | None = pa.Field(nullable=True)
    ast_pct: float | None = pa.Field(nullable=True)
    season_year: str = pa.Field()


class AggPlayerCareerSchema(BaseSchema):
    """Career-aggregated stats per player across regular seasons."""

    player_id: int = pa.Field(gt=0)
    career_gp: int | None = pa.Field(nullable=True, ge=0)
    career_min: float | None = pa.Field(nullable=True, ge=0.0)
    career_pts: float | None = pa.Field(nullable=True, ge=0.0)
    career_ppg: float | None = pa.Field(nullable=True, ge=0.0)
    career_rpg: float | None = pa.Field(nullable=True, ge=0.0)
    career_apg: float | None = pa.Field(nullable=True, ge=0.0)
    career_spg: float | None = pa.Field(nullable=True, ge=0.0)
    career_bpg: float | None = pa.Field(nullable=True, ge=0.0)
    career_fg_pct: float | None = pa.Field(nullable=True)
    career_fg3_pct: float | None = pa.Field(nullable=True)
    career_ft_pct: float | None = pa.Field(nullable=True)
    first_season: str | None = pa.Field(nullable=True)
    last_season: str | None = pa.Field(nullable=True)
    seasons_played: int | None = pa.Field(nullable=True, ge=0)


class AggPlayerRollingSchema(BaseSchema):
    """Rolling window averages (5/10/20 games) for player pts, reb, ast."""

    game_id: str = pa.Field()
    player_id: int = pa.Field(gt=0)
    game_date: str = pa.Field()
    pts_roll5: float | None = pa.Field(nullable=True, ge=0.0)
    reb_roll5: float | None = pa.Field(nullable=True, ge=0.0)
    ast_roll5: float | None = pa.Field(nullable=True, ge=0.0)
    pts_roll10: float | None = pa.Field(nullable=True, ge=0.0)
    reb_roll10: float | None = pa.Field(nullable=True, ge=0.0)
    ast_roll10: float | None = pa.Field(nullable=True, ge=0.0)
    pts_roll20: float | None = pa.Field(nullable=True, ge=0.0)
    reb_roll20: float | None = pa.Field(nullable=True, ge=0.0)
    ast_roll20: float | None = pa.Field(nullable=True, ge=0.0)


class AggPlayerSeasonSchema(BaseSchema):
    """Player season aggregates joining traditional and advanced game logs."""

    player_id: int = pa.Field(gt=0)
    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int = pa.Field(ge=0)
    total_min: float | None = pa.Field(nullable=True, ge=0.0)
    avg_min: float | None = pa.Field(nullable=True, ge=0.0)
    total_pts: float | None = pa.Field(nullable=True, ge=0.0)
    avg_pts: float | None = pa.Field(nullable=True, ge=0.0)
    total_reb: float | None = pa.Field(nullable=True, ge=0.0)
    avg_reb: float | None = pa.Field(nullable=True, ge=0.0)
    total_ast: float | None = pa.Field(nullable=True, ge=0.0)
    avg_ast: float | None = pa.Field(nullable=True, ge=0.0)
    total_stl: float | None = pa.Field(nullable=True, ge=0.0)
    avg_stl: float | None = pa.Field(nullable=True, ge=0.0)
    total_blk: float | None = pa.Field(nullable=True, ge=0.0)
    avg_blk: float | None = pa.Field(nullable=True, ge=0.0)
    total_tov: float | None = pa.Field(nullable=True, ge=0.0)
    avg_tov: float | None = pa.Field(nullable=True, ge=0.0)
    total_fgm: float | None = pa.Field(nullable=True, ge=0.0)
    total_fga: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True)
    total_fg3m: float | None = pa.Field(nullable=True, ge=0.0)
    total_fg3a: float | None = pa.Field(nullable=True, ge=0.0)
    fg3_pct: float | None = pa.Field(nullable=True)
    total_ftm: float | None = pa.Field(nullable=True, ge=0.0)
    total_fta: float | None = pa.Field(nullable=True, ge=0.0)
    ft_pct: float | None = pa.Field(nullable=True)
    avg_off_rating: float | None = pa.Field(nullable=True)
    avg_def_rating: float | None = pa.Field(nullable=True)
    avg_net_rating: float | None = pa.Field(nullable=True)
    avg_ts_pct: float | None = pa.Field(nullable=True)
    avg_usg_pct: float | None = pa.Field(nullable=True)
    avg_pie: float | None = pa.Field(nullable=True)


class AggPlayerSeasonPer36Schema(BaseSchema):
    """Per-36-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0)
    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int = pa.Field(ge=0)
    avg_min: float | None = pa.Field(nullable=True, ge=0.0)
    pts_per36: float | None = pa.Field(nullable=True, ge=0.0)
    reb_per36: float | None = pa.Field(nullable=True, ge=0.0)
    ast_per36: float | None = pa.Field(nullable=True, ge=0.0)
    stl_per36: float | None = pa.Field(nullable=True, ge=0.0)
    blk_per36: float | None = pa.Field(nullable=True, ge=0.0)
    tov_per36: float | None = pa.Field(nullable=True, ge=0.0)


class AggPlayerSeasonPer48Schema(BaseSchema):
    """Per-48-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0)
    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int = pa.Field(ge=0)
    avg_min: float | None = pa.Field(nullable=True, ge=0.0)
    pts_per48: float | None = pa.Field(nullable=True, ge=0.0)
    reb_per48: float | None = pa.Field(nullable=True, ge=0.0)
    ast_per48: float | None = pa.Field(nullable=True, ge=0.0)
    stl_per48: float | None = pa.Field(nullable=True, ge=0.0)
    blk_per48: float | None = pa.Field(nullable=True, ge=0.0)
    tov_per48: float | None = pa.Field(nullable=True, ge=0.0)


class AggShotLocationSeasonSchema(BaseSchema):
    """Shot-location season stats with per-season FGM ranking."""

    player_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    fgm: int | None = pa.Field(nullable=True, ge=0)
    season_fgm_rank: int = pa.Field(ge=1)


class AggShotZonesSchema(BaseSchema):
    """Player shooting stats aggregated by court zone per season."""

    player_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    shot_zone_basic: str | None = pa.Field(nullable=True)
    shot_zone_area: str | None = pa.Field(nullable=True)
    shot_zone_range: str | None = pa.Field(nullable=True)
    attempts: int | None = pa.Field(nullable=True, ge=0)
    makes: int | None = pa.Field(nullable=True, ge=0)
    fg_pct: float | None = pa.Field(nullable=True)
    avg_distance: float | None = pa.Field(nullable=True, ge=0.0)


class AggTeamFranchiseSchema(BaseSchema):
    """Franchise history with derived age and win-percentage columns."""

    team_id: int = pa.Field(gt=0)
    team_city: str | None = pa.Field(nullable=True)
    team_name: str | None = pa.Field(nullable=True)
    start_year: int | None = pa.Field(nullable=True)
    end_year: int | None = pa.Field(nullable=True)
    years: int | None = pa.Field(nullable=True, ge=0)
    games: int | None = pa.Field(nullable=True, ge=0)
    wins: int | None = pa.Field(nullable=True, ge=0)
    losses: int | None = pa.Field(nullable=True, ge=0)
    win_pct: float | None = pa.Field(nullable=True)
    po_appearances: int | None = pa.Field(nullable=True, ge=0)
    div_titles: int | None = pa.Field(nullable=True, ge=0)
    conf_titles: int | None = pa.Field(nullable=True, ge=0)
    league_titles: int | None = pa.Field(nullable=True, ge=0)
    franchise_age_years: int | None = pa.Field(nullable=True, ge=0)
    computed_win_pct: float | None = pa.Field(nullable=True)


class AggTeamPaceAndEfficiencySchema(BaseSchema):
    """Team-season pace and four-factor efficiency from advanced game logs."""

    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int = pa.Field(ge=0)
    avg_pace: float | None = pa.Field(nullable=True, ge=0.0)
    avg_ortg: float | None = pa.Field(nullable=True)
    avg_drtg: float | None = pa.Field(nullable=True)
    avg_net_rtg: float | None = pa.Field(nullable=True)


class AggTeamSeasonSchema(BaseSchema):
    """Team season aggregates from fact_team_game joined with dim_game."""

    team_id: int = pa.Field(gt=0)
    season_year: str = pa.Field()
    season_type: str = pa.Field()
    gp: int = pa.Field(ge=0)
    avg_pts: float | None = pa.Field(nullable=True, ge=0.0)
    avg_reb: float | None = pa.Field(nullable=True, ge=0.0)
    avg_ast: float | None = pa.Field(nullable=True, ge=0.0)
    avg_stl: float | None = pa.Field(nullable=True, ge=0.0)
    avg_blk: float | None = pa.Field(nullable=True, ge=0.0)
    avg_tov: float | None = pa.Field(nullable=True, ge=0.0)
    fg_pct: float | None = pa.Field(nullable=True)
    fg3_pct: float | None = pa.Field(nullable=True)
    ft_pct: float | None = pa.Field(nullable=True)
