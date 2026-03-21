import Link from "next/link";
import {
  ArrowRight,
  Binoculars,
  BookOpenText,
  Database,
  LayoutGrid,
  Network,
  Radar,
  Route,
  Search,
  ShieldCheck,
  Trophy,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  audienceLanes,
  docsSections,
  heroSignals,
  searchPrompts,
  siteMetrics,
  type SectionId,
} from "@/lib/site-config";

const featureRows = [
  {
    label: "Warehouse",
    title: "Model the league like a front office.",
    description:
      "Dimensions, facts, bridges, and derived views laid out with the clarity of a half-court diagram.",
    href: "/docs/schema",
  },
  {
    label: "Coverage",
    title: "Scout the full endpoint surface.",
    description:
      "Move from box scores to play-by-play to draft without losing the thread of how each extractor fits the system.",
    href: "/docs/endpoints",
  },
  {
    label: "Operations",
    title: "Run the pipeline like a composed possession.",
    description:
      "Guides, playbooks, and troubleshooting surfaces make recurring workflows feel deliberate instead of fragile.",
    href: "/docs/guides",
  },
];

const audienceIcons = [Database, ShieldCheck, Binoculars];
const sectionIcons: Record<SectionId, typeof Radar> = {
  schema: Database,
  endpoints: Trophy,
  lineage: Network,
  guides: Route,
  diagrams: LayoutGrid,
  "data-dictionary": BookOpenText,
  core: Radar,
};

const tickerItems = [
  "141-table public model",
  "131 endpoint scouting surface",
  "DuckDB-first analyst workflow",
  "Per-page OG and share kit",
  "Basketball-native visual prompt pack",
];

const heroRoutes = [
  {
    title: "Schema",
    note: "grains, joins, and table families",
    href: "/docs/schema",
    top: "11%",
    left: "8%",
  },
  {
    title: "Guides",
    note: "repeatable analyst and ops plays",
    href: "/docs/guides",
    top: "24%",
    left: "57%",
  },
  {
    title: "Lineage",
    note: "blast radius and dependency replay",
    href: "/docs/lineage",
    top: "60%",
    left: "11%",
  },
  {
    title: "Art Pack",
    note: "prompt-ready hero, OG, and icon system",
    href: "/docs/guides/visual-asset-prompt-pack",
    top: "69%",
    left: "56%",
  },
];

const artDirectionCards = [
  {
    label: "Hero posters",
    description:
      "Generate widescreen key art for homepage or section hero moments without breaking the docs tone.",
  },
  {
    label: "Share cards",
    description:
      "Build OG visuals that keep court geometry, scoreboard cues, and restrained type hierarchy intact.",
  },
  {
    label: "Texture plates",
    description:
      "Create subtle overlays, hardwood noise, and telestrator marks that support content instead of drowning it.",
  },
];

const openingSet = [
  {
    step: "01",
    title: "Read the floor",
    href: "/docs/diagrams/er-diagram",
    description: "Start with the coach's-board overview before narrowing to one surface.",
  },
  {
    step: "02",
    title: "Scout the feeds",
    href: "/docs/endpoints",
    description: "Map API families to the warehouse so each table has a source story.",
  },
  {
    step: "03",
    title: "Run a play",
    href: "/docs/guides/duckdb-queries",
    description: "Move from docs to a first working analysis with DuckDB-first patterns.",
  },
];

export default function HomePage() {
  return (
    <main className="nba-home-shell flex flex-1 flex-col">
      <section className="mx-auto w-full max-w-7xl px-4 pb-10 pt-8 sm:px-6 lg:px-8">
        <div className="nba-home-hero nba-reveal">
          <div className="grid gap-8 xl:grid-cols-[minmax(0,1.08fr)_minmax(22rem,28rem)] xl:items-start">
            <div className="space-y-6 nba-delay-1">
              <div className="flex flex-wrap gap-2">
                <Badge variant="signal">Arena Data Lab</Badge>
                <Badge variant="board">141 tables · 131 endpoints · 47 docs pages</Badge>
                <Badge variant="accent">Now with visual asset prompt packs</Badge>
              </div>

              <div className="space-y-4">
                <p className="nba-kicker">Basketball-native documentation system</p>
                <h1 className="nba-display max-w-5xl text-balance text-5xl font-semibold tracking-tight text-foreground md:text-6xl xl:text-[4.7rem]">
                  A docs site that feels like a scoreboard, a film room, and a
                  warehouse map at once.
                </h1>
                <p className="max-w-3xl text-pretty text-lg leading-8 text-muted-foreground md:text-xl">
                  nbadb turns league-wide NBA feeds into a star schema you can
                  reason about, query fast, and ship confidently. The docs now
                  lean harder into court geometry, clearer route design, richer
                  share surfaces, and authored prompt packs for generating art
                  that still feels like nbadb.
                </p>
              </div>

              <div className="flex flex-wrap gap-3">
                <Button asChild size="lg">
                  <Link href="/docs">
                    Enter the docs
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <Button asChild size="lg" variant="tint">
                  <Link href="/docs/schema">Explore the schema</Link>
                </Button>
                <Button asChild size="lg" variant="outline">
                  <Link href="/docs/guides/visual-asset-prompt-pack">
                    Build asset prompts
                    <ArrowRight className="size-4" />
                  </Link>
                </Button>
                <Button asChild size="lg" variant="ghost">
                  <a
                    href="https://www.kaggle.com/datasets/wyattowalsh/basketball"
                    target="_blank"
                    rel="noopener noreferrer"
                  >
                    Kaggle dataset
                  </a>
                </Button>
              </div>

              <div className="nba-ticker">
                {tickerItems.map((item) => (
                  <span key={item} className="nba-score-ribbon">
                    {item}
                  </span>
                ))}
              </div>

              <div className="grid gap-3 md:grid-cols-3">
                {heroSignals.map((signal) => (
                  <div
                    key={signal.title}
                    className="nba-surface rounded-[1.5rem] px-4 py-4 nba-delay-2"
                  >
                    <p className="nba-kicker">{signal.label}</p>
                    <h2 className="mt-2 text-lg font-semibold tracking-tight text-foreground">
                      {signal.title}
                    </h2>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {signal.description}
                    </p>
                  </div>
                ))}
              </div>
            </div>

            <div className="grid gap-4 nba-delay-2">
              <div className="nba-search-card rounded-4xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="nba-kicker">Coverage board</p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                      What ships on the floor
                    </h2>
                  </div>
                  <Radar className="size-7 text-primary" />
                </div>
                <div className="mt-5 grid gap-3">
                  {siteMetrics.map((metric) => (
                    <div
                      key={metric.label}
                      className="rounded-[1.25rem] border border-border/70 bg-background/75 px-4 py-3"
                    >
                      <div className="flex items-end justify-between gap-3">
                        <div>
                          <div className="nba-scoreboard-value text-2xl text-foreground">
                            {metric.value}
                          </div>
                          <div className="nba-metric-label mt-1">{metric.label}</div>
                        </div>
                        <div className="max-w-40 text-right text-xs leading-5 text-muted-foreground">
                          {metric.note}
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              </div>

              <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_14rem]">
                <div className="nba-court-board">
                  <div className="nba-court-axis" aria-hidden="true" />
                  <div className="nba-court-lane" aria-hidden="true" />
                  <div className="nba-court-rim" aria-hidden="true" />
                  <div className="nba-court-arc nba-court-arc--paint" aria-hidden="true" />
                  <div className="nba-court-arc nba-court-arc--three" aria-hidden="true" />
                  {heroRoutes.map((route) => (
                    <Link
                      key={route.href}
                      href={route.href}
                      className="nba-court-zone"
                      style={{ top: route.top, left: route.left }}
                    >
                      <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                        {route.title}
                      </div>
                      <p className="mt-1 text-xs leading-5 text-muted-foreground">
                        {route.note}
                      </p>
                    </Link>
                  ))}
                </div>

                <div className="nba-surface rounded-[1.8rem] p-4">
                  <div className="flex items-center justify-between gap-3">
                    <div>
                      <p className="nba-kicker">Share pack</p>
                      <h2 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                        Prompt-ready surfaces
                      </h2>
                    </div>
                    <LayoutGrid className="size-5 text-primary" />
                  </div>
                  <div className="mt-4 grid gap-3">
                    {artDirectionCards.map((item) => (
                      <div
                        key={item.label}
                        className="rounded-[1.2rem] border border-border/70 bg-background/72 px-3 py-3"
                      >
                        <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                          {item.label}
                        </div>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                          {item.description}
                        </p>
                      </div>
                    ))}
                  </div>
                </div>
              </div>

              <div className="nba-surface rounded-4xl p-5">
                <div className="flex items-center justify-between gap-3">
                  <div>
                    <p className="nba-kicker">Search and discovery</p>
                    <h2 className="mt-2 text-2xl font-semibold tracking-tight text-foreground">
                      Prompt the index, not your memory
                    </h2>
                  </div>
                  <Search className="size-6 text-primary" />
                </div>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  The docs shell is wired for fast retrieval. Use <kbd>⌘K</kbd>{" "}
                  or <kbd>Ctrl K</kbd> to jump directly to tables, diagrams,
                  endpoints, guide routes, and the new art-direction kit.
                </p>
                <div className="mt-4 grid gap-3">
                  {searchPrompts.map((prompt) => (
                    <div
                      key={prompt.query}
                      className="rounded-[1.25rem] border border-border/70 bg-background/75 px-4 py-3"
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">
                          {prompt.label}
                        </div>
                        <span className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                          ⌘K
                        </span>
                      </div>
                      <div className="mt-1 font-mono text-[0.8rem] text-foreground">
                        {prompt.query}
                      </div>
                      <div className="mt-1 text-xs leading-5 text-muted-foreground">
                        {prompt.description}
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-14 sm:px-6 lg:px-8 nba-reveal nba-delay-2">
        <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="nba-kicker">Entry lanes</p>
            <h2 className="nba-display text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
              Choose the role you are playing tonight
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            Analysts, operators, and explorers should not have to decode the same
            page from scratch. These routes bias toward intent first.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-3">
          {audienceLanes.map((lane, index) => {
            const Icon = audienceIcons[index];

            return (
              <Link
                key={lane.href}
                href={lane.href}
                className="nba-surface group rounded-[1.75rem] p-5 transition-transform duration-200 hover:-translate-y-0.5"
              >
                <div className="flex items-center justify-between gap-3">
                  <Badge variant="board">{lane.label}</Badge>
                  <Icon className="size-5 text-primary" />
                </div>
                <h3 className="mt-4 text-xl font-semibold tracking-tight text-foreground">
                  {lane.title}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {lane.description}
                </p>
                <div className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary">
                  Take this route
                  <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-14 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
        <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="nba-kicker">Section hubs</p>
            <h2 className="nba-display text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
              Navigate the floor by intent
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            Every major section now has a clearer role: scouting reports for
            endpoints, playbook boards for diagrams, and possession chains for
            lineage.
          </p>
        </div>
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {docsSections.map((section) => {
            const Icon = sectionIcons[section.id];

            return (
              <Link
                key={section.id}
                href={section.hubHref}
                className="nba-surface group rounded-[1.75rem] p-5 transition-transform duration-200 hover:-translate-y-0.5"
              >
                <div
                  className={`rounded-[1.35rem] border border-border/60 bg-linear-to-br p-3 ${section.toneClass}`}
                >
                  <Icon className="size-6 text-foreground" />
                </div>
                <div className="mt-4 flex items-center justify-between gap-3">
                  <Badge variant="outline">{section.eyebrow}</Badge>
                  <ArrowRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
                </div>
                <h3 className="mt-4 text-xl font-semibold tracking-tight text-foreground">
                  {section.label}
                </h3>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                  {section.blurb}
                </p>
                <div className="mt-4 grid gap-2 sm:grid-cols-2">
                  {section.stats.slice(0, 2).map((stat) => (
                    <div
                      key={stat.label}
                      className="rounded-2xl border border-border/70 bg-background/70 px-3 py-2"
                    >
                      <div className="nba-scoreboard-value text-sm text-foreground">
                        {stat.value}
                      </div>
                      <div className="nba-metric-label mt-1">{stat.label}</div>
                    </div>
                  ))}
                </div>
              </Link>
            );
          })}
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-14 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
        <div className="mb-6 flex flex-col gap-4 md:flex-row md:items-end md:justify-between">
          <div>
            <p className="nba-kicker">Asset lab</p>
            <h2 className="nba-display text-3xl font-semibold tracking-tight text-foreground md:text-4xl">
              Generate visuals that still feel like nbadb
            </h2>
          </div>
          <p className="max-w-2xl text-sm leading-6 text-muted-foreground">
            The site now carries an authored prompt pack for hero art, OG cards,
            icons, and ambient textures so new assets can match the docs system
            instead of fighting it.
          </p>
        </div>
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1.1fr)_minmax(18rem,22rem)]">
          <Link
            href="/docs/guides/visual-asset-prompt-pack"
            className="nba-surface group rounded-[1.9rem] p-6 transition-transform duration-200 hover:-translate-y-0.5"
          >
            <div className="flex flex-wrap gap-2">
              <Badge variant="signal">New guide</Badge>
              <Badge variant="accent">AI prompt pack</Badge>
            </div>
            <h2 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">
              Basketball-native prompts for hero art, share cards, icons, and
              subtle atmosphere.
            </h2>
            <p className="mt-3 max-w-3xl text-sm leading-7 text-muted-foreground">
              Use the prompt library to generate assets that respect the site
              typography, court geometry, scoreboard motifs, and restrained
              editorial tone. It includes negative prompts, ratio guidance, and
              deliverable-specific prompt templates.
            </p>
            <div className="mt-6 grid gap-3 md:grid-cols-3">
              {artDirectionCards.map((item) => (
                <div
                  key={item.label}
                  className="rounded-[1.3rem] border border-border/70 bg-background/72 px-4 py-4"
                >
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    {item.label}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {item.description}
                  </p>
                </div>
              ))}
            </div>
            <div className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary">
              Open the prompt pack
              <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
            </div>
          </Link>

          <div className="grid gap-4">
            {[
              {
                label: "OG routing",
                title: "Per-page share surfaces",
                description:
                  "The docs app now ships dedicated sitemap, robots, icon, and Open Graph routes for cleaner discovery and sharing.",
              },
              {
                label: "Art direction",
                title: "Prompt constraints included",
                description:
                  "The prompt pack includes negative prompts and style guardrails so outputs stay editorial, not generic AI wallpaper.",
              },
            ].map((card) => (
              <div key={card.title} className="nba-search-card rounded-[1.8rem] p-5">
                <p className="nba-kicker">{card.label}</p>
                <h3 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                  {card.title}
                </h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  {card.description}
                </p>
              </div>
            ))}
          </div>
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-14 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
        <div className="grid gap-4 xl:grid-cols-3">
          {featureRows.map((feature) => (
            <Link
              key={feature.title}
              href={feature.href}
              className="nba-surface group rounded-[1.75rem] p-6 transition-transform duration-200 hover:-translate-y-0.5"
            >
              <Badge variant="accent">{feature.label}</Badge>
              <h2 className="mt-4 text-2xl font-semibold tracking-tight text-foreground">
                {feature.title}
              </h2>
              <p className="mt-3 text-sm leading-7 text-muted-foreground">
                {feature.description}
              </p>
              <div className="mt-5 inline-flex items-center gap-2 text-sm font-semibold text-primary">
                Dive deeper
                <ArrowRight className="size-4 transition-transform duration-200 group-hover:translate-x-0.5" />
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section className="mx-auto w-full max-w-7xl px-4 pb-20 sm:px-6 lg:px-8 nba-reveal nba-delay-3">
        <div className="nba-surface rounded-4xl p-6 md:p-8">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_18rem]">
            <div>
              <p className="nba-kicker">Opening set</p>
              <h2 className="nba-display mt-2 text-3xl font-semibold tracking-tight text-foreground">
                Three clean starting actions
              </h2>
              <div className="mt-6 grid gap-4 md:grid-cols-3">
                {openingSet.map((item) => (
                  <Link
                    key={item.title}
                    href={item.href}
                    className="rounded-[1.4rem] border border-border/70 bg-background/75 px-4 py-4 transition-colors hover:bg-accent/35"
                  >
                    <div className="text-sm font-semibold uppercase tracking-[0.22em] text-primary">
                      {item.step}
                    </div>
                    <div className="mt-2 text-lg font-semibold text-foreground">
                      {item.title}
                    </div>
                    <p className="mt-2 text-sm leading-6 text-muted-foreground">
                      {item.description}
                    </p>
                  </Link>
                ))}
              </div>
            </div>
            <div className="flex flex-col justify-between gap-4 rounded-[1.6rem] border border-border/70 bg-background/70 p-5">
              <div>
                <p className="nba-kicker">Signal</p>
                <h3 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                  Basketball cues, documentation discipline
                </h3>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">
                  The redesign leans on court lines, scoreboard labels, and film
                  room composition while keeping navigation, search, and prose
                  legibility first. It also ships with prompt-ready asset
                  guidance so future visual layers do not drift off-brand.
                </p>
              </div>
              <Button
                asChild
                variant="outline"
                className="w-full justify-between rounded-2xl"
              >
                <Link href="/docs/guides/visual-asset-prompt-pack">
                  Open visual asset prompt pack
                  <ArrowRight className="size-4" />
                </Link>
              </Button>
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
