import { Command, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getGeneratedPageFrame } from "@/lib/site-config";

export function DocsGeneratedEntrySurface({ slug }: { slug?: string[] }) {
  const frame = getGeneratedPageFrame(slug);

  if (!frame) {
    return null;
  }

  return (
    <section className="mt-8 grid gap-4 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="border border-border bg-card p-4 md:p-5">
        <div className="flex flex-wrap gap-2">
          <Badge variant="primary">Generated page</Badge>
          <Badge variant="default">Command-owned</Badge>
          <Badge variant="muted">{frame.generatorLabel}</Badge>
        </div>

        <div className="mt-4 space-y-3">
          <p className="nba-kicker">{frame.eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {frame.title}
          </h2>
          <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
            {frame.description}
          </p>
        </div>

        <div className="mt-5 grid gap-3 md:grid-cols-3">
          {frame.stats.map((stat) => (
            <div
              key={stat.label}
              className="border border-border bg-muted px-3 py-2"
            >
              <div className="nba-metric-label">{stat.label}</div>
              <div className="nba-scoreboard-value mt-1 text-xl text-foreground">
                {stat.value}
              </div>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {stat.note}
              </p>
            </div>
          ))}
        </div>

        <div className="mt-6">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-muted-foreground">
            <Search className="size-3.5 text-primary" />
            How to work this page
          </div>
          <div className="mt-3 rounded-2xl border border-border bg-muted/60 p-3 md:p-4">
            <div className="grid gap-3 md:grid-cols-3">
              {frame.steps.map((step, index) => (
                <div
                  key={step.title}
                  className="rounded-xl border border-border/80 bg-background/80 px-3 py-3"
                >
                  <div className="flex items-start gap-3">
                    <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-primary/25 bg-primary/12 text-xs font-semibold text-primary">
                      {index + 1}
                    </span>
                    <div>
                      <h3 className="text-sm font-semibold uppercase tracking-[0.16em] text-foreground">
                        {step.title}
                      </h3>
                      <p className="mt-2 text-sm leading-6 text-muted-foreground">
                        {step.description}
                      </p>
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      <aside className="border border-border bg-card p-4 md:p-5">
        <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.22em] text-foreground">
          <Command className="size-3.5 text-primary" />
          Generator boundary
        </div>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {frame.ownershipNote}
        </p>
        <div className="mt-4 border border-border bg-muted p-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Regenerate with
          </div>
          <code className="mt-2 block overflow-x-auto font-mono text-[0.78rem] leading-6 text-foreground">
            {frame.regenerateCommand}
          </code>
        </div>
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          If the content drifts from code, refresh the generator instead of
          hand-editing the artifact.
        </p>
      </aside>
    </section>
  );
}
