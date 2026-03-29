"""Pandera star-schema contracts for all 16 agg_* aggregate output tables."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class AggAllTimeLeadersSchema(BaseSchema):
    """All-time career leaders with computed ranking columns."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    player_name: str = pa.Field(metadata={"description": "Player display name"})
    pts: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Career total points"})
    ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career total assists"}
    )
    reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career total rebounds"}
    )
    pts_rank: int = pa.Field(ge=1, metadata={"description": "All-time points rank"})
    ast_rank: int = pa.Field(ge=1, metadata={"description": "All-time assists rank"})
    reb_rank: int = pa.Field(ge=1, metadata={"description": "All-time rebounds rank"})


class AggClutchStatsSchema(BaseSchema):
    """Clutch-time statistics merged from dashboard and league clutch sources."""

    player_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Player identifier"}
    )
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    clutch_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Games played in clutch time"}
    )
    clutch_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Minutes played in clutch time"}
    )
    clutch_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points scored in clutch time"}
    )
    clutch_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Clutch field goal percentage"}
    )
    clutch_ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Clutch free throw percentage"}
    )
    league_clutch_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "League-wide clutch points"}
    )
    league_clutch_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League-wide clutch FG percentage"}
    )


class AggGameTotalsSchema(BaseSchema):
    """Per-game aggregate with home/away stats side-by-side."""

    game_id: int = pa.Field(gt=0, metadata={"description": "Unique game identifier"})
    game_date: str = pa.Field(metadata={"description": "Date the game was played"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"},
    )
    home_team_id: int = pa.Field(gt=0, metadata={"description": "Home team identifier"})
    away_team_id: int = pa.Field(gt=0, metadata={"description": "Away team identifier"})
    home_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team points"}
    )
    away_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team points"}
    )
    total_pts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Combined game points (home + away)"}
    )
    home_reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team total rebounds"}
    )
    away_reb: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team total rebounds"}
    )
    home_ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Home team assists"}
    )
    away_ast: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Away team assists"}
    )
    home_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Home team field goal percentage"}
    )
    away_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Away team field goal percentage"}
    )


class AggLeagueLeadersSchema(BaseSchema):
    """Per-season player rankings derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
    pts_rank: int = pa.Field(ge=1, metadata={"description": "Points per game rank"})
    reb_rank: int = pa.Field(ge=1, metadata={"description": "Rebounds per game rank"})
    ast_rank: int = pa.Field(ge=1, metadata={"description": "Assists per game rank"})
    stl_rank: int = pa.Field(ge=1, metadata={"description": "Steals per game rank"})
    blk_rank: int = pa.Field(ge=1, metadata={"description": "Blocks per game rank"})


class AggLineupEfficiencySchema(BaseSchema):
    """Lineup-level efficiency aggregated from fact_lineup_stats."""

    group_id: str = pa.Field(metadata={"description": "Lineup group identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    total_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total games played by lineup"}
    )
    total_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total minutes played by lineup"}
    )
    pts_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Points per 48 minutes"}
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average net rating"}
    )
    total_plus_minus: float | None = pa.Field(
        nullable=True, metadata={"description": "Total plus-minus differential"}
    )


class AggPlayerBioSchema(BaseSchema):
    """Player biographical and physical information from league bio stats."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    player_name: str = pa.Field(metadata={"description": "Player display name"})
    team_id: int | None = pa.Field(nullable=True, gt=0, metadata={"description": "Team identifier"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    age: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Player age"})
    player_height: str | None = pa.Field(
        nullable=True, metadata={"description": "Player height as string (e.g. 6-8)"}
    )
    player_height_inches: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Player height in inches"}
    )
    player_weight: str | None = pa.Field(
        nullable=True, metadata={"description": "Player weight as string"}
    )
    college: str | None = pa.Field(nullable=True, metadata={"description": "College attended"})
    country: str | None = pa.Field(nullable=True, metadata={"description": "Country of origin"})
    draft_year: str | None = pa.Field(nullable=True, metadata={"description": "Year drafted"})
    draft_round: str | None = pa.Field(nullable=True, metadata={"description": "Round drafted"})
    draft_number: str | None = pa.Field(
        nullable=True, metadata={"description": "Overall draft pick number"}
    )
    gp: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Games played"})
    pts: float | None = pa.Field(nullable=True, ge=0.0, metadata={"description": "Points per game"})
    reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per game"}
    )
    ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per game"}
    )
    net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Net rating (offensive - defensive)"}
    )
    oreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Offensive rebound percentage"}
    )
    dreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Defensive rebound percentage"}
    )
    usg_pct: float | None = pa.Field(nullable=True, metadata={"description": "Usage percentage"})
    ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "True shooting percentage"}
    )
    ast_pct: float | None = pa.Field(nullable=True, metadata={"description": "Assist percentage"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})


class AggPlayerCareerSchema(BaseSchema):
    """Career-aggregated stats per player across regular seasons."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    career_gp: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Career games played"}
    )
    career_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career total minutes"}
    )
    career_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career total points"}
    )
    career_ppg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career points per game"}
    )
    career_rpg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career rebounds per game"}
    )
    career_apg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career assists per game"}
    )
    career_spg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career steals per game"}
    )
    career_bpg: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Career blocks per game"}
    )
    career_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career field goal percentage"}
    )
    career_fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career three-point percentage"}
    )
    career_ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career free throw percentage"}
    )
    first_season: str | None = pa.Field(
        nullable=True, metadata={"description": "First season played"}
    )
    last_season: str | None = pa.Field(
        nullable=True, metadata={"description": "Last season played"}
    )
    seasons_played: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total seasons played"}
    )


class AggPlayerRollingSchema(BaseSchema):
    """Rolling window averages (5/10/20 games) for player pts, reb, ast."""

    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    game_date: str = pa.Field(metadata={"description": "Game date"})
    pts_roll5: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "5-game rolling average points"}
    )
    reb_roll5: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "5-game rolling average rebounds"}
    )
    ast_roll5: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "5-game rolling average assists"}
    )
    pts_roll10: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "10-game rolling average points"}
    )
    reb_roll10: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "10-game rolling average rebounds"}
    )
    ast_roll10: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "10-game rolling average assists"}
    )
    pts_roll20: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "20-game rolling average points"}
    )
    reb_roll20: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "20-game rolling average rebounds"}
    )
    ast_roll20: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "20-game rolling average assists"}
    )


class AggPlayerSeasonAdvancedSchema(BaseSchema):
    """Per-season advanced stat aggregates for a player including efficiency metrics."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_off_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average offensive rating"}
    )
    avg_def_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average defensive rating"}
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average net rating"}
    )
    avg_ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average true shooting percentage"}
    )
    avg_usg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average usage percentage"}
    )
    avg_efg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average effective FG%"}
    )
    avg_ast_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average assist percentage"}
    )
    avg_ast_ratio: float | None = pa.Field(
        nullable=True, metadata={"description": "Average assist ratio"}
    )
    avg_oreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average offensive rebound percentage"}
    )
    avg_dreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average defensive rebound percentage"}
    )
    avg_reb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average total rebound percentage"}
    )
    avg_tov_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average turnover percentage"}
    )
    avg_pace: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average pace"}
    )
    avg_pie: float | None = pa.Field(
        nullable=True, metadata={"description": "Average player impact estimate"}
    )


class AggPlayerSeasonSchema(BaseSchema):
    """Player season aggregates joining traditional and advanced game logs."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    total_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total minutes played"}
    )
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    total_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total points scored"}
    )
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    total_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total rebounds"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    total_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total assists"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    total_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total steals"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    total_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total blocks"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    total_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total turnovers"}
    )
    avg_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average turnovers per game"}
    )
    total_fgm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total field goals made"}
    )
    total_fga: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total field goals attempted"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    total_fg3m: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total three-pointers made"}
    )
    total_fg3a: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total three-pointers attempted"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    total_ftm: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total free throws made"}
    )
    total_fta: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Total free throws attempted"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
    avg_off_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average offensive rating"}
    )
    avg_def_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average defensive rating"}
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average net rating"}
    )
    avg_ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average true shooting percentage"}
    )
    avg_usg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Average usage percentage"}
    )
    avg_pie: float | None = pa.Field(
        nullable=True, metadata={"description": "Average player impact estimate"}
    )


class AggPlayerSeasonPer36Schema(BaseSchema):
    """Per-36-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    pts_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points per 36 minutes"}
    )
    reb_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per 36 minutes"}
    )
    ast_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per 36 minutes"}
    )
    stl_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Steals per 36 minutes"}
    )
    blk_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Blocks per 36 minutes"}
    )
    tov_per36: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Turnovers per 36 minutes"}
    )


class AggPlayerSeasonPer48Schema(BaseSchema):
    """Per-48-minute rates derived from agg_player_season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_min: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average minutes per game"}
    )
    pts_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Points per 48 minutes"}
    )
    reb_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Rebounds per 48 minutes"}
    )
    ast_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Assists per 48 minutes"}
    )
    stl_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Steals per 48 minutes"}
    )
    blk_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Blocks per 48 minutes"}
    )
    tov_per48: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Turnovers per 48 minutes"}
    )


class AggShotLocationSeasonSchema(BaseSchema):
    """Shot-location season stats with per-season FGM ranking."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    fgm: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Field goals made"})
    season_fgm_rank: int = pa.Field(ge=1, metadata={"description": "Season FGM rank"})


class AggShotZonesSchema(BaseSchema):
    """Player shooting stats aggregated by court zone per season."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    shot_zone_basic: str | None = pa.Field(
        nullable=True, metadata={"description": "Basic shot zone classification"}
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True, metadata={"description": "Shot zone area (left, center, right)"}
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True, metadata={"description": "Shot distance range"}
    )
    attempts: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Shot attempts in zone"}
    )
    makes: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Shots made in zone"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage in zone"}
    )
    avg_distance: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average shot distance in feet"}
    )


class AggTeamFranchiseSchema(BaseSchema):
    """Franchise history with derived age and win-percentage columns."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    team_city: str | None = pa.Field(nullable=True, metadata={"description": "Franchise city"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Franchise name"})
    start_year: int | None = pa.Field(
        nullable=True, metadata={"description": "Franchise start year"}
    )
    end_year: int | None = pa.Field(nullable=True, metadata={"description": "Franchise end year"})
    years: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total years in league"}
    )
    games: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Total games played"}
    )
    wins: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Total wins"})
    losses: int | None = pa.Field(nullable=True, ge=0, metadata={"description": "Total losses"})
    win_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Historical win percentage"}
    )
    po_appearances: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Playoff appearances"}
    )
    div_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Division titles won"}
    )
    conf_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Conference titles won"}
    )
    league_titles: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "League championships won"}
    )
    franchise_age_years: int | None = pa.Field(
        nullable=True, ge=0, metadata={"description": "Franchise age in years"}
    )
    computed_win_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Computed win percentage (wins/games)"}
    )


class AggTeamPaceAndEfficiencySchema(BaseSchema):
    """Team-season pace and four-factor efficiency from advanced game logs."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_pace: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average pace (possessions per 48 min)"}
    )
    avg_ortg: float | None = pa.Field(
        nullable=True, metadata={"description": "Average offensive rating"}
    )
    avg_drtg: float | None = pa.Field(
        nullable=True, metadata={"description": "Average defensive rating"}
    )
    avg_net_rtg: float | None = pa.Field(
        nullable=True, metadata={"description": "Average net rating"}
    )


class AggTeamSeasonSchema(BaseSchema):
    """Team season aggregates from fact_team_game joined with dim_game."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Unique team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(
        metadata={"description": "Season type (Regular Season, Playoffs, etc.)"}
    )
    gp: int = pa.Field(ge=0, metadata={"description": "Games played"})
    avg_pts: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average assists per game"}
    )
    avg_stl: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average steals per game"}
    )
    avg_blk: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average blocks per game"}
    )
    avg_tov: float | None = pa.Field(
        nullable=True, ge=0.0, metadata={"description": "Average turnovers per game"}
    )
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
