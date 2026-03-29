import type { Metadata } from "next";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";
import { BarList } from "@/components/admin/bar-list";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/admin/kpi-card";
import { TrackerBar } from "@/components/admin/tracker-bar";
import { PipelineTabs } from "./pipeline-tabs";
import { formatLatency } from "@/lib/utils";

export const metadata: Metadata = { title: "Pipeline" };
export const dynamic = "force-dynamic";

function formatDateTime(value: string | null): string {
  if (!value) return "Not available";

  try {
    return new Intl.DateTimeFormat("en-US", {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }).format(new Date(value));
  } catch {
    return value;
  }
}

export default async function PipelinePage() {
  const summary = await getPipelineSummary();
  const status = overallPipelineStatus(summary);
  const hasTelemetry =
    summary.daily.length > 0 ||
    summary.slowEndpoints.length > 0 ||
    summary.failureHotspots.length > 0;
  const errorRate = summary.totals.runs
    ? ((summary.totals.errorCount / summary.totals.runs) * 100).toFixed(1)
    : "0.0";
  const lastBucket = summary.daily.at(-1) ?? null;

  const statusLabel: Record<string, string> = {
    done: "Healthy",
    failed: "Errors detected",
    running: "Running now",
    abandoned: "No data",
  };

  return (
    <div className="space-y-6 nba-reveal">
      <Card className="overflow-hidden border-primary/15 bg-[linear-gradient(135deg,color-mix(in_oklch,var(--primary)_10%,transparent),transparent_65%),linear-gradient(180deg,color-mix(in_oklch,var(--card)_88%,transparent),var(--card))]">
        <CardContent className="grid gap-6 px-6 py-6 lg:grid-cols-[minmax(0,1.2fr)_minmax(18rem,0.8fr)] lg:px-8">
          <div>
            <p className="nba-kicker">Pipeline Telemetry</p>
            <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
              Control the pipeline, not just its summary
            </h1>
            <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
              The admin panel now surfaces extraction throughput, latency
              pressure, and current failure hotspots from the DuckDB pipeline
              tables behind the password-protected control plane.
            </p>
          </div>

          <div className="grid gap-3 rounded-3xl border border-border/70 bg-background/70 p-4 backdrop-blur-sm sm:grid-cols-2">
            <div>
              <p className="nba-kicker">Status</p>
              <div className="mt-2 flex items-center gap-2">
                <Badge variant="outline">{statusLabel[status]}</Badge>
                <span className="text-xs text-muted-foreground">
                  {summary.windowDays}d telemetry window
                </span>
              </div>
            </div>
            <div>
              <p className="nba-kicker">Last Export</p>
              <p className="mt-2 text-sm font-medium text-foreground">
                {formatDateTime(summary.generatedAt)}
              </p>
            </div>
            <div>
              <p className="nba-kicker">Last Run</p>
              <p className="mt-2 text-sm font-medium text-foreground">
                {formatDateTime(summary.lastRun)}
              </p>
            </div>
            <div>
              <p className="nba-kicker">Latest Bucket</p>
              <p className="mt-2 text-sm font-medium text-foreground">
                {lastBucket
                  ? `${lastBucket.rowsExtracted.toLocaleString()} rows, ${lastBucket.errorCount} errors`
                  : "No metric data yet"}
              </p>
            </div>
          </div>
        </CardContent>
      </Card>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-6 nba-delay-1">
        <KpiCard label="Failed now" value={summary.counts.failed} />
        <KpiCard label="Running now" value={summary.counts.running} />
        <KpiCard label="Abandoned" value={summary.counts.abandoned} />
        <KpiCard
          label={`Rows (${summary.windowDays}d)`}
          value={summary.totals.rowsExtracted.toLocaleString()}
        />
        <KpiCard
          label="Avg latency"
          value={formatLatency(summary.totals.avgDurationMs)}
        />
        <KpiCard
          label="p95 latency"
          value={formatLatency(summary.totals.p95DurationMs)}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.35fr)_minmax(18rem,0.8fr)] nba-delay-2">
        <Card>
          <CardHeader>
            <CardTitle>Current Extraction State</CardTitle>
            <Badge variant="outline">{summary.totals.runs} metric rows</Badge>
          </CardHeader>
          <CardContent>
            {summary.runs.length > 0 ? (
              <div className="space-y-4">
                <TrackerBar
                  data={summary.runs.map((run) => ({
                    status: run.status,
                    label: `${run.timestamp} — ${run.tablesProcessed} endpoints, ${run.rowsExtracted.toLocaleString()} rows`,
                  }))}
                />
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                    <p className="nba-kicker">Endpoint states</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">
                      {summary.counts.done +
                        summary.counts.failed +
                        summary.counts.running +
                        summary.counts.abandoned}
                    </p>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                    <p className="nba-kicker">Error rate</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">
                      {errorRate}%
                    </p>
                  </div>
                  <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                    <p className="nba-kicker">Total tables</p>
                    <p className="mt-2 text-2xl font-semibold text-foreground">
                      {summary.totalTables}
                    </p>
                  </div>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No rollup data available yet.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Failure Hotspots</CardTitle>
            <Badge variant="outline">{summary.failureHotspots.length}</Badge>
          </CardHeader>
          <CardContent>
            {summary.failureHotspots.length > 0 ? (
              <div className="space-y-4">
                <BarList
                  data={summary.failureHotspots.map((item) => ({
                    name: item.endpoint,
                    value: item.count,
                  }))}
                  color="var(--destructive)"
                />
                <div className="space-y-2">
                  {summary.failureHotspots.slice(0, 3).map((item) => (
                    <div
                      key={`${item.endpoint}-${item.status}`}
                      className="rounded-2xl border border-border/60 bg-muted/20 p-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <p className="text-sm font-semibold text-foreground">
                          {item.endpoint}
                        </p>
                        <Badge variant="outline">{item.status}</Badge>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-muted-foreground">
                        {item.sampleError ?? "No error message captured"}
                      </p>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                No failed or abandoned extractions are currently active.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      {hasTelemetry ? (
        <>
          <PipelineTabs
            chartsProps={{
              daily: summary.daily,
              counts: summary.counts,
              slowEndpoints: summary.slowEndpoints,
            }}
          />

          <div className="grid gap-4 lg:grid-cols-2 nba-delay-3">
            <Card>
              <CardHeader>
                <CardTitle>Slowest Endpoints</CardTitle>
                <Badge variant="outline">
                  Top {summary.slowEndpoints.length}
                </Badge>
              </CardHeader>
              <CardContent>
                {summary.slowEndpoints.length > 0 ? (
                  <BarList
                    data={summary.slowEndpoints.map((item) => ({
                      name: item.endpoint,
                      value: item.p95DurationMs,
                    }))}
                    color="var(--chart-2)"
                  />
                ) : (
                  <p className="text-sm text-muted-foreground">
                    Endpoint latency telemetry will appear after metrics are
                    recorded.
                  </p>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader>
                <CardTitle>Telemetry Window</CardTitle>
                <Badge variant="outline">{summary.windowDays} days</Badge>
              </CardHeader>
              <CardContent className="grid gap-3 sm:grid-cols-2">
                <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                  <p className="nba-kicker">Metric rows</p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">
                    {summary.totals.runs}
                  </p>
                </div>
                <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                  <p className="nba-kicker">Rows extracted</p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">
                    {summary.totals.rowsExtracted.toLocaleString()}
                  </p>
                </div>
                <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                  <p className="nba-kicker">Observed errors</p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">
                    {summary.totals.errorCount}
                  </p>
                </div>
                <div className="rounded-2xl border border-border/60 bg-muted/20 p-3">
                  <p className="nba-kicker">Staging metadata</p>
                  <p className="mt-2 text-2xl font-semibold text-foreground">
                    {summary.stagingCoverage}%
                  </p>
                </div>
              </CardContent>
            </Card>
          </div>
        </>
      ) : (
        <Card className="nba-delay-2">
          <CardContent className="py-12 text-center">
            <p className="text-lg font-semibold text-foreground">
              No pipeline data available
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Export pipeline status with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                uv run nbadb journal-summary --output-path pipeline-status.json
              </code>
            </p>
          </CardContent>
        </Card>
      )}

      {summary.recentErrors.length > 0 && (
        <Card className="nba-delay-3">
          <CardHeader>
            <CardTitle>Recent Errors</CardTitle>
            <Badge variant="outline">{summary.recentErrors.length}</Badge>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {summary.recentErrors.map((errorLine, index) => (
                <div
                  key={`${index}-${errorLine.slice(0, 24)}`}
                  className="rounded-2xl border border-border/60 bg-muted/20 p-3"
                >
                  <p className="font-mono text-xs leading-6 text-foreground/80">
                    {errorLine}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
