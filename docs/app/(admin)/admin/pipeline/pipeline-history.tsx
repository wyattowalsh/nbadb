"use client";

import { FreshnessHeatmap } from "@/components/admin/freshness-heatmap";
import { KpiCard } from "@/components/admin/kpi-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type PipelineHistoryProps = {
  freshness: Array<{
    endpoint: string;
    layer: string;
    lastSuccess: string | null;
    hoursSinceSuccess: number | null;
  }>;
  healthScores: Array<{
    endpoint: string;
    score: number;
    status: "healthy" | "degraded" | "unhealthy";
  }>;
};

function statusDotColor(status: "healthy" | "degraded" | "unhealthy"): string {
  if (status === "healthy") return "bg-emerald-500";
  if (status === "degraded") return "bg-amber-500";
  return "bg-red-500";
}

export function PipelineHistory({
  freshness,
  healthScores,
}: PipelineHistoryProps) {
  const healthyCount = healthScores.filter(
    (h) => h.status === "healthy",
  ).length;
  const degradedCount = healthScores.filter(
    (h) => h.status === "degraded",
  ).length;
  const staleCount = freshness.filter(
    (f) => f.hoursSinceSuccess !== null && f.hoursSinceSuccess > 168,
  ).length;
  const neverCount = freshness.filter(
    (f) => f.hoursSinceSuccess === null,
  ).length;

  const heatmapData = freshness.map((f) => ({
    label: f.endpoint,
    layer: f.layer,
    hoursSinceSuccess: f.hoursSinceSuccess,
  }));

  const sortedScores = [...healthScores].sort((a, b) => b.score - a.score);

  return (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        <KpiCard label="Healthy" value={healthyCount} />
        <KpiCard label="Degraded" value={degradedCount} />
        <KpiCard label="Stale (>7d)" value={staleCount} />
        <KpiCard label="Never Succeeded" value={neverCount} />
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Freshness Heatmap</CardTitle>
        </CardHeader>
        <CardContent>
          {heatmapData.length > 0 ? (
            <FreshnessHeatmap data={heatmapData} />
          ) : (
            <p className="text-sm text-muted-foreground">
              No freshness data available yet.
            </p>
          )}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Health Scores</CardTitle>
        </CardHeader>
        <CardContent>
          {sortedScores.length > 0 ? (
            <div className="space-y-2">
              {sortedScores.map((item) => (
                <div
                  key={item.endpoint}
                  className="flex items-center gap-3 rounded-xl border border-border/40 px-3 py-2 transition-colors hover:bg-muted/20"
                >
                  <span
                    className={cn(
                      "size-2 shrink-0 rounded-full",
                      statusDotColor(item.status),
                    )}
                  />
                  <span className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
                    {item.endpoint}
                  </span>
                  <div className="flex w-32 items-center gap-2">
                    <div className="h-2 flex-1 overflow-hidden rounded-full bg-muted/40">
                      <div
                        className={cn(
                          "h-full rounded-full transition-all",
                          item.score >= 80
                            ? "bg-emerald-500"
                            : item.score >= 50
                              ? "bg-amber-500"
                              : "bg-red-500",
                        )}
                        style={{
                          width: `${Math.min(100, Math.max(0, item.score))}%`,
                        }}
                      />
                    </div>
                    <span className="w-8 text-right font-mono text-xs tabular-nums text-muted-foreground">
                      {item.score}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              No health score data available yet.
            </p>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
