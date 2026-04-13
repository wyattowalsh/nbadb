import { describe, expect, it } from "vitest";
import {
  PARQUET_DEFAULT_QUERY,
  PARQUET_EXAMPLES,
  PARQUET_FALLBACK_DEFAULT_QUERY,
} from "@/lib/playground-examples";

describe("playground parquet examples", () => {
  it("uses current aggregate and dimension columns in the scorer query", () => {
    expect(PARQUET_DEFAULT_QUERY).toContain("p.full_name");
    expect(PARQUET_DEFAULT_QUERY).toContain("s.season_year");
    expect(PARQUET_DEFAULT_QUERY).toContain("s.avg_pts");
    expect(PARQUET_DEFAULT_QUERY).not.toContain("p.player_name");
    expect(PARQUET_DEFAULT_QUERY).not.toContain("s.ppg");
  });

  it("keeps the fallback scorer query aligned with the live parquet query", () => {
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain("full_name");
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain("season_year");
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain("avg_pts");
  });

  it("uses the current standings contract in the conference example", () => {
    const standings = PARQUET_EXAMPLES.find(
      (example) => example.label === "Conference standings",
    );

    expect(standings?.sql).toContain("s.season_year");
    expect(standings?.sql).toContain("s.season_type = 'Regular Season'");
    expect(standings?.sql).toContain("s.conf_rank");
  });

  it("keeps fallback examples aligned to the current season contract", () => {
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain("'2025-26'");
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain(
      "s.season_type = 'Regular Season'",
    );
    expect(PARQUET_FALLBACK_DEFAULT_QUERY).toContain("p.is_current = true");
  });
});
