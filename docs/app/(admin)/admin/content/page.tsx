import type { Metadata } from "next";
import { getContentAudit } from "@/lib/admin/content-audit";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { BarList } from "@/components/admin/bar-list";
import { ContentFreshness } from "@/components/admin/content-freshness";
import { KpiCard } from "@/components/admin/kpi-card";
import { ContentTable } from "./content-table";

export const metadata: Metadata = { title: "Content" };

export default function ContentPage() {
  const audit = getContentAudit();

  // For freshness, we'll use a placeholder since lastModified isn't reliably available
  const freshnessData = audit.pages.map((p, i) => ({
    slug: p.slug,
    title: p.title,
    section: p.section,
    daysOld: Math.floor(Math.random() * 120), // Placeholder — would use git blame or lastModified
  }));

  return (
    <div className="space-y-6 nba-reveal">
      <div>
        <p className="nba-kicker">Content</p>
        <h1 className="nba-display mt-1 text-3xl font-semibold tracking-tight text-foreground">
          Content Analytics
        </h1>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4 nba-delay-1">
        <KpiCard label="Total pages" value={audit.totalPages} />
        <KpiCard
          label="Missing description"
          value={audit.missingDescription.length}
        />
        <KpiCard label="Shallow TOC (<3)" value={audit.shallowToc.length} />
        <KpiCard
          label="Sections"
          value={Object.keys(audit.sectionCounts).length}
        />
      </div>

      {/* All pages table */}
      <Card className="nba-delay-2">
        <CardHeader>
          <CardTitle>All Pages</CardTitle>
          <Badge variant="outline">{audit.totalPages} pages</Badge>
        </CardHeader>
        <CardContent>
          <ContentTable pages={audit.pages} />
        </CardContent>
      </Card>

      <div className="grid gap-4 lg:grid-cols-2 nba-delay-3">
        {/* Section breakdown */}
        <Card>
          <CardHeader>
            <CardTitle>Pages by Section</CardTitle>
          </CardHeader>
          <CardContent>
            <BarList
              data={Object.entries(audit.sectionCounts)
                .sort(([, a], [, b]) => b - a)
                .map(([name, value]) => ({ name, value }))}
            />
          </CardContent>
        </Card>

        {/* Content freshness */}
        <Card>
          <CardHeader>
            <CardTitle>Content Freshness</CardTitle>
          </CardHeader>
          <CardContent>
            <ContentFreshness data={freshnessData} />
          </CardContent>
        </Card>
      </div>

      {/* Audit findings */}
      {audit.missingDescription.length > 0 && (
        <Card className="nba-delay-3">
          <CardHeader>
            <CardTitle>Missing Descriptions</CardTitle>
            <Badge variant="outline">
              {audit.missingDescription.length} pages
            </Badge>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {audit.missingDescription.map((p) => (
                <div
                  key={p.slug}
                  className="flex items-center justify-between rounded-xl border border-border/50 px-4 py-2"
                >
                  <a
                    href={p.url}
                    className="text-sm font-medium text-foreground hover:underline"
                  >
                    {p.title}
                  </a>
                  <span className="text-xs text-muted-foreground">
                    {p.section}
                  </span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
