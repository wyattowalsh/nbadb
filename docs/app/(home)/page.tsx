import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { siteMetrics, docsSections } from "@/lib/site-config";

const quickStart = [
  {
    step: "01",
    label: "Explore the schema",
    href: "/docs/schema",
    note: "dimensions, facts, bridges, analytics views",
  },
  {
    step: "02",
    label: "Scout endpoint coverage",
    href: "/docs/endpoints",
    note: "131 NBA API extractors mapped to staging tables",
  },
  {
    step: "03",
    label: "Run DuckDB queries",
    href: "/docs/guides/duckdb-queries",
    note: "analyst-first patterns for the star schema",
  },
];

export default function HomePage() {
  return (
    <main className="nba-home-shell flex flex-1 flex-col">
      {/* ── Stat hero ────────────────────────────────── */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-10 pt-12 sm:px-6 lg:px-8">
        <div className="nba-reveal">
          <div className="flex flex-wrap items-center gap-3">
            <img src="/logo-600.png" alt="" className="h-10 w-auto sm:h-12" />
            <span className="nba-display text-2xl font-bold tracking-tight text-foreground sm:text-3xl">
              nbadb
            </span>
            <Badge variant="primary">v4</Badge>
            <Badge variant="default">star schema</Badge>
            <Badge variant="default">DuckDB</Badge>
          </div>

          <p className="mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
            NBA data warehouse documentation. 141-table star schema built from
            131 nba_api endpoints. Dimensions, facts, lineage, and operational
            guides.
          </p>

          {/* Stat counters */}
          <div className="mt-8 grid grid-cols-2 gap-px border border-border sm:grid-cols-4 nba-delay-1">
            {siteMetrics.map((metric) => (
              <div
                key={metric.label}
                className="bg-card px-4 py-4"
              >
                <div className="nba-scoreboard-value text-3xl font-bold text-foreground sm:text-4xl">
                  {metric.value}
                </div>
                <div className="nba-metric-label mt-1">{metric.label}</div>
                <div className="mt-1 text-xs text-muted-foreground">
                  {metric.note}
                </div>
              </div>
            ))}
          </div>

          {/* Actions */}
          <div className="mt-6 flex flex-wrap gap-3 nba-delay-2">
            <Button asChild size="default">
              <Link href="/docs">
                Enter docs
                <ArrowRight className="size-4" />
              </Link>
            </Button>
            <Button asChild size="default" variant="outline">
              <Link href="/docs/schema">Schema</Link>
            </Button>
            <Button asChild size="default" variant="outline">
              <Link href="/docs/guides/analytics-quickstart">Quickstart</Link>
            </Button>
            <Button asChild size="default" variant="ghost">
              <a
                href="https://www.kaggle.com/datasets/wyattowalsh/basketball"
                target="_blank"
                rel="noopener noreferrer"
              >
                Kaggle dataset
              </a>
            </Button>
          </div>
        </div>
      </section>

      {/* ── Section index ────────────────────────────── */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6 lg:px-8 nba-reveal nba-delay-2">
        <div className="mb-4">
          <span className="nba-kicker">Sections</span>
        </div>
        <div className="grid gap-px border border-border sm:grid-cols-2 lg:grid-cols-3">
          {docsSections.map((section) => (
            <Link
              key={section.id}
              href={section.hubHref}
              className="group flex flex-col justify-between bg-card px-4 py-4 transition-colors hover:bg-muted"
            >
              <div>
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-bold uppercase tracking-[0.16em] text-foreground">
                    {section.label}
                  </span>
                  <ArrowRight className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
                  {section.blurb}
                </p>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {section.stats.slice(0, 2).map((stat) => (
                  <span
                    key={stat.label}
                    className="text-xs text-muted-foreground"
                  >
                    <span className="font-bold text-foreground">{stat.value}</span>{" "}
                    {stat.label.toLowerCase()}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Quick start ──────────────────────────────── */}
      <section className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
        <div className="mb-4">
          <span className="nba-kicker">Quick start</span>
        </div>
        <div className="divide-y divide-border border border-border">
          {quickStart.map((item) => (
            <Link
              key={item.step}
              href={item.href}
              className="group flex items-center gap-4 bg-card px-4 py-3 transition-colors hover:bg-muted"
            >
              <span className="text-sm font-bold tabular-nums text-primary">
                {item.step}
              </span>
              <span className="text-sm font-semibold text-foreground">
                {item.label}
              </span>
              <span className="hidden text-xs text-muted-foreground sm:inline" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
                {item.note}
              </span>
              <ArrowRight className="ml-auto size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </section>
    </main>
  );
}
