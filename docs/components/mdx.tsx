import type { ComponentProps, ComponentType, ReactNode } from "react";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

type MDXComponentMap = Record<
  string,
  ComponentType<{ [key: string]: unknown }>
>;

function CourtQuote({ className, ...props }: ComponentProps<"blockquote">) {
  return (
    <blockquote
      className={cn(
        "rounded-3xl border border-border/70 bg-secondary/18 shadow-[inset_0_1px_0_color-mix(in_oklab,var(--foreground)_5%,transparent)]",
        className,
      )}
      {...props}
    />
  );
}

function CourtDivider({ label = "Split action" }: { label?: ReactNode }) {
  return (
    <div className="my-10 flex items-center gap-4">
      <span className="h-px flex-1 bg-border" />
      <Badge variant="muted">{label}</Badge>
      <span className="h-px flex-1 bg-border" />
    </div>
  );
}

function StatPill({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string;
}) {
  return (
    <div className="nba-surface rounded-[1.35rem] px-4 py-3">
      <div className="nba-metric-label">{label}</div>
      <div className="nba-scoreboard-value mt-1 text-2xl text-foreground">
        {value}
      </div>
      {note ? <div className="mt-1 text-sm text-muted-foreground">{note}</div> : null}
    </div>
  );
}

function StatGrid({
  children,
  className,
  columns = 3,
}: {
  children: ReactNode;
  className?: string;
  columns?: 2 | 3 | 4;
}) {
  const columnClass = {
    2: "md:grid-cols-2",
    3: "md:grid-cols-3",
    4: "md:grid-cols-4",
  }[columns];

  return (
    <div className={cn("nba-stat-grid grid gap-4", columnClass, className)}>
      {children}
    </div>
  );
}

function ScoutCard({
  title,
  label = "Analyst note",
  className,
  children,
}: {
  title: string;
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className={cn("nba-surface rounded-[1.6rem] p-5", className)}>
      <Badge variant="board">{label}</Badge>
      <h3 className="mt-4 text-xl font-semibold tracking-tight text-foreground">
        {title}
      </h3>
      <div className="mt-3 text-sm leading-7 text-muted-foreground">
        {children}
      </div>
    </div>
  );
}

function DataColumns({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "nba-data-columns grid gap-4 md:grid-cols-2 xl:gap-6",
        className,
      )}
    >
      {children}
    </div>
  );
}

function InsightCard({
  children,
  className,
  title = "Field note",
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <aside className={cn("nba-analyst-note rounded-[1.5rem] px-5 py-4", className)}>
      <p className="nba-kicker">{title}</p>
      <div className="mt-3 text-sm leading-7 text-muted-foreground">
        {children}
      </div>
    </aside>
  );
}

export function getMDXComponents(
  components?: MDXComponentMap,
) {
  return {
    ...defaultMdxComponents,
    blockquote: CourtQuote,
    CourtDivider,
    DataColumns,
    InsightCard,
    Mermaid,
    ScoutCard,
    StatGrid,
    StatPill,
    ...components,
  };
}
