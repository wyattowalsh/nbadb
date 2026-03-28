"use client";

import { ChartArea } from "@/components/admin/chart-area";
import { ChartBar } from "@/components/admin/chart-bar";
import { ChartDonut } from "@/components/admin/chart-donut";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import type {
  PipelineDailyRollup,
  PipelineEndpointTelemetry,
  PipelineRunStatus,
} from "@/lib/admin/types";

const statusColors: Record<PipelineRunStatus, string> = {
  done: "var(--primary)",
  failed: "var(--destructive)",
  running: "var(--accent)",
  abandoned: "var(--muted)",
};

type PipelineChartsProps = {
  daily: PipelineDailyRollup[];
  counts: Record<PipelineRunStatus, number>;
  slowEndpoints: PipelineEndpointTelemetry[];
};

export function PipelineCharts({
  daily,
  counts,
  slowEndpoints,
}: PipelineChartsProps) {
  const areaData = daily.map((bucket) => ({
    bucket: bucket.label.slice(5),
    rows: bucket.rowsExtracted,
  }));

  const latencyData = slowEndpoints.slice(0, 6).map((item) => ({
    endpoint: item.endpoint.replace(/([A-Z])/g, " $1").trim().slice(0, 16),
    latency: item.p95DurationMs,
  }));

  const donutData = (Object.entries(counts) as [PipelineRunStatus, number][])
    .filter(([, v]) => v > 0)
    .map(([name, value]) => ({
      name,
      value,
      color: statusColors[name],
    }));

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.4fr)_minmax(0,1fr)] nba-delay-3">
      <Card className="xl:col-span-2">
        <CardHeader>
          <CardTitle>Extraction Volume</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartArea
            data={areaData}
            xKey="bucket"
            yKey="rows"
            color="var(--primary)"
            height={200}
          />
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <CardTitle>p95 Endpoint Latency</CardTitle>
        </CardHeader>
        <CardContent>
          <ChartBar
            data={latencyData}
            xKey="endpoint"
            yKey="latency"
            color="var(--chart-2)"
            height={220}
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
