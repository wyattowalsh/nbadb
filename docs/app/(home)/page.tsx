import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Counter } from "@/components/site/counter";
import { siteMetrics } from "@/lib/site-metrics.generated";
import { audienceLanes, docsSections, heroSignals } from "@/lib/site-config";

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
    note: "NBA API extractors mapped to staging tables",
  },
  {
    step: "03",
    label: "Launch the browser explorer",
    href: "/docs/playground",
    note: "DuckDB-WASM sandbox with NBA-flavored sample drills",
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
        className="nba-hero-bg mx-auto w-full max-w-5xl px-4 pb-10 pt-12 sm:px-6 lg:px-8"
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
              NBA warehouse docs with an actual court view: endpoint coverage,
              possession-level lineage, and analyst-ready tables laid out like a
              scouting board instead of a generic software landing page.
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

            <p className="mt-3 max-w-2xl text-xs leading-5 text-muted-foreground nba-delay-2">
              Pick the first route by job to be done: quick analyst reps, daily
              pipeline operations, table scouting, or a no-install DuckDB
              warmup.
            </p>
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
              <span className="nba-kicker">From tip-off to final horn</span>
              <p>
                Raw nba_api feeds staged in DuckDB, transformed into star-schema
                tables, then routed into docs pages that explain where every
                play and model came from.
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
            <h2 className="nba-kicker">Choose by question</h2>
            <p className="mt-2 max-w-2xl text-xs leading-5 text-muted-foreground">
              Start with the warehouse shape, source feeds, dependency replay,
              or execution guides depending on what you need to answer next.
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

      {/* ── Audience lanes ─────────────────────────── */}
      <section
        id="lanes"
        className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6 lg:px-8 nba-reveal nba-delay-3"
      >
        <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
          <h2 className="nba-kicker">Choose your lane</h2>
          <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
            Three clean entries depending on whether you are scouting the model,
            running the pipeline, or jumping straight into analysis.
          </p>
        </div>
        <div className="grid gap-px border border-border md:grid-cols-3">
          {audienceLanes.map((lane) => (
            <Link
              key={lane.label}
              href={lane.href}
              className="nba-lane-card group bg-card px-4 py-5 transition-colors hover:bg-muted"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="nba-kicker">{lane.label}</span>
                <ArrowRight className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
              </div>
              <div className="mt-3 text-base font-semibold text-foreground">
                {lane.title}
              </div>
              <p className="mt-2 text-xs leading-5 text-muted-foreground">
                {lane.description}
              </p>
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
      <footer className="mx-auto w-full max-w-5xl px-4 pb-12 sm:px-6 lg:px-8">
        <div className="border-t border-border pt-8">
          <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
            <div className="max-w-sm">
              <div className="flex items-center gap-2">
                <Image
                  src="/logo-600.png"
                  alt=""
                  width={600}
                  height={600}
                  className="h-6 w-auto"
                />
                <span className="nba-display text-base font-bold tracking-tight text-foreground">
                  nbadb
                </span>
                <Badge variant="primary">v4</Badge>
              </div>
              <p className="mt-3 text-xs leading-5 text-muted-foreground">
                Star-schema NBA data warehouse documentation. DuckDB-first with
                full endpoint coverage, lineage, and schema docs.
              </p>
            </div>

            <div className="flex gap-10 text-xs">
              <div className="space-y-2">
                <span className="nba-kicker">Docs</span>
                <div className="flex flex-col gap-1.5">
                  <Link
                    href="/docs/schema"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Schema
                  </Link>
                  <Link
                    href="/docs/endpoints"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Endpoints
                  </Link>
                  <Link
                    href="/docs/lineage"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Lineage
                  </Link>
                  <Link
                    href="/docs/guides"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                  >
                    Guides
                  </Link>
                </div>
              </div>
              <div className="space-y-2">
                <span className="nba-kicker">Resources</span>
                <div className="flex flex-col gap-1.5">
                  <a
                    href="https://github.com/wyattowalsh/nba-db"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    GitHub
                  </a>
                  <a
                    href="https://www.kaggle.com/datasets/wyattowalsh/basketball"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Kaggle
                  </a>
                  <a
                    href="https://pypi.org/project/nbadb/"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    PyPI
                  </a>
                </div>
              </div>
              <div className="space-y-2">
                <span className="nba-kicker">Built with</span>
                <div className="flex flex-col gap-1.5">
                  <a
                    href="https://duckdb.org"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    DuckDB
                  </a>
                  <a
                    href="https://pola.rs"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Polars
                  </a>
                  <a
                    href="https://github.com/swar/nba_api"
                    className="text-muted-foreground hover:text-foreground transition-colors"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    nba_api
                  </a>
                </div>
              </div>
            </div>
          </div>

          <div className="mt-8 border-t border-border pt-4">
            <p className="text-xs text-muted-foreground">
              Open-source NBA data warehouse documentation.
            </p>
          </div>
        </div>
      </footer>
    </main>
  );
}
