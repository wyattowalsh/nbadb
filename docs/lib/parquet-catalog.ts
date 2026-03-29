export type ParquetTableEntry = {
  tableName: string;
  url: string;
  description: string;
  rowEstimate: string;
  sizeEstimate: string;
};

/**
 * Whether sample Parquet files are deployed and available for loading.
 * Set to `true` once the sample data pipeline publishes files to /samples/.
 */
export const SAMPLE_DATA_AVAILABLE = false;

export const PARQUET_CATALOG: ParquetTableEntry[] = [
  {
    tableName: "dim_player",
    url: "/samples/dim_player_sample.parquet",
    description: "All NBA players with IDs, names, and active status",
    rowEstimate: "~50",
    sizeEstimate: "~2 KB",
  },
  {
    tableName: "dim_team",
    url: "/samples/dim_team_sample.parquet",
    description: "30 NBA teams with abbreviations and conference",
    rowEstimate: "~30",
    sizeEstimate: "~2 KB",
  },
  {
    tableName: "agg_player_season",
    url: "/samples/agg_player_season_sample.parquet",
    description: "Per-player season aggregates (last 3 seasons)",
    rowEstimate: "~150",
    sizeEstimate: "~8 KB",
  },
  {
    tableName: "fact_shot_chart",
    url: "/samples/fact_shot_chart_sample.parquet",
    description: "Shot chart detail sample",
    rowEstimate: "~2,000",
    sizeEstimate: "~18 KB",
  },
  {
    tableName: "fact_standings",
    url: "/samples/fact_standings_sample.parquet",
    description: "Conference standings (last 5 seasons)",
    rowEstimate: "~150",
    sizeEstimate: "~4 KB",
  },
];
