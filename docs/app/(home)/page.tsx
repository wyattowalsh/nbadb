import Image from "next/image";
import Link from "next/link";
import type { CSSProperties } from "react";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Counter } from "@/components/site/counter";
import { DocsFooter } from "@/components/site/footer";
import { siteMetrics } from "@/lib/site-metrics.generated";
import {
  audienceLanes,
  docsSections,
  heroSignals,
  siteDescription,
  siteOrigin,
  siteTitle,
} from "@/lib/site-config";
import { serializeJsonLd } from "@/lib/utils";

const sectionCardBackgrounds: Record<
  (typeof docsSections)[number]["id"],
  CSSProperties
> = {
  core: {
    backgroundImage:
      "radial-gradient(circle at top right, color-mix(in oklch, var(--primary) 28%, transparent), transparent 52%), radial-gradient(circle at bottom left, color-mix(in oklch, var(--accent) 18%, transparent), transparent 48%)",
  },
  schema: {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(56, 189, 248, 0.22), transparent 52%), radial-gradient(circle at bottom left, rgba(34, 197, 94, 0.12), transparent 46%)",
  },
  "data-dictionary": {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(244, 114, 182, 0.2), transparent 50%), radial-gradient(circle at bottom left, rgba(168, 85, 247, 0.14), transparent 44%)",
  },
  diagrams: {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(250, 204, 21, 0.18), transparent 48%), radial-gradient(circle at bottom left, rgba(248, 113, 113, 0.12), transparent 44%)",
  },
  endpoints: {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(251, 146, 60, 0.2), transparent 52%), radial-gradient(circle at bottom left, rgba(239, 68, 68, 0.14), transparent 46%)",
  },
  lineage: {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(45, 212, 191, 0.2), transparent 50%), radial-gradient(circle at bottom left, rgba(59, 130, 246, 0.14), transparent 46%)",
  },
  guides: {
    backgroundImage:
      "radial-gradient(circle at top right, rgba(129, 140, 248, 0.2), transparent 52%), radial-gradient(circle at bottom left, rgba(244, 114, 182, 0.12), transparent 46%)",
  },
};

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
  const structuredData = {
    "@context": "https://schema.org",
    "@type": "WebSite",
    name: siteTitle,
    description: siteDescription,
    url: siteOrigin,
  };

  return (
    <>
      <script
        type="application/ld+json"
        dangerouslySetInnerHTML={{ __html: serializeJsonLd(structuredData) }}
      />
      <main id="main-content" className="nba-home-shell flex flex-1 flex-col">
        {/* ── Stat hero ────────────────────────────────── */}
        <section className="nba-hero-bg mx-auto w-full max-w-5xl px-4 pb-10 pt-12 sm:px-6 lg:px-8">
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
                possession-level lineage, and analyst-ready tables laid out like
                a scouting board instead of a generic software landing page.
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
              <div className="mt-6 grid gap-3 sm:flex sm:flex-wrap nba-delay-2">
                <Button
                  asChild
                  size="default"
                  className="justify-between sm:justify-center"
                >
                  <Link href="/docs/guides/analytics-quickstart">
                    Analyst quickstart
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <Button
                  asChild
                  size="default"
                  variant="outline"
                  className="justify-between sm:justify-center"
                >
                  <Link href="/docs/guides/daily-updates">Operator guide</Link>
                </Button>
                <Button
                  asChild
                  size="default"
                  variant="outline"
                  className="justify-between sm:justify-center"
                >
                  <Link href="/docs/schema">Schema map</Link>
                </Button>
                <Button
                  asChild
                  size="default"
                  variant="outline"
                  className="justify-between sm:justify-center"
                >
                  <Link href="/docs/playground">Browser playground</Link>
                </Button>
              </div>

              <p className="mt-3 max-w-2xl text-xs leading-5 text-muted-foreground nba-delay-2">
                Pick the first route by job to be done: quick analyst reps,
                daily pipeline operations, table scouting, or a no-install
                DuckDB warmup.
              </p>
            </div>

            <div className="nba-court-panel nba-delay-1" aria-hidden="true">
              <div className="pointer-events-none absolute inset-0">
                <Image
                  src="/hero-homepage.png"
                  alt=""
                  fill
                  className="object-cover opacity-28"
                  sizes="(min-width: 1024px) 34rem, 100vw"
                  priority
                />
                <div className="absolute inset-0 bg-gradient-to-br from-background/24 via-transparent to-background/68" />
              </div>
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
                  Raw nba_api feeds staged in DuckDB, transformed into
                  star-schema tables, then routed into docs pages that explain
                  where every play and model came from.
                </p>
              </div>
            </div>
          </div>

          <div className="mt-8 flex flex-wrap items-center justify-between gap-3 nba-delay-2">
            <span className="nba-kicker">Scoreboard</span>
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
        <section className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6 lg:px-8 nba-reveal nba-delay-2">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <div>
              <span className="nba-kicker">Choose by question</span>
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
                className="group relative flex flex-col justify-between overflow-hidden bg-card px-4 py-4 transition-colors hover:bg-muted"
                data-section={section.id}
              >
                <div
                  className="pointer-events-none absolute inset-0 opacity-95 transition-transform duration-500 group-hover:scale-[1.02]"
                  style={sectionCardBackgrounds[section.id]}
                />
                <div className="pointer-events-none absolute inset-0 bg-gradient-to-br from-card/96 via-card/82 to-card/92" />
                <div className="relative z-10">
                  <div className="flex items-center justify-between gap-2">
                    <span className="text-sm font-bold uppercase tracking-[0.16em] text-foreground">
                      {section.label}
                    </span>
                    <ArrowRight className="size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary" />
                  </div>
                  <div className="mt-3 flex flex-wrap gap-2">
                    <Badge variant="muted">{section.cue}</Badge>
                    {section.stats[2] && (
                      <Badge variant="outline">{section.stats[2].value}</Badge>
                    )}
                  </div>
                  <p className="mt-2 text-xs leading-5 text-muted-foreground">
                    {section.blurb}
                  </p>
                </div>
                <div className="relative z-10 mt-3 flex flex-wrap gap-2">
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
        <section className="mx-auto w-full max-w-5xl px-4 pb-10 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
          <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
            <span className="nba-kicker">Choose your lane</span>
            <p className="max-w-2xl text-xs leading-5 text-muted-foreground">
              Three clean entries depending on whether you are scouting the
              model, running the pipeline, or jumping straight into analysis.
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
        <section className="mx-auto w-full max-w-5xl px-4 pb-16 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
          <div className="mb-4">
            <span className="nba-kicker">Quick start</span>
          </div>
          <div className="divide-y divide-border border border-border">
            {quickStart.map((item) => (
              <Link
                key={item.step}
                href={item.href}
                className="group grid grid-cols-[auto_minmax(0,1fr)_auto] items-start gap-4 bg-card px-4 py-3 transition-colors hover:bg-muted"
              >
                <span className="flex size-8 shrink-0 items-center justify-center rounded-full border border-primary/30 bg-primary/15 text-sm font-bold tabular-nums text-primary shadow-sm shadow-primary/10">
                  {item.step}
                </span>
                <span className="min-w-0">
                  <span className="text-sm font-semibold text-foreground">
                    {item.label}
                  </span>
                  <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                    {item.note}
                  </span>
                </span>
                <ArrowRight className="mt-1 size-3.5 text-muted-foreground transition-transform group-hover:translate-x-0.5 group-hover:text-primary sm:mt-0 sm:self-center" />
              </Link>
            ))}
          </div>
        </section>

        {/* ── Footer ───────────────────────────────────── */}
        <DocsFooter />
      </main>
    </>
  );
}
