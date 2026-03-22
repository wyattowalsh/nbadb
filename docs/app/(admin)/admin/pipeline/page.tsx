import type { Metadata } from "next";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/admin/kpi-card";
import { TrackerBar } from "@/components/admin/tracker-bar";
import { PipelineCharts } from "./pipeline-charts";

export const metadata: Metadata = { title: "Pipeline" };

export default async function PipelinePage() {
  const summary = await getPipelineSummary();
  const status = overallPipelineStatus(summary);

  const statusLabel: Record<string, string> = {
    done: "Healthy",
    failed: "Errors detected",
    running: "Running now",
    abandoned: "No data",
  };

  return (
    <div className="space-y-6 nba-reveal">
      <div className="flex items-center justify-between">
        <div>
          <p className="nba-kicker">Pipeline</p>
          <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Pipeline Status
          </h1>
        </div>
        <Badge variant="outline">{statusLabel[status]}</Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 nba-delay-1">
        <KpiCard label="Done" value={summary.counts.done} />
        <KpiCard label="Failed" value={summary.counts.failed} />
        <KpiCard label="Running" value={summary.counts.running} />
        <KpiCard label="Total tables" value={summary.totalTables} />
      </div>

      {summary.runs.length > 0 ? (
        <>
          <Card className="nba-delay-2">
            <CardHeader>
              <CardTitle>Run History</CardTitle>
              <Badge variant="outline">{summary.runs.length} runs</Badge>
            </CardHeader>
            <CardContent>
              <TrackerBar
                data={summary.runs.map((r) => ({
                  status: r.status,
                  label: `${r.status} — ${r.tablesProcessed} tables, ${r.rowsExtracted} rows`,
                }))}
              />
            </CardContent>
          </Card>

          <PipelineCharts runs={summary.runs} counts={summary.counts} />
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
                uv run nbadb journal-summary --json &gt; pipeline-status.json
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
            <div className="max-h-64 overflow-y-auto rounded-xl bg-muted/30 p-4">
              <pre className="whitespace-pre-wrap font-mono text-xs text-foreground/80">
                {summary.recentErrors.join("\n\n")}
              </pre>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
