import type { Metadata } from "next";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { getContentPages } from "@/lib/admin/content-audit";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/admin/kpi-card";
import { StatusDot } from "@/components/admin/status-dot";
import type { SubsystemStatus } from "@/lib/admin/types";

export const metadata: Metadata = { title: "Health" };
export const dynamic = "force-dynamic";

async function readPackageVersions(): Promise<
  Array<{ name: string; version: string }>
> {
  try {
    const raw = await readFile(resolve(process.cwd(), "package.json"), "utf-8");
    const pkg = JSON.parse(raw) as {
      dependencies?: Record<string, string>;
      devDependencies?: Record<string, string>;
    };
    const keyPackages = [
      "next",
      "fumadocs-core",
      "fumadocs-ui",
      "react",
      "tailwindcss",
      "recharts",
      "@tanstack/react-table",
      "@orama/orama",
    ];
    return keyPackages.map((name) => ({
      name,
      version:
        pkg.dependencies?.[name] ?? pkg.devDependencies?.[name] ?? "unknown",
    }));
  } catch {
    return [];
  }
}

function pipelineToHealth(status: string): SubsystemStatus {
  if (status === "done" || status === "running") return "healthy";
  if (status === "failed") return "degraded";
  return "unknown";
}

export default async function HealthPage() {
  const [pages, pipeline] = await Promise.all([
    getContentPages(),
    getPipelineSummary(),
  ]);

  const pipelineStatus = overallPipelineStatus(pipeline);
  const missingDesc = pages.filter((p) => !p.description).length;

  const subsystems = [
    {
      key: "Content",
      status: (pages.length > 0 ? "healthy" : "degraded") as SubsystemStatus,
      detail: `${pages.length} pages indexed, ${missingDesc} missing descriptions`,
    },
    {
      key: "Search",
      status: "unknown" as SubsystemStatus,
      detail: "Orama search — status not verified at build time",
    },
    {
      key: "Pipeline",
      status: pipelineToHealth(pipelineStatus),
      detail: pipeline.lastRun
        ? `Last run: ${pipeline.lastRun}`
        : "No pipeline data",
    },
    {
      key: "Build",
      status: "unknown" as SubsystemStatus,
      detail: `Runtime build health not verified`,
    },
  ];

  const overallStatus: SubsystemStatus = subsystems.some(
    (s) => s.status === "down",
  )
    ? "down"
    : subsystems.some((s) => s.status === "degraded")
      ? "degraded"
      : "healthy";

  const deps = await readPackageVersions();

  return (
    <div className="space-y-6 nba-reveal">
      <div className="flex items-center justify-between">
        <div>
          <p className="nba-kicker">Health</p>
          <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Site Health
          </h1>
        </div>
        <Badge variant="outline">{overallStatus}</Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 nba-delay-1">
        <KpiCard label="Total pages" value={pages.length} />
        <KpiCard label="Missing descriptions" value={missingDesc} />
        <KpiCard label="Pipeline tables" value={pipeline.totalTables} />
        <KpiCard
          label="Staging coverage"
          value={
            pipeline.stagingCoverage > 0 ? `${pipeline.stagingCoverage}%` : "—"
          }
        />
      </div>

      <Card className="nba-delay-2">
        <CardHeader>
          <CardTitle>Subsystem Status</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {subsystems.map((sub) => (
              <StatusDot
                key={sub.key}
                status={sub.status}
                label={sub.key}
                detail={sub.detail}
              />
            ))}
          </div>
        </CardContent>
      </Card>

      <Card className="nba-delay-3">
        <CardHeader>
          <CardTitle>Dependencies</CardTitle>
          <Badge variant="outline">{deps.length} packages</Badge>
        </CardHeader>
        <CardContent>
          <div className="overflow-hidden rounded-2xl border border-border/70">
            <table className="w-full">
              <thead>
                <tr className="border-b border-border/60 bg-muted/30">
                  <th className="px-4 py-3 text-left text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    Package
                  </th>
                  <th className="px-4 py-3 text-left text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                    Version
                  </th>
                </tr>
              </thead>
              <tbody>
                {deps.map((dep) => (
                  <tr
                    key={dep.name}
                    className="border-b border-border/40 transition-colors hover:bg-muted/20"
                  >
                    <td className="px-4 py-2.5 font-mono text-sm text-foreground">
                      {dep.name}
                    </td>
                    <td className="px-4 py-2.5 font-mono text-sm tabular-nums text-muted-foreground">
                      {dep.version}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
