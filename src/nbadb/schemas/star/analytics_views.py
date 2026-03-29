"""Pandera star-schema contracts for all 12 analytics_* view output tables."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema

# ---------------------------------------------------------------------------
# Private stat-field mixins (DRY helpers shared by multiple analytics views)
# ---------------------------------------------------------------------------


class _MinutesStatMixin(BaseSchema):
    """Minute totals shared by player-level and clutch analytics views."""

    min: float | None = pa.Field(nullable=True, metadata={"description": "Minutes played"})


class _TraditionalStatsMixin(BaseSchema):
    """Traditional box-score stat fields common to analytics views."""

    pts: float | None = pa.Field(nullable=True, metadata={"description": "Points scored"})
    reb: float | None = pa.Field(nullable=True, metadata={"description": "Total rebounds"})
    ast: float | None = pa.Field(nullable=True, metadata={"description": "Assists"})
    stl: float | None = pa.Field(nullable=True, metadata={"description": "Steals"})
    blk: float | None = pa.Field(nullable=True, metadata={"description": "Blocks"})
    tov: float | None = pa.Field(nullable=True, metadata={"description": "Turnovers"})
    pf: float | None = pa.Field(nullable=True, metadata={"description": "Personal fouls"})
    fgm: float | None = pa.Field(nullable=True, metadata={"description": "Field goals made"})
    fga: float | None = pa.Field(nullable=True, metadata={"description": "Field goals attempted"})
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    fg3m: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goals made"}
    )
    fg3a: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goals attempted"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )
    ftm: float | None = pa.Field(nullable=True, metadata={"description": "Free throws made"})
    fta: float | None = pa.Field(nullable=True, metadata={"description": "Free throws attempted"})
    ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Free throw percentage"}
    )
    oreb: float | None = pa.Field(nullable=True, metadata={"description": "Offensive rebounds"})
    dreb: float | None = pa.Field(nullable=True, metadata={"description": "Defensive rebounds"})
    plus_minus: float | None = pa.Field(
        nullable=True, metadata={"description": "Plus-minus differential"}
    )


class _AdvancedStatsMixin(BaseSchema):
    """Advanced analytics fields common to multiple analytics views."""

    off_rating: float | None = pa.Field(nullable=True, metadata={"description": "Offensive rating"})
    def_rating: float | None = pa.Field(nullable=True, metadata={"description": "Defensive rating"})
    net_rating: float | None = pa.Field(nullable=True, metadata={"description": "Net rating"})
    efg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Effective field goal percentage"}
    )
    ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "True shooting percentage"}
    )
    pace: float | None = pa.Field(
        nullable=True, metadata={"description": "Pace (possessions per 48 min)"}
    )
    pie: float | None = pa.Field(nullable=True, metadata={"description": "Player impact estimate"})
    ast_pct: float | None = pa.Field(nullable=True, metadata={"description": "Assist percentage"})
    reb_pct: float | None = pa.Field(nullable=True, metadata={"description": "Rebound percentage"})
    oreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Offensive rebound percentage"}
    )
    dreb_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Defensive rebound percentage"}
    )


class _HustleStatsMixin(BaseSchema):
    """Hustle stat fields common to multiple analytics views."""

    contested_shots: float | None = pa.Field(
        nullable=True, metadata={"description": "Contested shots"}
    )
    deflections: float | None = pa.Field(nullable=True, metadata={"description": "Deflections"})
    loose_balls_recovered: float | None = pa.Field(
        nullable=True, metadata={"description": "Loose balls recovered"}
    )
    charges_drawn: float | None = pa.Field(nullable=True, metadata={"description": "Charges drawn"})
    screen_assists: float | None = pa.Field(
        nullable=True, metadata={"description": "Screen assists"}
    )


class _MiscStatsMixin(BaseSchema):
    """Miscellaneous stat fields common to multiple analytics views."""

    pts_off_tov: float | None = pa.Field(
        nullable=True, metadata={"description": "Points off turnovers"}
    )
    second_chance_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Second chance points"}
    )
    fbps: float | None = pa.Field(nullable=True, metadata={"description": "Fast break points"})
    pitp: float | None = pa.Field(nullable=True, metadata={"description": "Points in the paint"})


class _TrackingStatsMixin(BaseSchema):
    """Player/team tracking stat fields common to multiple analytics views."""

    dist: float | None = pa.Field(
        nullable=True, metadata={"description": "Distance traveled (miles)"}
    )
    spd: float | None = pa.Field(nullable=True, metadata={"description": "Average speed (mph)"})
    tchs: float | None = pa.Field(nullable=True, metadata={"description": "Touches"})
    passes: float | None = pa.Field(nullable=True, metadata={"description": "Passes made"})


# ---------------------------------------------------------------------------
# Analytics view schemas
# ---------------------------------------------------------------------------


class AnalyticsClutchPerformanceSchema(_MinutesStatMixin, _TraditionalStatsMixin):
    """Clutch performance stats joined with player and team dimensions."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    clutch_window: str = pa.Field(metadata={"description": "Clutch window definition"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    gp: int | None = pa.Field(nullable=True, metadata={"description": "Games played"})
    w: int | None = pa.Field(nullable=True, metadata={"description": "Wins"})
    l: int | None = pa.Field(nullable=True, metadata={"description": "Losses"})  # noqa: E741
    net_rating: float | None = pa.Field(nullable=True, metadata={"description": "Net rating"})
    off_rating: float | None = pa.Field(nullable=True, metadata={"description": "Offensive rating"})
    def_rating: float | None = pa.Field(nullable=True, metadata={"description": "Defensive rating"})


class AnalyticsDraftValueSchema(BaseSchema):
    """Draft picks enriched with career stats from agg_player_career."""

    person_id: int = pa.Field(gt=0, metadata={"description": "Drafted player identifier"})
    season: str = pa.Field(metadata={"description": "Draft season"})
    round_number: int | None = pa.Field(
        nullable=True, metadata={"description": "Draft round number"}
    )
    round_pick: int | None = pa.Field(
        nullable=True, metadata={"description": "Pick within the round"}
    )
    overall_pick: int | None = pa.Field(
        nullable=True, metadata={"description": "Overall pick number"}
    )
    team_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Drafting team identifier"}
    )
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    position: str | None = pa.Field(nullable=True, metadata={"description": "Player position"})
    country: str | None = pa.Field(
        nullable=True, metadata={"description": "Player country of origin"}
    )
    career_gp: int | None = pa.Field(nullable=True, metadata={"description": "Career games played"})
    career_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Career total points"}
    )
    career_ppg: float | None = pa.Field(
        nullable=True, metadata={"description": "Career points per game"}
    )
    career_rpg: float | None = pa.Field(
        nullable=True, metadata={"description": "Career rebounds per game"}
    )
    career_apg: float | None = pa.Field(
        nullable=True, metadata={"description": "Career assists per game"}
    )
    career_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career field goal percentage"}
    )
    career_fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Career three-point percentage"}
    )
    seasons_played: int | None = pa.Field(
        nullable=True, metadata={"description": "Total seasons played"}
    )
    first_season: str | None = pa.Field(
        nullable=True, metadata={"description": "First season played"}
    )
    last_season: str | None = pa.Field(
        nullable=True, metadata={"description": "Last season played"}
    )


class AnalyticsGameSummarySchema(BaseSchema):
    """Game summary combining dim_game, fact_game_result, and team info."""

    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    game_date: str = pa.Field(metadata={"description": "Game date"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Season type"})
    matchup: str | None = pa.Field(
        nullable=True, metadata={"description": "Matchup description string"}
    )
    arena_name: str | None = pa.Field(nullable=True, metadata={"description": "Arena name"})
    home_team_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Home team identifier"}
    )
    home_team_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Home team full name"}
    )
    home_team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Home team abbreviation"}
    )
    away_team_id: int | None = pa.Field(
        nullable=True, gt=0, metadata={"description": "Away team identifier"}
    )
    away_team_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Away team full name"}
    )
    away_team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Away team abbreviation"}
    )
    pts_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home team total points"}
    )
    pts_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away team total points"}
    )
    plus_minus_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home team plus-minus"}
    )
    wl_home: str | None = pa.Field(
        nullable=True, metadata={"description": "Home team win/loss result"}
    )
    pts_qtr1_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home Q1 points"}
    )
    pts_qtr2_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home Q2 points"}
    )
    pts_qtr3_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home Q3 points"}
    )
    pts_qtr4_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home Q4 points"}
    )
    pts_ot1_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home OT1 points"}
    )
    pts_ot2_home: float | None = pa.Field(
        nullable=True, metadata={"description": "Home OT2 points"}
    )
    pts_qtr1_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away Q1 points"}
    )
    pts_qtr2_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away Q2 points"}
    )
    pts_qtr3_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away Q3 points"}
    )
    pts_qtr4_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away Q4 points"}
    )
    pts_ot1_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away OT1 points"}
    )
    pts_ot2_away: float | None = pa.Field(
        nullable=True, metadata={"description": "Away OT2 points"}
    )


class AnalyticsHeadToHeadSchema(BaseSchema):
    """Team head-to-head matchup aggregates per season."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    opponent_team_id: int = pa.Field(gt=0, metadata={"description": "Opponent team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    team_abbr: str | None = pa.Field(nullable=True, metadata={"description": "Team abbreviation"})
    opponent_abbr: str | None = pa.Field(
        nullable=True, metadata={"description": "Opponent team abbreviation"}
    )
    games_played: int = pa.Field(metadata={"description": "Number of games in matchup"})
    wins: int = pa.Field(metadata={"description": "Wins against opponent"})
    losses: int = pa.Field(metadata={"description": "Losses against opponent"})
    avg_pts_scored: float | None = pa.Field(
        nullable=True, metadata={"description": "Average points scored per game"}
    )
    avg_pts_allowed: float | None = pa.Field(
        nullable=True, metadata={"description": "Average points allowed per game"}
    )
    avg_margin: float | None = pa.Field(
        nullable=True, metadata={"description": "Average point margin"}
    )


class AnalyticsLeagueBenchmarksSchema(BaseSchema):
    """League-wide season benchmarks from player and team aggregates."""

    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Season type"})
    total_players: int = pa.Field(metadata={"description": "Total qualifying players in season"})
    league_avg_ppg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average points per game"}
    )
    league_avg_rpg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average rebounds per game"}
    )
    league_avg_apg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average assists per game"}
    )
    league_avg_spg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average steals per game"}
    )
    league_avg_bpg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average blocks per game"}
    )
    league_avg_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average field goal percentage"}
    )
    league_avg_fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average three-point percentage"}
    )
    league_avg_ft_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average free throw percentage"}
    )
    league_avg_ts_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average true shooting percentage"}
    )
    league_avg_usg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average usage percentage"}
    )
    total_teams: int | None = pa.Field(
        nullable=True, metadata={"description": "Total teams in season"}
    )
    league_avg_team_ppg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average team points per game"}
    )
    league_avg_team_rpg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average team rebounds per game"}
    )
    league_avg_team_apg: float | None = pa.Field(
        nullable=True, metadata={"description": "League average team assists per game"}
    )
    league_avg_team_fg_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "League average team field goal percentage"},
    )
    league_avg_team_fg3_pct: float | None = pa.Field(
        nullable=True,
        metadata={"description": "League average team three-point percentage"},
    )


class AnalyticsPlayerGameCompleteSchema(
    _MinutesStatMixin,
    _TraditionalStatsMixin,
    _AdvancedStatsMixin,
    _MiscStatsMixin,
    _HustleStatsMixin,
    _TrackingStatsMixin,
):
    """Complete player-game stats joining traditional, advanced, misc, hustle, tracking."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    game_date: str | None = pa.Field(nullable=True, metadata={"description": "Game date"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    ast_ratio: float | None = pa.Field(nullable=True, metadata={"description": "Assist ratio"})
    usg_pct: float | None = pa.Field(nullable=True, metadata={"description": "Usage percentage"})
    dfg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Defended field goal percentage"}
    )


class AnalyticsPlayerImpactSchema(BaseSchema):
    """Player impact combining season stats with on/off court splits."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Season type"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    gp: int | None = pa.Field(nullable=True, metadata={"description": "Games played"})
    avg_min: float | None = pa.Field(
        nullable=True, metadata={"description": "Average minutes per game"}
    )
    avg_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, metadata={"description": "Average assists per game"}
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
    on_off_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team offensive rating with player on court"}
    )
    on_def_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team defensive rating with player on court"}
    )
    on_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team net rating with player on court"}
    )
    on_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Team points with player on court"}
    )
    on_reb: float | None = pa.Field(
        nullable=True, metadata={"description": "Team rebounds with player on court"}
    )
    on_ast: float | None = pa.Field(
        nullable=True, metadata={"description": "Team assists with player on court"}
    )
    off_off_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team offensive rating with player off court"}
    )
    off_def_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team defensive rating with player off court"}
    )
    off_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Team net rating with player off court"}
    )
    net_rating_diff: float | None = pa.Field(
        nullable=True,
        metadata={"description": "On-court minus off-court net rating differential"},
    )


class AnalyticsPlayerMatchupSchema(BaseSchema):
    """Player-vs-player matchup stats enriched with dimension names."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Player identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    vs_player_id: int = pa.Field(gt=0, metadata={"description": "Opposing player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    vs_player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Opposing player display name"}
    )
    matchup_min: float | None = pa.Field(
        nullable=True, metadata={"description": "Minutes in matchup"}
    )
    player_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Player points in matchup"}
    )
    team_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Team points during matchup"}
    )
    ast: float | None = pa.Field(nullable=True, metadata={"description": "Assists in matchup"})
    tov: float | None = pa.Field(nullable=True, metadata={"description": "Turnovers in matchup"})
    stl: float | None = pa.Field(nullable=True, metadata={"description": "Steals in matchup"})
    blk: float | None = pa.Field(nullable=True, metadata={"description": "Blocks in matchup"})
    fgm: float | None = pa.Field(nullable=True, metadata={"description": "Field goals made"})
    fga: float | None = pa.Field(nullable=True, metadata={"description": "Field goals attempted"})
    fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Field goal percentage"}
    )
    fg3m: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goals made"}
    )
    fg3a: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goals attempted"}
    )
    fg3_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "Three-point field goal percentage"}
    )


class AnalyticsPlayerSeasonCompleteSchema(BaseSchema):
    """Complete player-season stats with totals, per-36, and per-48 rates."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Season type"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    gp: int | None = pa.Field(nullable=True, metadata={"description": "Games played"})
    total_min: float | None = pa.Field(
        nullable=True, metadata={"description": "Total minutes played"}
    )
    total_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Total points scored"}
    )
    total_reb: float | None = pa.Field(nullable=True, metadata={"description": "Total rebounds"})
    total_ast: float | None = pa.Field(nullable=True, metadata={"description": "Total assists"})
    total_stl: float | None = pa.Field(nullable=True, metadata={"description": "Total steals"})
    total_blk: float | None = pa.Field(nullable=True, metadata={"description": "Total blocks"})
    total_tov: float | None = pa.Field(nullable=True, metadata={"description": "Total turnovers"})
    avg_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, metadata={"description": "Average assists per game"}
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
    avg_off_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average offensive rating"}
    )
    avg_def_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average defensive rating"}
    )
    avg_net_rating: float | None = pa.Field(
        nullable=True, metadata={"description": "Average net rating"}
    )
    avg_pie: float | None = pa.Field(
        nullable=True, metadata={"description": "Average player impact estimate"}
    )
    # per-36
    pts_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Points per 36 minutes"}
    )
    reb_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Rebounds per 36 minutes"}
    )
    ast_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Assists per 36 minutes"}
    )
    stl_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Steals per 36 minutes"}
    )
    blk_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Blocks per 36 minutes"}
    )
    tov_per36: float | None = pa.Field(
        nullable=True, metadata={"description": "Turnovers per 36 minutes"}
    )
    # per-48
    pts_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Points per 48 minutes"}
    )
    reb_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Rebounds per 48 minutes"}
    )
    ast_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Assists per 48 minutes"}
    )
    stl_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Steals per 48 minutes"}
    )
    blk_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Blocks per 48 minutes"}
    )
    tov_per48: float | None = pa.Field(
        nullable=True, metadata={"description": "Turnovers per 48 minutes"}
    )


class AnalyticsShootingEfficiencySchema(BaseSchema):
    """Shot chart data enriched with league averages by zone."""

    player_id: int = pa.Field(gt=0, metadata={"description": "Unique player identifier"})
    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    player_name: str | None = pa.Field(
        nullable=True, metadata={"description": "Player display name"}
    )
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    game_date: str | None = pa.Field(nullable=True, metadata={"description": "Game date"})
    shot_zone_basic: str | None = pa.Field(
        nullable=True, metadata={"description": "Basic shot zone classification"}
    )
    shot_zone_area: str | None = pa.Field(
        nullable=True, metadata={"description": "Shot zone area (left, center, right)"}
    )
    shot_zone_range: str | None = pa.Field(
        nullable=True, metadata={"description": "Shot distance range"}
    )
    shot_distance: float | None = pa.Field(
        nullable=True, metadata={"description": "Shot distance in feet"}
    )
    shot_type: str | None = pa.Field(nullable=True, metadata={"description": "Shot type (2PT/3PT)"})
    shot_made_flag: int | None = pa.Field(
        nullable=True, metadata={"description": "Shot made indicator (1=made, 0=missed)"}
    )
    loc_x: float | None = pa.Field(
        nullable=True, metadata={"description": "Shot location X coordinate"}
    )
    loc_y: float | None = pa.Field(
        nullable=True, metadata={"description": "Shot location Y coordinate"}
    )
    league_avg_fgm: float | None = pa.Field(
        nullable=True, metadata={"description": "League average field goals made in zone"}
    )
    league_avg_fga: float | None = pa.Field(
        nullable=True,
        metadata={"description": "League average field goals attempted in zone"},
    )
    league_avg_fg_pct: float | None = pa.Field(
        nullable=True, metadata={"description": "League average FG% in zone"}
    )


class AnalyticsTeamGameCompleteSchema(
    _TraditionalStatsMixin,
    _AdvancedStatsMixin,
    _MiscStatsMixin,
    _HustleStatsMixin,
    _TrackingStatsMixin,
):
    """Complete team-game stats joining traditional, advanced, misc, hustle, tracking."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    game_id: str = pa.Field(metadata={"description": "Unique game identifier"})
    season_year: str | None = pa.Field(
        nullable=True, metadata={"description": "Season year (e.g. 2024-25)"}
    )
    game_date: str | None = pa.Field(nullable=True, metadata={"description": "Game date"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team full name"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )


class AnalyticsTeamSeasonSummarySchema(BaseSchema):
    """Team season summary combining aggregates with standings."""

    team_id: int = pa.Field(gt=0, metadata={"description": "Team identifier"})
    season_year: str = pa.Field(metadata={"description": "Season year (e.g. 2024-25)"})
    season_type: str = pa.Field(metadata={"description": "Season type"})
    team_name: str | None = pa.Field(nullable=True, metadata={"description": "Team full name"})
    team_abbreviation: str | None = pa.Field(
        nullable=True, metadata={"description": "Team abbreviation code"}
    )
    gp: int | None = pa.Field(nullable=True, metadata={"description": "Games played"})
    avg_pts: float | None = pa.Field(
        nullable=True, metadata={"description": "Average points per game"}
    )
    avg_reb: float | None = pa.Field(
        nullable=True, metadata={"description": "Average rebounds per game"}
    )
    avg_ast: float | None = pa.Field(
        nullable=True, metadata={"description": "Average assists per game"}
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
    wins: int | None = pa.Field(nullable=True, metadata={"description": "Season wins"})
    losses: int | None = pa.Field(nullable=True, metadata={"description": "Season losses"})
    win_pct: float | None = pa.Field(nullable=True, metadata={"description": "Win percentage"})
    conference: str | None = pa.Field(nullable=True, metadata={"description": "Conference name"})
    conference_rank: int | None = pa.Field(
        nullable=True, metadata={"description": "Conference standing rank"}
    )
    division: str | None = pa.Field(nullable=True, metadata={"description": "Division name"})
    division_rank: int | None = pa.Field(
        nullable=True, metadata={"description": "Division standing rank"}
    )
