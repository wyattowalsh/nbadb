import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { KpiCard } from "@/components/admin/kpi-card";
import { TrackerBar } from "@/components/admin/tracker-bar";
import { BarList } from "@/components/admin/bar-list";
import { StatusDot } from "@/components/admin/status-dot";
import { OverviewSparklines } from "./overview-sparklines";
import type { SubsystemStatus } from "@/lib/admin/types";
import { getContentAudit } from "@/lib/admin/content-audit";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";
import { getStats } from "@/lib/admin/umami";

export const dynamic = "force-dynamic";

export default async function AdminOverviewPage() {
  const analyticsEnabled = Boolean(
    process.env.UMAMI_API_TOKEN && process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID,
  );
  const [audit, pipeline, stats] = await Promise.all([
    getContentAudit(),
    getPipelineSummary(),
    analyticsEnabled ? getStats("7d") : Promise.resolve(null),
  ]);
  const pipelineStatus = overallPipelineStatus(pipeline);

  const missingDesc = audit.missingDescription.length;
  const health = {
    overall: (pipeline.counts.failed > 0
      ? "degraded"
      : audit.totalPages > 0
        ? "healthy"
        : "unknown") as SubsystemStatus,
    subsystems: {
      content: {
        status: (audit.totalPages > 0
          ? "healthy"
          : "degraded") as SubsystemStatus,
        detail: `${audit.totalPages} pages indexed, ${missingDesc} missing descriptions`,
      },
      pipeline: {
        status: (pipelineStatus === "failed"
          ? "degraded"
          : pipelineStatus === "abandoned"
            ? "unknown"
            : "healthy") as SubsystemStatus,
        detail: pipeline.lastRun
          ? `Last run: ${pipeline.lastRun}`
          : "No pipeline data",
      },
    },
  };
  return (
    <div className="space-y-6 nba-reveal">
      <div>
        <p className="nba-kicker">Overview</p>
        <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
          Control Center
        </h1>
      </div>

      {/* KPI row */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-5 nba-delay-1">
        <KpiCard label="Total pages" value={audit.totalPages} />
        <KpiCard
          label="Missing descriptions"
          value={audit.missingDescription.length}
        />
        <KpiCard label="Shallow TOC" value={audit.shallowToc.length} />
        <KpiCard
          label="Visitors (7d)"
          value={stats?.visitors?.toLocaleString() ?? "—"}
        />
        <KpiCard
          label="Pageviews (7d)"
          value={stats?.pageviews?.toLocaleString() ?? "—"}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-[minmax(0,1.2fr)_minmax(16rem,1fr)] nba-delay-2">
        {/* Sparklines */}
        <OverviewSparklines analyticsEnabled={analyticsEnabled} />

        {/* Health summary */}
        <Card>
          <CardHeader>
            <CardTitle>System Health</CardTitle>
            {health && <Badge variant="outline">{health.overall}</Badge>}
          </CardHeader>
          <CardContent>
            {health ? (
              <div className="space-y-3">
                {Object.entries(health.subsystems).map(([key, sub]) => (
                  <StatusDot
                    key={key}
                    status={sub.status}
                    label={key.charAt(0).toUpperCase() + key.slice(1)}
                    detail={sub.detail}
                  />
                ))}
              </div>
            ) : (
              <p className="text-sm text-muted-foreground">
                Health data unavailable
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-2 nba-delay-3">
        {/* Pipeline tracker */}
        <Card>
          <CardHeader>
            <CardTitle>Pipeline Runs</CardTitle>
            {pipeline && <Badge variant="outline">{pipelineStatus}</Badge>}
          </CardHeader>
          <CardContent>
            {pipeline && pipeline.runs.length > 0 ? (
              <TrackerBar
                data={pipeline.runs.map((r) => ({
                  status: r.status,
                  label: `${r.status} — ${r.tablesProcessed} tables`,
                }))}
              />
            ) : (
              <p className="text-sm text-muted-foreground">
                No pipeline run data available
              </p>
            )}
          </CardContent>
        </Card>

        {/* Section breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Content by Section</CardTitle>
          </CardHeader>
          <CardContent>
            <BarList
              data={Object.entries(audit.sectionCounts)
                .sort(([, a], [, b]) => b - a)
                .map(([name, value]) => ({ name, value }))}
            />
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
