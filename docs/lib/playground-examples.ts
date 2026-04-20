import { PARQUET_CATALOG, SAMPLE_DATA_AVAILABLE } from "@/lib/parquet-catalog";

// Re-export so the MDX can import from a single module
export { SAMPLE_DATA_AVAILABLE };

export const BUILT_IN_EXAMPLES = [
  {
    label: "Leaderboard",
    description:
      "Practice a simple ranking query over NBA-flavored sample rows.",
    sql: `WITH box_score AS (
  SELECT *
  FROM (
    VALUES
      ('Nikola Jokic', 'DEN', 29, 13, 11),
      ('Shai Gilgeous-Alexander', 'OKC', 32, 5, 6),
      ('Jayson Tatum', 'BOS', 27, 8, 5),
      ('Luka Doncic', 'DAL', 34, 9, 10),
      ('Giannis Antetokounmpo', 'MIL', 30, 11, 6)
  ) AS t(player, team, pts, reb, ast)
)
SELECT
  player,
  team,
  pts,
  reb,
  ast,
  pts + reb + ast AS box_score_total
FROM box_score
ORDER BY pts DESC;`,
  },
  {
    label: "Shot zones",
    description:
      "Practice grouped efficiency reads before moving into real shot-chart data.",
    sql: `WITH shot_zones AS (
  SELECT *
  FROM (
    VALUES
      ('Restricted Area', 42, 31),
      ('Paint', 28, 15),
      ('Mid-Range', 18, 8),
      ('Above the Break 3', 36, 14),
      ('Corner 3', 12, 5)
  ) AS t(zone, attempts, makes)
)
SELECT
  zone,
  attempts,
  makes,
  ROUND(100.0 * makes / attempts, 1) AS fg_pct
FROM shot_zones
ORDER BY attempts DESC;`,
  },
  {
    label: "Standings",
    description:
      "Practice ranking and window functions with a compact conference snapshot.",
    sql: `WITH standings AS (
  SELECT *
  FROM (
    VALUES
      ('East', 'Boston Celtics', 61, 21),
      ('East', 'Milwaukee Bucks', 49, 33),
      ('East', 'New York Knicks', 50, 32),
      ('West', 'Oklahoma City Thunder', 57, 25),
      ('West', 'Denver Nuggets', 57, 25),
      ('West', 'Minnesota Timberwolves', 56, 26)
  ) AS t(conference, team, wins, losses)
)
SELECT
  conference,
  team,
  wins,
  losses,
  ROUND(wins * 1.0 / NULLIF(wins + losses, 0), 3) AS win_pct,
  DENSE_RANK() OVER (PARTITION BY conference ORDER BY wins DESC, losses ASC) AS conference_seed
FROM standings
ORDER BY conference, conference_seed, team;`,
  },
];

export const BUILT_IN_DEFAULT_QUERY = BUILT_IN_EXAMPLES[0].sql;

export const PARQUET_TABLES = PARQUET_CATALOG.map(({ tableName, url }) => ({
  tableName,
  url,
}));

export const CURRENT_SEASON = "2025-26";

export const PARQUET_DEFAULT_QUERY = `SELECT
  p.full_name,
  s.team_abbreviation AS team,
  s.season_year,
  s.avg_pts,
  s.avg_reb,
  s.avg_ast
FROM agg_player_season s
JOIN dim_player p ON s.player_id = p.player_id
WHERE s.season_year = '${CURRENT_SEASON}'
  AND s.season_type = 'Regular Season'
  AND p.is_current = true
ORDER BY s.avg_pts DESC
LIMIT 10;`;

export const PARQUET_EXAMPLES = [
  {
    label: "Top scorers",
    description:
      "Join player season stats with dimension tables to find top scorers.",
    sql: PARQUET_DEFAULT_QUERY,
  },
  {
    label: "Shot zone efficiency",
    description:
      "Calculate field-goal percentage by shot zone from the shot chart.",
    sql: `SELECT
  shot_zone_basic,
  COUNT(*) AS attempts,
  SUM(shot_made_flag) AS makes,
  ROUND(100.0 * SUM(shot_made_flag) / COUNT(*), 1) AS fg_pct
FROM fact_shot_chart
GROUP BY shot_zone_basic
ORDER BY attempts DESC;`,
  },
  {
    label: "Conference standings",
    description: "Rank teams within each conference for the latest season.",
    sql: `SELECT
  s.conference,
  t.full_name,
  s.wins,
  s.losses,
  s.win_pct,
  s.conf_rank
FROM fact_standings s
JOIN dim_team t ON s.team_id = t.team_id
WHERE s.season_year = '${CURRENT_SEASON}'
  AND s.season_type = 'Regular Season'
ORDER BY s.conference, s.conf_rank;`,
  },
];

export const PARQUET_FALLBACK_DEFAULT_QUERY = `WITH dim_player AS (
  SELECT *
  FROM (
    VALUES
      (203999, 'Nikola Jokic', true),
      (1628983, 'Shai Gilgeous-Alexander', true),
      (1628369, 'Jayson Tatum', true)
  ) AS t(player_id, full_name, is_current)
),
dim_team AS (
  SELECT *
  FROM (
    VALUES
      (1610612743, 'DEN', 'Denver Nuggets', 'West'),
      (1610612760, 'OKC', 'Oklahoma City Thunder', 'West'),
      (1610612738, 'BOS', 'Boston Celtics', 'East')
  ) AS t(team_id, abbreviation, full_name, conference)
),
agg_player_season AS (
  SELECT *
  FROM (
    VALUES
      (203999, 1610612743, 'DEN', '${CURRENT_SEASON}', 'Regular Season', 29.4, 12.1, 9.8),
      (1628983, 1610612760, 'OKC', '${CURRENT_SEASON}', 'Regular Season', 31.7, 5.6, 6.4),
      (1628369, 1610612738, 'BOS', '${CURRENT_SEASON}', 'Regular Season', 27.9, 8.4, 5.1)
  ) AS t(player_id, team_id, team_abbreviation, season_year, season_type, avg_pts, avg_reb, avg_ast)
)
SELECT
  p.full_name,
  s.team_abbreviation AS team,
  s.season_year,
  s.avg_pts,
  s.avg_reb,
  s.avg_ast
FROM agg_player_season s
JOIN dim_player p ON s.player_id = p.player_id
WHERE s.season_year = '${CURRENT_SEASON}'
  AND s.season_type = 'Regular Season'
  AND p.is_current = true
ORDER BY s.avg_pts DESC
LIMIT 10;`;

export const PARQUET_FALLBACK_EXAMPLES = [
  {
    label: "Top scorers (demo)",
    description:
      "Use inline demo dimensions and aggregates that mirror the warehouse join shape.",
    sql: PARQUET_FALLBACK_DEFAULT_QUERY,
  },
  {
    label: "Shot zone efficiency (demo)",
    description:
      "Practice the same aggregation against inline fact_shot_chart-style rows.",
    sql: `WITH fact_shot_chart AS (
  SELECT *
  FROM (
    VALUES
      ('Restricted Area', 1),
      ('Restricted Area', 1),
      ('Restricted Area', 0),
      ('Above the Break 3', 1),
      ('Above the Break 3', 0),
      ('Corner 3', 1)
  ) AS t(shot_zone_basic, shot_made_flag)
)
SELECT
  shot_zone_basic,
  COUNT(*) AS attempts,
  SUM(shot_made_flag) AS makes,
  ROUND(100.0 * SUM(shot_made_flag) / COUNT(*), 1) AS fg_pct
FROM fact_shot_chart
GROUP BY shot_zone_basic
ORDER BY attempts DESC;`,
  },
  {
    label: "Conference standings (demo)",
    description:
      "Keep the real join and ranking pattern while the hosted Parquet samples are offline.",
    sql: `WITH dim_team AS (
  SELECT *
  FROM (
    VALUES
      (1610612738, 'Boston Celtics', 'East'),
      (1610612749, 'Milwaukee Bucks', 'East'),
      (1610612760, 'Oklahoma City Thunder', 'West'),
      (1610612743, 'Denver Nuggets', 'West')
  ) AS t(team_id, full_name, conference)
),
fact_standings AS (
  SELECT *
  FROM (
    VALUES
      (1610612738, '${CURRENT_SEASON}', 'Regular Season', 61, 21, 0.744, 1),
      (1610612749, '${CURRENT_SEASON}', 'Regular Season', 49, 33, 0.598, 2),
      (1610612760, '${CURRENT_SEASON}', 'Regular Season', 57, 25, 0.695, 1),
      (1610612743, '${CURRENT_SEASON}', 'Regular Season', 56, 26, 0.683, 2)
  ) AS t(team_id, season_year, season_type, wins, losses, win_pct, conf_rank)
)
SELECT
  t.conference,
  t.full_name,
  s.wins,
  s.losses,
  s.win_pct,
  s.conf_rank
FROM fact_standings s
JOIN dim_team t ON s.team_id = t.team_id
WHERE s.season_year = '${CURRENT_SEASON}'
  AND s.season_type = 'Regular Season'
ORDER BY t.conference, s.conf_rank;`,
  },
];
