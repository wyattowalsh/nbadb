import type { ComponentProps, ComponentType, ReactNode } from "react";
import defaultMdxComponents from "fumadocs-ui/mdx";
import { Mermaid } from "@/components/mdx/mermaid";
import { Badge } from "@/components/ui/badge";

type MDXComponentMap = Record<
  string,
  ComponentType<{ [key: string]: unknown }>
>;

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
      {note ? <div className="mt-1 text-xs text-muted-foreground">{note}</div> : null}
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
    <div className={`nba-stat-grid grid gap-px border border-border ${columnClass} ${className ?? ""}`}>
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
      <div className="mt-2 text-sm leading-7 text-muted-foreground" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
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

function InsightCard({
  children,
  title = "Note",
}: {
  children: ReactNode;
  className?: string;
  title?: string;
}) {
  return (
    <aside className="border border-border border-l-3 border-l-primary bg-muted px-4 py-3">
      <p className="nba-kicker">{title}</p>
      <div className="mt-2 text-sm leading-7 text-muted-foreground" style={{ fontFamily: "var(--font-sans), system-ui, sans-serif" }}>
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
    blockquote: TerminalQuote,
    CourtDivider: SectionDivider,
    DataColumns,
    InsightCard,
    Mermaid,
    ScoutCard: NoteCard,
    StatGrid,
    StatPill,
    ...components,
  };
}
