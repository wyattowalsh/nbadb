import { describe, expect, it } from "vitest";
import { expandSearchQuery } from "@/lib/search-query";

describe("expandSearchQuery", () => {
  it("adds each known alias once", () => {
    const expanded = expandSearchQuery("ppg ppg rpg");

    expect(expanded).toContain("points per game");
    expect(expanded).toContain("scoring average");
    expect(expanded).toContain("rebounds per game");
    expect(expanded.match(/points per game/g)).toHaveLength(1);
  });

  it("leaves unrelated queries unchanged", () => {
    expect(expandSearchQuery("schema lineage")).toBe("schema lineage");
  });

  it("matches aliases case-insensitively without duplicating phrases", () => {
    const expanded = expandSearchQuery("PPG apg");

    expect(expanded).toContain("points per game");
    expect(expanded).toContain("scoring average");
    expect(expanded).toContain("assists per game");
    expect(expanded.match(/assists per game/g)).toHaveLength(1);
  });
});
