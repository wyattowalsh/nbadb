import type { Metadata } from "next";
import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { KpiCard } from "@/components/admin/kpi-card";

export const metadata: Metadata = { title: "Profiling" };

type ColumnProfile = {
  name: string;
  type: string;
  nullPct: number;
};

type TableProfile = {
  table: string;
  layer: string;
  rowCount: number;
  columnCount: number;
  columns: ColumnProfile[];
};

const PROFILE_PATHS = [
  resolve(process.cwd(), "table-profile.generated.json"),
  resolve(process.cwd(), "../table-profile.generated.json"),
  resolve(process.cwd(), "lib/admin/table-profile.generated.json"),
];

async function getTableProfiles(): Promise<TableProfile[]> {
  for (const filePath of PROFILE_PATHS) {
    try {
      const raw = await readFile(filePath, "utf-8");
      return JSON.parse(raw) as TableProfile[];
    } catch {
      continue;
    }
  }
  return [];
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
  const sortedLayers = [...grouped.entries()].sort(
    (a, b) => layerOrder.indexOf(a[0]) - layerOrder.indexOf(b[0]),
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
            <div className="overflow-hidden rounded-2xl border border-border/70">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border/60 bg-muted/30">
                    <th className="px-4 py-3 text-left text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Table
                    </th>
                    <th className="px-4 py-3 text-right text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Rows
                    </th>
                    <th className="px-4 py-3 text-right text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                      Columns
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {tables.map((t) => (
                    <tr
                      key={t.table}
                      className="border-b border-border/40 transition-colors hover:bg-muted/20"
                    >
                      <td className="px-4 py-2.5 font-mono text-sm text-foreground">
                        {t.table}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-sm tabular-nums text-muted-foreground">
                        {t.rowCount.toLocaleString()}
                      </td>
                      <td className="px-4 py-2.5 text-right font-mono text-sm tabular-nums text-muted-foreground">
                        {t.columnCount}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
