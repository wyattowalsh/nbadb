import type { ComponentProps, ComponentType, ReactNode } from "react";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";
import { Badge } from "@/components/ui/badge";
import {
  DistributionPlot,
  GameFlow,
  HeatmapGrid,
  LineageExplorer,
  ObservablePlot,
  PlayerCompare,
  SchemaExplorer,
  SeasonTrend,
  ShotChart,
  SqlPlayground,
} from "@/components/mdx/dynamic-charts";

type MDXComponentMap = Record<
  string,
  ComponentType<{ [key: string]: unknown }>
>;

function asMdxComponent<T extends object>(Component: ComponentType<T>) {
  return function WrappedMdxComponent(props: T) {
    return <Component {...props} />;
  };
}

function TerminalQuote({ ...props }: ComponentProps<"blockquote">) {
  return (
    <blockquote
      className="border-l-3 border-primary bg-muted px-4 py-3"
      {...props}
    />
  );
}

function SectionDivider({ label = "—" }: { label?: ReactNode }) {
  return (
    <div className="my-8 flex items-center gap-3">
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
    <div className="border border-border bg-card px-3 py-2">
      <div className="nba-metric-label">{label}</div>
      <div className="nba-scoreboard-value mt-1 text-2xl text-foreground">
        {value}
      </div>
      {note ? (
        <div className="mt-1 text-xs text-muted-foreground">{note}</div>
      ) : null}
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
    <div
      className={`nba-stat-grid grid gap-px border border-border ${columnClass} ${className ?? ""}`}
    >
      {children}
    </div>
  );
}

function NoteCard({
  title,
  label = "Note",
  children,
}: {
  title: string;
  label?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <div className="border border-border bg-card p-4">
      <Badge variant="default">{label}</Badge>
      <h3 className="mt-3 text-base font-bold tracking-tight text-foreground">
        {title}
      </h3>
      <div className="mt-2 text-sm leading-7 text-muted-foreground font-sans">
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
      className={`nba-data-columns grid gap-px border border-border md:grid-cols-2 ${className ?? ""}`}
    >
      {children}
    </div>
  );
}

function AlertCard({
  children,
  title,
  variant = "note",
}: {
  children: ReactNode;
  title?: string;
  variant?: "note" | "warning";
}) {
  const isWarning = variant === "warning";
  return (
    <aside
      className={`border border-border border-l-3 bg-muted px-4 py-3 ${isWarning ? "border-l-destructive" : "border-l-primary"}`}
    >
      <p className={`nba-kicker ${isWarning ? "text-destructive" : ""}`}>
        {title ?? (isWarning ? "Warning" : "Note")}
      </p>
      <div className="mt-2 text-sm leading-7 text-muted-foreground font-sans">
        {children}
      </div>
    </aside>
  );
}

function CommandBlock({ command, label }: { command: string; label?: string }) {
  return (
    <div className="nba-surface my-4 overflow-hidden">
      {label ? (
        <div className="border-b border-border bg-muted px-3 py-1.5">
          <span className="nba-metric-label">{label}</span>
        </div>
      ) : null}
      <pre className="overflow-x-auto px-4 py-3 font-mono text-sm leading-relaxed text-foreground">
        <code>
          <span className="select-none text-muted-foreground">$ </span>
          {command}
        </code>
      </pre>
    </div>
  );
}

function MetricRow({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={`my-4 flex flex-wrap items-center gap-0 divide-x divide-border border border-border ${className ?? ""}`}
    >
      {children}
    </div>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-baseline gap-2 px-3 py-2">
      <span className="nba-scoreboard-value text-lg text-foreground">
        {value}
      </span>
      <span className="nba-metric-label">{label}</span>
    </div>
  );
}

const mdxComponents = {
  ...defaultMdxComponents,
  blockquote: TerminalQuote,
  CourtDivider: SectionDivider,
  DataColumns,
  CommandBlock,
  InsightCard: AlertCard,
  DistributionPlot: asMdxComponent(DistributionPlot),
  GameFlow: asMdxComponent(GameFlow),
  HeatmapGrid: asMdxComponent(HeatmapGrid),
  LineageExplorer: asMdxComponent(LineageExplorer),
  Mermaid,
  Metric,
  MetricRow,
  ObservablePlot: asMdxComponent(ObservablePlot),
  PlayerCompare: asMdxComponent(PlayerCompare),
  SchemaExplorer: asMdxComponent(SchemaExplorer),
  SeasonTrend: asMdxComponent(SeasonTrend),
  ShotChart: asMdxComponent(ShotChart),
  SqlPlayground: asMdxComponent(SqlPlayground),
  WarningCard: (props: ComponentProps<typeof AlertCard>) => (
    <AlertCard variant="warning" {...props} />
  ),
  ScoutCard: NoteCard,
  StatGrid,
  StatPill,
};

/**
 * Client wrapper that renders MDX content with the full component registry.
 * Use this from server components instead of calling getMDXComponents() directly.
 */
export function MDXContent({
  Body,
}: {
  Body: ComponentType<{ components?: typeof mdxComponents }>;
}) {
  return <Body components={mdxComponents} />;
}

export function getMDXComponents(components?: MDXComponentMap) {
  return {
    ...mdxComponents,
    ...components,
  };
}
