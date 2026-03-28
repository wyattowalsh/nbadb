from __future__ import annotations

import json
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from loguru import logger

if TYPE_CHECKING:
    from pathlib import Path

from nbadb.core.config import get_settings

TABLE_DESCRIPTIONS: dict[str, str] = {
    # --- Dimensions (17) ---
    "dim_all_players": "Master player directory with player IDs, names, and active status for every NBA player in history.",
    "dim_arena": "NBA arenas with name, city, state, country, and timezone. Surrogate key assigned.",
    "dim_coach": "Coaching staff by team and season, including head coaches and assistants.",
    "dim_college": "Lookup table of college/university names with surrogate IDs.",
    "dim_date": "Calendar dimension from 1946 to present+1yr with NBA season mapping, day-of-week, and weekend flags.",
    "dim_defunct_team": "Historical teams no longer active in the NBA, from FranchiseHistory.",
    "dim_game": "Game dimension with date, season, home/visitor teams, matchup, and arena. One row per game.",
    "dim_official": "NBA referees with official ID, name, and jersey number.",
    "dim_play_event_type": "Reference lookup for play-by-play event types (made_shot, rebound, foul, etc.).",
    "dim_player": "SCD Type 2 player dimension tracking team, position, and jersey changes across seasons.",
    "dim_season": "NBA seasons with start and end dates, derived from game log.",
    "dim_season_phase": "Reference lookup for season phases: Preseason, Regular, Play-In, Playoffs R1-R2, Conference Finals, Finals, All-Star.",
    "dim_season_week": "Schedule week boundaries by season from the NBA schedule endpoint.",
    "dim_shot_zone": "Distinct shot zone combinations (basic, area, range) with surrogate IDs.",
    "dim_team": "Current NBA teams with abbreviation, city, state, arena, conference, and division.",
    "dim_team_extended": "Extended team attributes joining team details, common info, and active years.",
    "dim_team_history": "SCD Type 2 team history tracking city, nickname, and abbreviation changes over time.",
    # --- Bridges (5) ---
    "bridge_game_official": "Many-to-many bridge linking games to their assigned officials.",
    "bridge_game_team": "Bridge linking each game to both participating teams with home/away side and win-loss outcome.",
    "bridge_lineup_player": "Exploded bridge linking lineup group IDs to individual players and lineup slot order.",
    "bridge_play_player": "Many-to-many bridge linking play-by-play events to involved players.",
    "bridge_player_team_season": "Bridge linking players to teams by season with jersey number and listed position.",
    # --- Facts (127) ---
    "fact_box_score_advanced_team": "Team-level advanced box score stats per game: offensive/defensive rating, pace, eFG%, TS%, AST ratio.",
    "fact_box_score_defensive_team": "Team-level defensive box score stats per game.",
    "fact_box_score_four_factors": "Player-level Four Factors stats per game: eFG%, TOV%, OREB%, FT rate.",
    "fact_box_score_four_factors_team": "Team-level Four Factors stats per game: eFG%, TOV%, OREB%, FT rate.",
    "fact_box_score_hustle_player": "Player-level hustle stats per game: contested shots, deflections, loose balls, charges drawn, screen assists.",
    "fact_box_score_misc_team": "Team-level miscellaneous box score stats per game: points off turnovers, second chance points, fast break points, points in the paint.",
    "fact_box_score_player_track_team": "Team-level player tracking box score stats per game: distance, speed, touches, passes.",
    "fact_box_score_scoring_team": "Team-level scoring breakdown per game: points by quarter, half, and overtime.",
    "fact_box_score_starter_bench": "Starter vs. bench split box score stats per game per team.",
    "fact_box_score_summary_v3": "V3 box score summary with game-level totals for both teams.",
    "fact_box_score_team": "Team-level traditional box score stats per game: PTS, REB, AST, FG/FT/3PT shooting.",
    "fact_box_score_usage_team": "Team-level usage and efficiency box score stats per game.",
    "fact_college_rollup": "Aggregated stats by college/university — how many NBA players each school produced.",
    "fact_cumulative_stats": "Cumulative (running total) player stats across the season.",
    "fact_cumulative_stats_detail": "Detailed cumulative player stats with multiple time-window breakdowns.",
    "fact_defense_hub": "Defensive matchup statistics: points allowed, FG% against, by player/team.",
    "fact_defense_hub_detail": "Consolidated defensive leaderboard across 10 metrics (DREB, STL, BLK, def rating, plus-minus, DFG%) with rank per team.",
    "fact_draft": "NBA draft picks with round, pick number, team, organization, and combine measurements (height, weight, wingspan, vertical leap, sprint, bench press).",
    "fact_draft_board": "Draft board data with player rankings and projections.",
    "fact_draft_combine_detail": "Detailed NBA Draft Combine measurements and athletic testing results.",
    "fact_fantasy": "Fantasy basketball data from FanDuel, fantasy widgets, and player fantasy profiles (last 5 games avg, season avg).",
    "fact_franchise_detail": "Franchise-level detail: championships, conference titles, division titles, and historical records.",
    "fact_game_context": "Contextual game information: national TV broadcast, attendance, lead changes, times tied.",
    "fact_game_leaders": "Top performers per game with points, rebounds, and assists leaders.",
    "fact_game_result": "Game outcomes with final scores, winner/loser, and point differential.",
    "fact_game_scoring": "Scoring breakdown by period (quarter, overtime) for each game.",
    "fact_gl_alum_similarity": "G League alumni similarity scores — comparing G League and NBA performance.",
    "fact_homepage": "NBA homepage featured content and standings snapshot.",
    "fact_homepage_detail": "Consolidated homepage stat leaders across 8 metrics (PTS, REB, AST, STL, FG%, FT%, 3PT%, BLK) with rank per team.",
    "fact_homepage_leaders": "League leaders featured on the NBA homepage (top scorers, rebounders, assisters).",
    "fact_homepage_leaders_detail": "Homepage scoring leaders with main, league average, and league max variants — PTS, FG%, eFG%, TS%, per48.",
    "fact_hustle_availability": "Hustle stats data availability flags by season and stat type.",
    "fact_ist_standings": "NBA In-Season Tournament (IST/NBA Cup) standings by group.",
    "fact_leaders_tiles": "League leader tiles/cards with top performers across stat categories.",
    "fact_leaders_tiles_detail": "Leader tile variants (all-time high, last season, main, low season) for scoring leaders with rank and team.",
    "fact_league_dash_player_stats": "League-wide player dashboard stats per season: traditional stats with filters for clutch, shooting splits, etc.",
    "fact_league_dash_team_stats": "League-wide team dashboard stats per season with traditional and advanced metrics.",
    "fact_league_game_finder": "Game finder results matching search criteria across NBA history.",
    "fact_league_hustle": "League-wide hustle stats leaders per season: deflections, contested shots, loose balls.",
    "fact_league_leaders_detail": "Detailed league leaders across multiple statistical categories per season.",
    "fact_league_lineup_viz": "Lineup visualization data showing five-man unit performance metrics.",
    "fact_league_pt_shots": "League-wide player tracking shot data: shot type, distance, and closest defender.",
    "fact_league_shot_locations": "League-wide shooting by court location and distance.",
    "fact_league_team_clutch": "Team-level clutch performance stats across the league per season.",
    "fact_lineup_stats": "Five-man lineup combination stats from both league-wide and team-specific sources.",
    "fact_matchup": "Head-to-head matchup statistics between teams across seasons.",
    "fact_on_off_detail": "Detailed on/off court impact stats — team performance when a player is on vs. off the floor.",
    "fact_play_by_play": "Every play-by-play event with game clock, score, event type (made_shot, rebound, foul, etc.), and up to 3 involved players.",
    "fact_player_available_seasons": "Seasons with available data for each player from CommonPlayerInfo.",
    "fact_player_awards": "Player awards and honors (MVP, All-Star, All-NBA, etc.) by season.",
    "fact_player_career": "Career-level player statistics and milestones.",
    "fact_player_clutch_detail": "Player clutch stats across 11 time/score windows (last 5min/3min/1min/30sec/10sec with varying point margins).",
    "fact_player_dashboard_clutch_overall": "Player dashboard clutch overview stats per season.",
    "fact_player_dashboard_game_splits_overall": "Player dashboard game splits overview (home/road, wins/losses, by month).",
    "fact_player_dashboard_general_splits_overall": "Player dashboard general splits overview per season.",
    "fact_player_dashboard_last_n_overall": "Player dashboard last-N-games overview stats.",
    "fact_player_dashboard_shooting_overall": "Player dashboard shooting overview with zone breakdowns.",
    "fact_player_dashboard_team_perf_overall": "Player dashboard team performance overview — stats by game outcome.",
    "fact_player_dashboard_yoy_overall": "Player dashboard year-over-year comparison overview.",
    "fact_player_estimated_metrics": "Player-level estimated advanced metrics: OffRtg, DefRtg, NetRtg, pace, usage per season.",
    "fact_player_game_advanced": "Player game-level advanced stats: offensive/defensive rating, net rating, eFG%, TS%, AST%, USG%, PIE.",
    "fact_player_game_hustle": "Player game-level hustle stats: contested shots, deflections, loose balls, charges drawn, screen assists.",
    "fact_player_game_log": "Player game log with traditional stats, result, and matchup per game.",
    "fact_player_game_misc": "Player game-level miscellaneous stats: points off turnovers, second chance points, fast break points.",
    "fact_player_game_splits_detail": "Detailed player game splits across multiple dimensions (location, outcome, etc.).",
    "fact_player_game_tracking": "Player game-level tracking stats: distance, speed, touches, passes, contested/uncontested FG%.",
    "fact_player_game_traditional": "Player game-level traditional box score: PTS, REB, AST, STL, BLK, TOV, FG/3PT/FT shooting, plus-minus.",
    "fact_player_general_splits_detail": "Detailed player general splits (by conference, division, opponent, days rest, etc.).",
    "fact_player_headline_stats": "Player headline/summary stats from CommonPlayerInfo (career PPG, RPG, APG).",
    "fact_player_last_n_detail": "Detailed player stats over last-N-games windows (last 5, 10, 15, 20 games).",
    "fact_player_matchups": "Player vs. player matchup stats from head-to-head and comparison endpoints.",
    "fact_player_matchups_detail": "Detailed player-vs-player comparison stats from PlayerCompare and PlayerVsPlayer endpoints with on/off court splits.",
    "fact_player_matchups_shot_detail": "Player-vs-player shooting splits by shot area and distance with on/off court scoping.",
    "fact_player_next_games": "Upcoming scheduled games for each player.",
    "fact_player_profile": "Player profile data including bio, career highlights, and current season stats.",
    "fact_player_pt_reb_detail": "Detailed player tracking rebounding: contested/uncontested, by shot type and distance.",
    "fact_player_pt_shots_detail": "Detailed player tracking shooting: by shot type, dribble count, closest defender distance.",
    "fact_player_pt_tracking": "Consolidated player tracking data across 6 types: passing, receiving, rebounding, shooting, shot defense, and defense.",
    "fact_player_season_ranks": "Player season statistical rankings across all major categories.",
    "fact_player_shooting_splits_detail": "Detailed player shooting splits by zone, distance, and shot type.",
    "fact_player_splits": "Player stat splits by various dimensions (home/road, wins/losses, opponent, month).",
    "fact_player_team_perf_detail": "Detailed player stats segmented by team performance (blowout wins, close games, losses).",
    "fact_player_yoy_detail": "Detailed player year-over-year stat comparisons across seasons.",
    "fact_playoff_picture": "Current playoff picture with clinch scenarios, elimination status, and projected seedings.",
    "fact_playoff_series": "Playoff series results with series winner, game count, and matchup details.",
    "fact_rotation": "Player rotation data per game: check-in/out times, points scored, point differential, and usage during each stint.",
    "fact_scoreboard_detail": "Detailed scoreboard data with live game status, scores, and broadcast info.",
    "fact_scoreboard_v3": "V3 scoreboard with game summaries, scores, and current status.",
    "fact_scoreboard_win_probability": "Real-time win probability data from the scoreboard endpoint.",
    "fact_season_matchups": "Season-level head-to-head matchup records between teams.",
    "fact_shot_chart": "Every field goal attempt with court coordinates (x, y), shot zone, distance, action type, and make/miss flag.",
    "fact_shot_chart_league": "League-wide shot chart aggregates by zone and area.",
    "fact_shot_chart_league_averages": "League-wide average FG% by shot zone from both ShotChartDetail and ShotChartLineupDetail sources.",
    "fact_shot_chart_lineup": "Shot chart data broken down by lineup combination on the floor.",
    "fact_standings": "Team standings per season: W-L record, win%, conference/division rank, home/road record, streak.",
    "fact_streak_finder": "Historical streak finder results: longest winning/losing streaks matching criteria.",
    "fact_synergy": "Synergy play type data: PPP, efficiency, frequency by play type (PnR, isolation, transition, post-up, etc.) per player/team.",
    "fact_team_available_seasons": "Seasons with available data for each team.",
    "fact_team_awards_conf": "Team conference award history (conference championships).",
    "fact_team_awards_div": "Team division award history (division titles).",
    "fact_team_background": "Team background information: ownership, management, and front office details.",
    "fact_team_dashboard_general_overall": "Team dashboard general overview stats per season.",
    "fact_team_dashboard_shooting_overall": "Team dashboard shooting overview with zone breakdowns.",
    "fact_team_estimated_metrics": "Team-level estimated advanced metrics: OffRtg, DefRtg, NetRtg, pace per season.",
    "fact_team_game": "Team game-level traditional stats: PTS, REB, AST, STL, BLK, FG/3PT/FT shooting.",
    "fact_team_game_hustle": "Team game-level hustle stats: contested shots, deflections, loose balls, charges drawn.",
    "fact_team_game_log": "Team game log with traditional stats, result, and matchup per game.",
    "fact_team_general_splits_detail": "Detailed team general splits (by opponent, location, days rest, etc.).",
    "fact_team_historical": "Historical team records and all-time statistics.",
    "fact_team_history_detail": "Detailed team history from TeamDetails including seasons played and records.",
    "fact_team_hof": "Team's Hall of Fame players.",
    "fact_team_lineups_detail": "Detailed five-man lineup stats for each team.",
    "fact_team_lineups_overall": "Team lineup overview with top performing five-man combinations.",
    "fact_team_matchups": "Team vs. team matchup statistics across seasons.",
    "fact_team_matchups_detail": "Detailed team-vs-player comparison stats from TeamVsPlayer and TeamAndPlayersVsPlayers endpoints with on/off court splits.",
    "fact_team_matchups_shot_detail": "Team-vs-player shooting splits by shot area and distance with on/off court scoping.",
    "fact_team_player_dashboard": "Team player dashboard showing each player's contribution to the team.",
    "fact_team_pt_reb_detail": "Detailed team tracking rebounding: contested/uncontested, by shot type and distance.",
    "fact_team_pt_shots_detail": "Detailed team tracking shooting: by shot type, dribble count, closest defender.",
    "fact_team_pt_tracking": "Consolidated team tracking data across passing, receiving, rebounding, shooting, shot defense, and defense.",
    "fact_team_retired": "Retired jersey numbers by team.",
    "fact_team_season_ranks": "Team seasonal statistical rankings across major categories.",
    "fact_team_shooting_splits_detail": "Detailed team shooting splits by zone, distance, and shot type.",
    "fact_team_social_sites": "Team social media and website URLs.",
    "fact_team_splits": "Team stat splits by various dimensions (home/road, wins/losses, opponent).",
    "fact_tracking_defense": "Defensive player tracking: matchup stats, contested shots, FG% allowed.",
    "fact_win_probability": "Win probability by event for each game: home/visitor percentages, score, and margin at each play.",
    # --- Derived Aggregations (16) ---
    "agg_all_time_leaders": "All-time NBA leaders across 20 statistical categories (PTS, REB, AST, STL, BLK, FG%, 3PT%, etc.).",
    "agg_clutch_stats": "Aggregated clutch performance stats across multiple time/score window definitions.",
    "agg_league_leaders": "Current season league leaders across statistical categories.",
    "agg_lineup_efficiency": "Lineup efficiency metrics: offensive/defensive rating, net rating by five-man unit.",
    "agg_on_off_splits": "Aggregated on/off court splits showing team performance impact by player.",
    "agg_player_bio": "Player biographical aggregates: height, weight, age, experience distributions.",
    "agg_player_career": "Career totals and averages for every player: PTS, REB, AST, shooting splits.",
    "agg_player_rolling": "Rolling averages (e.g., last 5, 10, 15 games) for player stats.",
    "agg_player_season": "Player season aggregates: GP, totals, averages for traditional + advanced stats (OffRtg, DefRtg, TS%, USG%, PIE).",
    "agg_player_season_per36": "Player season stats normalized to per-36-minutes basis.",
    "agg_player_season_per48": "Player season stats normalized to per-48-minutes basis.",
    "agg_shot_location_season": "Season-level shooting aggregates by court location for each player.",
    "agg_shot_zones": "Shooting efficiency by zone per player per season: attempts, makes, FG%, average distance.",
    "agg_team_franchise": "Franchise-level all-time aggregates: total wins, losses, championships, playoff appearances.",
    "agg_team_pace_and_efficiency": "Team pace and efficiency metrics per season: possessions, offensive/defensive efficiency.",
    "agg_team_season": "Team season aggregates: GP, averages for PTS/REB/AST, and shooting percentages (FG/3PT/FT).",
    # --- Analytics Views (11) ---
    "analytics_draft_value": "Draft analytics joining pick position with player bio and career production for value comparisons.",
    "analytics_clutch_performance": "Wide analytics view joining clutch detail with player names and team abbreviations across all clutch windows.",
    "analytics_head_to_head": "Team head-to-head analytics with historical matchup records and stats.",
    "analytics_league_benchmarks": "Season-level benchmark view with league-average player and team metrics for comparison workflows.",
    "analytics_player_game_complete": "Denormalized player game view joining traditional, advanced, misc, hustle, and tracking stats with player/team/game dimensions.",
    "analytics_player_impact": "Player impact analytics combining season averages with on/off splits and team context.",
    "analytics_player_matchup": "Player matchup analytics comparing head-to-head performance between players.",
    "analytics_player_season_complete": "Complete player season analytics combining all stat categories into a single wide table.",
    "analytics_shooting_efficiency": "Shot-level analytics enriched with league average FG% by zone for relative efficiency analysis.",
    "analytics_team_game_complete": "Denormalized team game view combining box score stats across all categories with game context.",
    "analytics_team_season_summary": "Team season summary combining season aggregates, standings (W-L, win%, conference/division rank), and team info.",
}

TABLE_CATEGORIES: dict[str, list[str]] = {
    "dimensions": [
        "dim_all_players",
        "dim_arena",
        "dim_coach",
        "dim_college",
        "dim_date",
        "dim_defunct_team",
        "dim_game",
        "dim_official",
        "dim_play_event_type",
        "dim_player",
        "dim_season",
        "dim_season_phase",
        "dim_season_week",
        "dim_shot_zone",
        "dim_team",
        "dim_team_extended",
        "dim_team_history",
    ],
    "bridges": [
        "bridge_game_official",
        "bridge_game_team",
        "bridge_lineup_player",
        "bridge_play_player",
        "bridge_player_team_season",
    ],
    "facts": [
        "fact_box_score_advanced_team",
        "fact_box_score_defensive_team",
        "fact_box_score_four_factors",
        "fact_box_score_four_factors_team",
        "fact_box_score_hustle_player",
        "fact_box_score_misc_team",
        "fact_box_score_player_track_team",
        "fact_box_score_scoring_team",
        "fact_box_score_starter_bench",
        "fact_box_score_summary_v3",
        "fact_box_score_team",
        "fact_box_score_usage_team",
        "fact_college_rollup",
        "fact_cumulative_stats",
        "fact_cumulative_stats_detail",
        "fact_defense_hub",
        "fact_defense_hub_detail",
        "fact_draft",
        "fact_draft_board",
        "fact_draft_combine_detail",
        "fact_fantasy",
        "fact_franchise_detail",
        "fact_game_context",
        "fact_game_leaders",
        "fact_game_result",
        "fact_game_scoring",
        "fact_gl_alum_similarity",
        "fact_homepage",
        "fact_homepage_detail",
        "fact_homepage_leaders",
        "fact_homepage_leaders_detail",
        "fact_hustle_availability",
        "fact_ist_standings",
        "fact_leaders_tiles",
        "fact_leaders_tiles_detail",
        "fact_league_dash_player_stats",
        "fact_league_dash_team_stats",
        "fact_league_game_finder",
        "fact_league_hustle",
        "fact_league_leaders_detail",
        "fact_league_lineup_viz",
        "fact_league_pt_shots",
        "fact_league_shot_locations",
        "fact_league_team_clutch",
        "fact_lineup_stats",
        "fact_matchup",
        "fact_on_off_detail",
        "fact_play_by_play",
        "fact_player_available_seasons",
        "fact_player_awards",
        "fact_player_career",
        "fact_player_clutch_detail",
        "fact_player_dashboard_clutch_overall",
        "fact_player_dashboard_game_splits_overall",
        "fact_player_dashboard_general_splits_overall",
        "fact_player_dashboard_last_n_overall",
        "fact_player_dashboard_shooting_overall",
        "fact_player_dashboard_team_perf_overall",
        "fact_player_dashboard_yoy_overall",
        "fact_player_estimated_metrics",
        "fact_player_game_advanced",
        "fact_player_game_hustle",
        "fact_player_game_log",
        "fact_player_game_misc",
        "fact_player_game_splits_detail",
        "fact_player_game_tracking",
        "fact_player_game_traditional",
        "fact_player_general_splits_detail",
        "fact_player_headline_stats",
        "fact_player_last_n_detail",
        "fact_player_matchups",
        "fact_player_matchups_detail",
        "fact_player_matchups_shot_detail",
        "fact_player_next_games",
        "fact_player_profile",
        "fact_player_pt_reb_detail",
        "fact_player_pt_shots_detail",
        "fact_player_pt_tracking",
        "fact_player_season_ranks",
        "fact_player_shooting_splits_detail",
        "fact_player_splits",
        "fact_player_team_perf_detail",
        "fact_player_yoy_detail",
        "fact_playoff_picture",
        "fact_playoff_series",
        "fact_rotation",
        "fact_scoreboard_detail",
        "fact_scoreboard_v3",
        "fact_scoreboard_win_probability",
        "fact_season_matchups",
        "fact_shot_chart",
        "fact_shot_chart_league",
        "fact_shot_chart_league_averages",
        "fact_shot_chart_lineup",
        "fact_standings",
        "fact_streak_finder",
        "fact_synergy",
        "fact_team_available_seasons",
        "fact_team_awards_conf",
        "fact_team_awards_div",
        "fact_team_background",
        "fact_team_dashboard_general_overall",
        "fact_team_dashboard_shooting_overall",
        "fact_team_estimated_metrics",
        "fact_team_game",
        "fact_team_game_hustle",
        "fact_team_game_log",
        "fact_team_general_splits_detail",
        "fact_team_historical",
        "fact_team_history_detail",
        "fact_team_hof",
        "fact_team_lineups_detail",
        "fact_team_lineups_overall",
        "fact_team_matchups",
        "fact_team_matchups_detail",
        "fact_team_matchups_shot_detail",
        "fact_team_player_dashboard",
        "fact_team_pt_reb_detail",
        "fact_team_pt_shots_detail",
        "fact_team_pt_tracking",
        "fact_team_retired",
        "fact_team_season_ranks",
        "fact_team_shooting_splits_detail",
        "fact_team_social_sites",
        "fact_team_splits",
        "fact_tracking_defense",
        "fact_win_probability",
    ],
    "derived": [
        "agg_all_time_leaders",
        "agg_clutch_stats",
        "agg_league_leaders",
        "agg_lineup_efficiency",
        "agg_on_off_splits",
        "agg_player_bio",
        "agg_player_career",
        "agg_player_rolling",
        "agg_player_season",
        "agg_player_season_per36",
        "agg_player_season_per48",
        "agg_shot_location_season",
        "agg_shot_zones",
        "agg_team_franchise",
        "agg_team_pace_and_efficiency",
        "agg_team_season",
    ],
    "analytics": [
        "analytics_draft_value",
        "analytics_clutch_performance",
        "analytics_head_to_head",
        "analytics_league_benchmarks",
        "analytics_player_game_complete",
        "analytics_player_impact",
        "analytics_player_matchup",
        "analytics_player_season_complete",
        "analytics_shooting_efficiency",
        "analytics_team_game_complete",
        "analytics_team_season_summary",
    ],
}

CATEGORY_ORDER = ("dimensions", "bridges", "facts", "derived", "analytics")

CATEGORY_LABELS: dict[str, str] = {
    "dimensions": "Dimensions",
    "bridges": "Bridges",
    "facts": "Facts",
    "derived": "Aggregations",
    "analytics": "Analytics Views",
}

CATEGORY_SUMMARIES: dict[str, str] = {
    "dimensions": "Players, teams, games, arenas, seasons, coaches, and officials.",
    "bridges": "Explicit bridge tables for officials, game-team sides, lineup membership, and player/team-season links.",
    "facts": "Box scores, play-by-play, shot charts, tracking, standings, matchups, and dashboards.",
    "derived": "Season totals, career stats, all-time leaders, rolling windows, and rate-normalized rollups.",
    "analytics": "Pre-joined wide tables for ML, BI, and notebook workflows.",
}

FORMAT_SPECS: tuple[tuple[str, str, str], ...] = (
    ("DuckDB", "nba.duckdb", "Fast analytical queries, joins across tables"),
    ("SQLite", "nba.sqlite", "Portable SQL access with broad tool support"),
    ("Parquet", "parquet/<table>/...", "Columnar analytics with pandas, polars, Arrow, and Spark"),
    ("CSV", "csv/<table>.csv", "Universal compatibility and spreadsheet workflows"),
)

DATASET_TITLE = "NBA Basketball Database"
PROJECT_DOCS_URL = "https://nbadb.w4w.dev"
PROJECT_REPO_URL = "https://github.com/wyattowalsh/nbadb"


@dataclass(frozen=True, slots=True)
class ExportInventory:
    duckdb_available: bool
    sqlite_available: bool
    csv_tables: int
    parquet_tables: int


def _iter_catalog_tables() -> list[str]:
    return [table for category in CATEGORY_ORDER for table in TABLE_CATEGORIES[category]]


def _total_table_count() -> int:
    return len(_iter_catalog_tables())


def _expected_inventory() -> ExportInventory:
    total_tables = _total_table_count()
    return ExportInventory(
        duckdb_available=True,
        sqlite_available=True,
        csv_tables=total_tables,
        parquet_tables=total_tables,
    )


def _resolve_export_inventory(data_dir: Path | None) -> ExportInventory:
    if data_dir is None:
        return _expected_inventory()

    if not data_dir.exists():
        logger.warning(
            "Metadata data_dir {} does not exist; falling back to catalog-only metadata.",
            data_dir,
        )
        return _expected_inventory()

    all_tables = _iter_catalog_tables()
    csv_tables = sum(1 for table in all_tables if (data_dir / "csv" / f"{table}.csv").exists())
    parquet_tables = sum(
        1 for table in all_tables if _resolve_parquet_resource_path(table, data_dir)
    )
    return ExportInventory(
        duckdb_available=(data_dir / "nba.duckdb").exists(),
        sqlite_available=(data_dir / "nba.sqlite").exists(),
        csv_tables=csv_tables,
        parquet_tables=parquet_tables,
    )


def _available_format_specs(inventory: ExportInventory) -> list[tuple[str, str, str]]:
    available: list[tuple[str, str, str]] = []
    for label, path, description in FORMAT_SPECS:
        if label == "DuckDB" and not inventory.duckdb_available:
            continue
        if label == "SQLite" and not inventory.sqlite_available:
            continue
        if label == "Parquet" and inventory.parquet_tables == 0:
            continue
        if label == "CSV" and inventory.csv_tables == 0:
            continue
        available.append((label, path, description))
    return available


def _human_join(items: list[str]) -> str:
    if not items:
        return ""
    if len(items) == 1:
        return items[0]
    return f"{', '.join(items[:-1])}, and {items[-1]}"


def _render_subtitle(inventory: ExportInventory) -> str:
    total_tables = _total_table_count()
    format_names = [label for label, _, _ in _available_format_specs(inventory)]
    return (
        f"Comprehensive NBA database: {total_tables}-table star schema (1946-present) "
        f"with {_human_join(format_names)} exports"
    )


def _render_schema_overview() -> str:
    rows = [
        "## Schema Overview",
        "",
        "| Layer | Count | Description |",
        "|-------|------:|-------------|",
    ]
    for category in CATEGORY_ORDER:
        rows.append(
            f"| {CATEGORY_LABELS[category]} | {len(TABLE_CATEGORIES[category])} | {CATEGORY_SUMMARIES[category]} |"
        )
    return "\n".join(rows)


def _render_source_and_provenance() -> str:
    return "\n".join(
        [
            "## Source and Provenance",
            "",
            "- **Primary source**: `stats.nba.com` endpoints accessed via [`nba_api`](https://github.com/swar/nba_api).",
            "- **Dataset identifier**: `wyattowalsh/basketball` on Kaggle.",
            f"- **Documentation**: {PROJECT_DOCS_URL}",
            f"- **Repository**: {PROJECT_REPO_URL}",
            "- **Temporal coverage**: 1946-47 through the current NBA season, with daily in-season refreshes and monthly full rebuilds.",
        ]
    )


def _render_data_coverage() -> str:
    return "\n".join(
        [
            "## Data Coverage",
            "",
            "- **Box Scores**: traditional, advanced, misc, hustle, four factors, tracking, scoring, usage, and starter/bench splits.",
            "- **Play-by-Play**: every event with clock, score, event codes, and involved players.",
            "- **Shot Charts**: every FGA with court coordinates, zone, distance, and make/miss outcome.",
            "- **Player Tracking**: speed, distance, touches, passes, contested shots, and rebounding breakdowns.",
            "- **Rotations**: check-in/check-out times with points and usage per stint.",
            "- **Win Probability**: real-time home and visitor win probability at each play.",
            "- **Lineups**: five-man unit performance from league-wide and team-specific lineup endpoints.",
            "- **Synergy Play Types**: PnR, isolation, transition, post-up, spot-up, cut, and off-screen efficiency.",
            "- **Draft**: picks plus combine measurements including height, weight, wingspan, vertical leap, sprint, and bench press.",
            "- **Awards and Standings**: MVP, All-Star, All-NBA, DPOY, ROY, conference/division rankings, streaks, and playoff context.",
        ]
    )


def _render_available_formats(inventory: ExportInventory) -> str:
    rows = [
        "## Available Formats",
        "",
        "| Format | Path | Best For |",
        "|--------|------|----------|",
    ]
    for label, path, description in _available_format_specs(inventory):
        rows.append(f"| {label} | `{path}` | {description} |")
    rows.extend(
        [
            "",
            "DuckDB and Parquet exports use zstd compression for efficient storage.",
        ]
    )
    return "\n".join(rows)


def _render_export_inventory(inventory: ExportInventory) -> str:
    total_tables = _total_table_count()
    databases: list[str] = []
    if inventory.duckdb_available:
        databases.append("DuckDB")
    if inventory.sqlite_available:
        databases.append("SQLite")
    database_summary = _human_join(databases) or "none detected"
    return "\n".join(
        [
            "## Export Inventory",
            "",
            f"- **Cataloged tables**: {total_tables}",
            f"- **CSV exports available**: {inventory.csv_tables}/{total_tables}",
            f"- **Parquet exports available**: {inventory.parquet_tables}/{total_tables}",
            f"- **Database bundles available**: {database_summary}",
        ]
    )


def _render_getting_started() -> str:
    return "\n".join(
        [
            "## Getting Started",
            "",
            "```python",
            "import duckdb",
            'con = duckdb.connect("nba.duckdb", read_only=True)',
            "",
            "# Player season averages",
            "con.sql(\"SELECT * FROM agg_player_season WHERE season_year = '2024-25' ORDER BY avg_pts DESC LIMIT 10\")",
            "",
            "# Shot chart for a player",
            'con.sql("SELECT loc_x, loc_y, shot_made_flag FROM fact_shot_chart WHERE player_id = 201939")',
            "",
            "# Team standings",
            "con.sql(\"SELECT * FROM fact_standings WHERE season_year = '2024-25' ORDER BY conference_rank\")",
            "```",
        ]
    )


def _render_key_relationships() -> str:
    return "\n".join(
        [
            "## Key Relationships",
            "",
            "The warehouse follows a star schema: dimensions provide lookup context, while facts record measurable events and aggregates.",
            "",
            "- **player_id** links facts to `dim_player` (use `is_current = TRUE` for the latest SCD2 attributes).",
            "- **team_id** links facts and bridges to `dim_team`.",
            "- **game_id** links event and box-score facts to `dim_game`, which provides season, date, and home/visitor context.",
            "- **season_year** is the common grain for seasonal facts and aggregate rollups.",
            "",
            "Analytics views are pre-joined wide tables for common notebook and BI workflows.",
        ]
    )


def _render_table_catalog() -> str:
    sections = ["## Table Catalog", ""]
    for category in CATEGORY_ORDER:
        sections.extend(
            [
                f"### {CATEGORY_LABELS[category]} ({len(TABLE_CATEGORIES[category])})",
                "",
                "| Table | Description |",
                "|-------|-------------|",
            ]
        )
        sections.extend(
            f"| {table} | {TABLE_DESCRIPTIONS[table]} |" for table in TABLE_CATEGORIES[category]
        )
        sections.append("")
    return "\n".join(sections).rstrip()


def _render_companion_notebooks() -> str:
    return "\n".join(
        [
            "## Companion Notebooks",
            "",
            "10 Kaggle notebooks demonstrate MVP prediction, game-outcome modeling, player clustering, shot-chart visualization, and lineup analysis.",
        ]
    )


def _render_update_schedule() -> str:
    return "\n".join(
        [
            "## Update Schedule",
            "",
            "Updated daily during the NBA season via the automated pipeline. Full rebuilds run on the first week of each month.",
        ]
    )


def _render_dataset_description(inventory: ExportInventory) -> str:
    sections = [
        "# NBA Basketball Database",
        "",
        "The most comprehensive open NBA database available — 137 stats.nba.com endpoint classes extracted via [nba_api](https://github.com/swar/nba_api), normalized into a star schema covering every season from 1946-47 to present.",
        "",
        _render_source_and_provenance(),
        "",
        _render_schema_overview(),
        "",
        _render_data_coverage(),
        "",
        _render_available_formats(inventory),
        "",
        _render_export_inventory(inventory),
        "",
        _render_getting_started(),
        "",
        _render_key_relationships(),
        "",
        _render_table_catalog(),
        "",
        _render_companion_notebooks(),
        "",
        _render_update_schedule(),
    ]
    return "\n".join(sections)


_DTYPE_MAP: dict[str, str] = {
    "Int8": "integer",
    "Int16": "integer",
    "Int32": "integer",
    "Int64": "integer",
    "UInt8": "integer",
    "UInt16": "integer",
    "UInt32": "integer",
    "UInt64": "integer",
    "Float32": "number",
    "Float64": "number",
    "String": "string",
    "Utf8": "string",
    "Boolean": "boolean",
    "Date": "date",
    "Datetime": "datetime",
}


def generate_metadata(output_path: Path, data_dir: Path | None = None) -> None:
    """Generate dataset-metadata.json from the table catalog and optional export data."""
    settings = get_settings()
    inventory = _resolve_export_inventory(data_dir)
    metadata = {
        "id": settings.kaggle_dataset,
        "id_no": None,
        "title": DATASET_TITLE,
        "subtitle": _render_subtitle(inventory),
        "description": _render_dataset_description(inventory),
        "isPrivate": False,
        "licenses": [{"name": "CC-BY-SA-4.0"}],
        "keywords": [
            "basketball",
            "nba",
            "sports",
            "statistics",
            "analytics",
            "sports-analytics",
            "star-schema",
            "duckdb",
            "sqlite",
            "parquet",
            "play-by-play",
            "shot-charts",
            "player-tracking",
            "box-scores",
            "machine-learning",
            "data-science",
            "polars",
            "fantasy-basketball",
            "nba-stats",
        ],
        "collaborators": [],
        "data": [],
        "resources": _build_resources(data_dir=data_dir),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    logger.info(f"Generated metadata at {output_path}")


def _schema_to_fields(schema_cls: Any) -> list[dict]:
    """Convert a pandera schema class to Kaggle-compatible field dicts."""
    schema_obj = schema_cls.to_schema()
    fields: list[dict] = []
    for col_name, col in schema_obj.columns.items():
        dtype_str = str(col.dtype)
        kaggle_type = _DTYPE_MAP.get(dtype_str, "string")
        md = getattr(col, "metadata", None) or {}
        field: dict = {
            "name": col_name,
            "type": kaggle_type,
        }
        desc = md.get("description", "")
        if desc:
            field["description"] = desc
        fields.append(field)
    return fields


# Pass-through transforms whose output columns match their single staging input.
_STAGING_FALLBACKS: dict[str, str] = {
    "dim_all_players": "stg_common_all_players",
    "fact_box_score_four_factors_team": "stg_box_score_four_factors_team",
    "fact_box_score_hustle_player": "stg_box_score_hustle_player",
    "fact_box_score_team": "stg_box_score_traditional_team",
    "fact_league_dash_player_stats": "stg_league_dash_player_stats",
    "fact_league_dash_team_stats": "stg_league_dash_team_stats",
    "fact_shot_chart_league": "stg_shot_chart_league_wide",
}


def _extract_column_schema(table_name: str) -> list[dict] | None:
    """Extract column definitions from pandera schema, if available.

    Tries the star (output) schema first. Falls back to the staging
    (input) schema for known pass-through ``SELECT *`` transforms.
    """
    from nbadb.schemas.registry import get_input_schema, get_output_schema

    schema_cls = get_output_schema(table_name)
    if schema_cls is not None:
        return _schema_to_fields(schema_cls)

    stg_name = _STAGING_FALLBACKS.get(table_name)
    if stg_name is not None:
        schema_cls = get_input_schema(stg_name)
        if schema_cls is not None:
            return _schema_to_fields(schema_cls)

    return None


def _table_display_name(table: str) -> str:
    """Convert a snake_case table name to a human-readable display name."""
    # Strip prefix
    for prefix in ("dim_", "fact_", "agg_", "bridge_", "analytics_"):
        if table.startswith(prefix):
            table = table[len(prefix) :]
            break
    return table.replace("_", " ").title()


def _resolve_parquet_resource_path(table: str, data_dir: Path | None = None) -> str | None:
    from nbadb.load.parquet_loader import PARTITIONED_TABLES

    if data_dir is not None:
        table_dir = data_dir / "parquet" / table
        table_file = table_dir / f"{table}.parquet"
        if table_file.exists():
            return f"parquet/{table}/{table}.parquet"
        if table_dir.exists():
            return f"parquet/{table}"
        return None

    if table in PARTITIONED_TABLES:
        return f"parquet/{table}"
    return f"parquet/{table}/{table}.parquet"


def _build_resources(data_dir: Path | None = None) -> list[dict]:
    """Build resource entries for exported tables, filtering by data_dir when provided."""
    resources: list[dict] = []
    total_tables = _total_table_count()

    # Database files
    if data_dir is None or (data_dir / "nba.duckdb").exists():
        resources.append(
            {
                "path": "nba.duckdb",
                "name": "DuckDB Database",
                "description": f"DuckDB database with all {total_tables} cataloged tables. Best for fast analytical queries and cross-table joins.",
            }
        )
    if data_dir is None or (data_dir / "nba.sqlite").exists():
        resources.append(
            {
                "path": "nba.sqlite",
                "name": "SQLite Database",
                "description": f"SQLite database with all {total_tables} cataloged tables. Portable SQL access with broad tool support.",
            }
        )

    # CSV and Parquet tables with optional column schemas
    for table in _iter_catalog_tables():
        description = TABLE_DESCRIPTIONS.get(table, table)
        display_name = _table_display_name(table)
        schema_fields = _extract_column_schema(table)

        csv_path = f"csv/{table}.csv"
        if data_dir is None or (data_dir / csv_path).exists():
            csv_resource: dict = {
                "path": csv_path,
                "name": display_name,
                "description": description,
            }
            if schema_fields:
                csv_resource["schema"] = {"fields": schema_fields}
            resources.append(csv_resource)

        parquet_path = _resolve_parquet_resource_path(table, data_dir)
        if parquet_path is not None:
            parquet_resource: dict = {
                "path": parquet_path,
                "name": f"{display_name} (Parquet)",
                "description": description,
            }
            if schema_fields:
                parquet_resource["schema"] = {"fields": schema_fields}
            resources.append(parquet_resource)

    return resources
