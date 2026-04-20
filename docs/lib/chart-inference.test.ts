import { describe, expect, it } from "vitest";
import { inferChart } from "@/lib/chart-inference";

describe("inferChart", () => {
  it("prefers a line chart for temporal series", () => {
    const inference = inferChart(
      ["game_date", "pts"],
      [
        { game_date: "2025-01-01", pts: 27 },
        { game_date: "2025-01-03", pts: 31 },
      ],
    );

    expect(inference).toMatchObject({
      type: "line",
      xColumn: "game_date",
      yColumns: ["pts"],
      label: "Line chart",
    });
  });

  it("groups multiple quantitative columns under one categorical axis", () => {
    const inference = inferChart(
      ["player", "pts", "reb"],
      [
        { player: "A", pts: 21, reb: 9 },
        { player: "B", pts: 18, reb: 11 },
      ],
    );

    expect(inference).toMatchObject({
      type: "grouped-bar",
      xColumn: "player",
      yColumns: ["pts", "reb"],
      label: "Grouped bars",
    });
  });

  it("returns none when there is not enough data to infer a chart", () => {
    expect(inferChart(["pts"], [{ pts: 10 }, { pts: 14 }]).type).toBe("none");
    expect(inferChart(["player", "pts"], [{ player: "A", pts: 10 }]).type).toBe(
      "none",
    );
  });

  it("keeps numeric identifier columns categorical instead of using scatter", () => {
    const inference = inferChart(
      ["team_id", "pts"],
      [
        { team_id: 1610612738, pts: 18 },
        { team_id: 1610612743, pts: 22 },
      ],
    );

    expect(inference).toMatchObject({
      type: "bar",
      xColumn: "team_id",
      yColumns: ["pts"],
      label: "Bar chart",
    });
  });
});
