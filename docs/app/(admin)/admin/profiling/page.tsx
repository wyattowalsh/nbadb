import type { Metadata } from "next";
import { resolve } from "node:path";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/admin/kpi-card";
import { readFirstJson } from "@/lib/admin/files";
import type { TableProfile } from "@/lib/admin/types";
import { ProfilingLayerTable } from "./profiling-layer-table";

export const metadata: Metadata = { title: "Profiling" };
export const dynamic = "force-dynamic";

const PROFILE_PATHS = [
  resolve(
    /* turbopackIgnore: true */ process.cwd(),
    "table-profile.generated.json",
  ),
  resolve(
    /* turbopackIgnore: true */ process.cwd(),
    "../table-profile.generated.json",
  ),
  resolve(
    /* turbopackIgnore: true */ process.cwd(),
    "lib/admin/table-profile.generated.json",
  ),
];

async function getTableProfiles(): Promise<TableProfile[]> {
  return (await readFirstJson<TableProfile[]>(PROFILE_PATHS)) ?? [];
}

export default async function ProfilingPage() {
  const profiles = await getTableProfiles();

  if (profiles.length === 0) {
    return (
      <div className="space-y-6 nba-reveal">
        <div>
          <p className="nba-kicker">Profiling</p>
          <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
            Table Profiling
          </h1>
        </div>
        <Card>
          <CardContent className="py-12 text-center">
            <p className="text-lg font-semibold text-foreground">
              No profiling data available
            </p>
            <p className="mt-2 text-sm text-muted-foreground">
              Generate table profiles with{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 text-xs">
                uv run nbadb docs-autogen --docs-root docs/content/docs
              </code>
            </p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const totalTables = profiles.length;
  const totalRows = profiles.reduce((sum, p) => sum + p.rowCount, 0);
  const totalColumns = profiles.reduce((sum, p) => sum + p.columnCount, 0);

  const grouped = new Map<string, TableProfile[]>();
  for (const profile of profiles) {
    const existing = grouped.get(profile.layer);
    if (existing) {
      existing.push(profile);
    } else {
      grouped.set(profile.layer, [profile]);
    }
  }

  const layerOrder = [
    "raw",
    "staging",
    "dimension",
    "bridge",
    "fact",
    "aggregate",
    "analytics",
    "other",
  ];
  const layerRank = (layer: string) => {
    const idx = layerOrder.indexOf(layer);
    return idx === -1 ? Number.MAX_SAFE_INTEGER : idx;
  };
  const sortedLayers = [...grouped.entries()].sort(
    (a, b) => layerRank(a[0]) - layerRank(b[0]),
  );

  return (
    <div className="space-y-6 nba-reveal">
      <div>
        <p className="nba-kicker">Profiling</p>
        <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
          Table Profiling
        </h1>
      </div>

      <div className="grid gap-4 sm:grid-cols-3 nba-delay-1">
        <KpiCard label="Tables" value={totalTables} />
        <KpiCard label="Total Rows" value={totalRows.toLocaleString()} />
        <KpiCard label="Total Columns" value={totalColumns.toLocaleString()} />
      </div>

      {sortedLayers.map(([layer, tables]) => (
        <Card key={layer} className="nba-delay-2">
          <CardHeader>
            <CardTitle className="capitalize">{layer}</CardTitle>
            <Badge variant="outline">{tables.length} tables</Badge>
          </CardHeader>
          <CardContent>
            <ProfilingLayerTable tables={tables} />
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
