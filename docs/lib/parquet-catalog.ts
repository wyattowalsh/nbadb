// TODO: These Parquet URLs reference a GitHub release (`docs-sample-data`)
// that does not exist yet. Create the release and upload sample Parquet files
// before enabling the "Query real NBA data" section in playground.mdx.

export type ParquetTableEntry = {
  tableName: string;
  url: string;
  description: string;
  rowEstimate: string;
  sizeEstimate: string;
};

export const PARQUET_CATALOG: ParquetTableEntry[] = [
  {
    tableName: "dim_player",
    url: "https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/dim_player_sample.parquet",
    description: "All NBA players with IDs, names, and active status",
    rowEstimate: "~5,000",
    sizeEstimate: "~200 KB",
  },
  {
    tableName: "dim_team",
    url: "https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/dim_team_sample.parquet",
    description: "30 NBA teams with abbreviations and conference",
    rowEstimate: "~30",
    sizeEstimate: "~5 KB",
  },
  {
    tableName: "agg_player_season",
    url: "https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/agg_player_season_sample.parquet",
    description: "Per-player season aggregates (last 3 seasons)",
    rowEstimate: "~1,500",
    sizeEstimate: "~1 MB",
  },
  {
    tableName: "fact_shot_chart",
    url: "https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/fact_shot_chart_sample.parquet",
    description: "Shot chart detail for recent season",
    rowEstimate: "~200,000",
    sizeEstimate: "~3 MB",
  },
  {
    tableName: "fact_standings",
    url: "https://github.com/wyattowalsh/nbadb/releases/download/docs-sample-data/fact_standings_sample.parquet",
    description: "Conference standings (last 5 seasons)",
    rowEstimate: "~300",
    sizeEstimate: "~100 KB",
  },
];
