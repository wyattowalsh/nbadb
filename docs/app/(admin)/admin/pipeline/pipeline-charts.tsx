"use client";

import { ChartArea } from "@/components/admin/chart-area";
import { ChartDonut } from "@/components/admin/chart-donut";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type { PipelineRun, PipelineRunStatus } from "@/lib/admin/types";

const statusColors: Record<PipelineRunStatus, string> = {
  done: "var(--primary)",
  failed: "var(--destructive)",
  running: "var(--accent)",
  abandoned: "var(--muted)",
};

type PipelineChartsProps = {
  runs: PipelineRun[];
  counts: Record<PipelineRunStatus, number>;
};

export function PipelineCharts({ runs, counts }: PipelineChartsProps) {
  const areaData = runs.map((r, i) => ({
    run: `#${i + 1}`,
    rows: r.rowsExtracted,
  }));

  const donutData = (Object.entries(counts) as [PipelineRunStatus, number][])
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({
      name,
      value,
      color: statusColors[name],
    }));

  return (
    <div className="grid gap-4 lg:grid-cols-[minmax(0,1.5fr)_14rem] nba-delay-3">
      <Card>
        <CardHeader>
          <CardTitle>Extraction Volume</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartArea
            data={areaData}
            xKey="run"
            yKey="rows"
            color="var(--primary)"
            height={200}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>Status Breakdown</CardTitle>
        </CardHeader>
        <CardContent className="flex items-center justify-center">
          <ChartDonut data={donutData} size={160} />
        </CardContent>
      </Card>
    </div>
  );
}
