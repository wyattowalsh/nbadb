import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Counter } from "@/components/site/counter";
import { DocsFooter } from "@/components/site/footer";
import { siteMetrics } from "@/lib/site-metrics.generated";
import { docsSections, heroSignals } from "@/lib/site-config";

const quickStart = [
  {
    step: "01",
    label: "Browse the schema",
    href: "/docs/schema",
    note: "dimensions, facts, bridges, and analytics views",
  },
  {
    step: "02",
    label: "Check endpoint coverage",
    href: "/docs/endpoints",
    note: "NBA API extractors mapped to staging tables",
  },
  {
    step: "03",
    label: "Try the playground",
    href: "/docs/playground",
    note: "DuckDB-WASM sandbox with sample queries",
  },
];

const heroBoard = [
  {
    label: "Warehouse",
    note: "raw -> staging -> star",
  },
  {
    label: "Lineage",
    note: "table and column replay",
  },
  {
    label: "Playground",
    note: "DuckDB in the browser",
  },
];

export default function HomePage() {
  return (
    <main className="nba-home-shell flex flex-1 flex-col">
      {/* ── Stat hero ────────────────────────────────── */}
      <section
        id="scoreboard"
        className="nba-hero-bg mx-auto w-full max-w-5xl px-4 pb-8 pt-8 sm:px-6 lg:px-8"
      >
        <div className="nba-hero-grid nba-reveal">
          <div>
            <span className="nba-kicker">NBA warehouse documentation</span>
            <div className="flex flex-wrap items-center gap-3">
              <Image
                src="/logo-600.png"
                alt=""
                width={600}
                height={600}
                className="h-10 w-auto sm:h-12"
                priority
              />
              <h1 className="nba-display nba-title-gradient text-2xl font-bold tracking-tight sm:text-3xl">
                nbadb
              </h1>
              <Badge variant="primary">v4</Badge>
              <Badge variant="default">star schema</Badge>
              <Badge variant="default">DuckDB</Badge>
            </div>

            <p className="nba-hero-lede mt-3 max-w-2xl text-sm leading-relaxed text-muted-foreground">
              Documentation for the nbadb star-schema warehouse: endpoint
              coverage, table lineage, and analyst-ready references for every
              stage of the pipeline.
            </p>

            <div className="mt-6 grid gap-px border border-border bg-border sm:grid-cols-3 nba-delay-1">
              {heroSignals.map((signal) => (
                <div
                  key={signal.label}
                  className="nba-hero-signal bg-card px-4 py-4"
                >
                  <div className="nba-kicker">{signal.label}</div>
                  <div className="mt-2 text-sm font-semibold text-foreground">
                    {signal.title}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    {signal.description}
                  </p>
                </div>
              ))}
            </div>

            {/* Actions */}
            <div className="mt-6 flex flex-wrap gap-3 nba-delay-2">
              <Button asChild size="default">
                <Link href="/docs/guides/analytics-quickstart">
                  Analyst quickstart
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
              <Button asChild size="default" variant="outline">
                <Link href="/docs/guides/daily-updates">Operator guide</Link>
              </Button>
              <Button asChild size="default" variant="outline">
                <Link href="/docs/schema">Schema map</Link>
              </Button>
              <Button asChild size="default" variant="outline">
                <Link href="/docs/playground">Browser playground</Link>
              </Button>
            </div>
          </div>

          <div className="nba-court-panel nba-delay-1" aria-hidden="true">
            <div className="nba-court-markings">
              <div className="nba-court-midline" />
              <div className="nba-court-circle" />
              <div className="nba-court-key nba-court-key-left" />
              <div className="nba-court-key nba-court-key-right" />
              <div className="nba-court-arc nba-court-arc-left" />
              <div className="nba-court-arc nba-court-arc-right" />
            </div>

            <div className="nba-hero-mark">
              <Image
                src="/logo-600.png"
                alt=""
                width={600}
                height={600}
                className="h-auto w-full"
                priority
              />
            </div>

            <div className="nba-hero-board">
              {heroBoard.map((item) => (
                <div key={item.label} className="nba-hero-board-chip">
                  <span className="nba-kicker">{item.label}</span>
                  <span>{item.note}</span>
                </div>
              ))}
            </div>

            <div className="nba-court-caption">
              <span className="nba-kicker">Pipeline flow</span>
              <p>
                Raw nba_api feeds staged in DuckDB, transformed into star-schema
                tables, and documented end-to-end.
              </p>
            </div>
          </div>
        </div>

        <div className="mt-8 flex flex-wrap items-center justify-between gap-3 nba-delay-2">
          <h2 className="nba-kicker">Scoreboard</h2>
          <span className="text-xs text-muted-foreground">
            Counts refreshed by docs-autogen from the current code snapshot.
          </span>
        </div>

        {/* Stat counters */}
        <div className="mt-3 grid grid-cols-2 gap-px border border-border sm:grid-cols-4 nba-delay-2">
          {siteMetrics.map((metric) => (
            <div
              key={metric.label}
              className="nba-metric-card bg-card px-4 py-4"
            >
              <div className="nba-scoreboard-value text-3xl font-bold text-foreground sm:text-4xl">
                {/^\d+$/.test(metric.value) ? (
                  <Counter
                    target={parseInt(metric.value, 10)}
                    className="tabular-nums"
                  />
                ) : (
                  metric.value
                )}
              </div>
              <div className="nba-metric-label mt-1">{metric.label}</div>
              <div className="mt-1 text-xs text-muted-foreground">
                {metric.note}
              </div>
            </div>
          ))}
        </div>
      </section>

      {/* ── Section index ────────────────────────────── */}
      <section
        id="sections"
        className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6 lg:px-8 nba-reveal nba-delay-2"
      >
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <div>
            <h2 className="nba-kicker">Browse by topic</h2>
            <p className="mt-2 max-w-2xl text-xs leading-5 text-muted-foreground">
              Schema, endpoints, lineage, guides, and more — organized by what
              you need to look up.
            </p>
          </div>
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
                <div className="mt-3 flex flex-wrap gap-2">
                  <Badge variant="muted">{section.cue}</Badge>
                  {section.stats[2] ? (
                    <Badge variant="outline">{section.stats[2].value}</Badge>
                  ) : null}
                </div>
                <p className="mt-2 text-xs leading-5 text-muted-foreground">
                  {section.blurb}
                </p>
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                {section.stats.slice(0, 2).map((stat) => (
                  <span
                    key={stat.label}
                    className="text-xs text-muted-foreground"
                  >
                    <span className="font-bold text-foreground">
                      {stat.value}
                    </span>{" "}
                    {stat.label.toLowerCase()}
                  </span>
                ))}
              </div>
            </Link>
          ))}
        </div>
      </section>

      {/* ── Quick start ──────────────────────────────── */}
      <section
        id="quickstart"
        className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6 lg:px-8 nba-reveal nba-delay-3"
      >
        <div className="mb-4">
          <h2 className="nba-kicker">Quick start</h2>
        </div>
        <div className="divide-y divide-border border border-border">
          {quickStart.map((item) => (
            <Link
              key={item.step}
              href={item.href}
              className="group flex items-center gap-4 bg-card px-4 py-3 transition-colors hover:bg-muted"
            >
              <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/15 text-sm font-bold tabular-nums text-primary shadow-sm shadow-primary/10">
                {item.step}
              </span>
              <span className="text-sm font-semibold text-foreground">
                {item.label}
              </span>
              <span className="text-xs text-muted-foreground">{item.note}</span>
              <ArrowRight className="ml-auto size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
            </Link>
          ))}
        </div>
      </section>

      {/* ── Footer ───────────────────────────────────── */}
      <DocsFooter />
    </main>
  );
}
