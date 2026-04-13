"use client";

import { ChevronDown, ChevronRight } from "lucide-react";
import { type ReactNode, useEffect, useId, useMemo, useState } from "react";
import { Badge } from "@/components/ui/badge";
import {
  getGeneratedSourceGroupKey,
  getGeneratedStarGroupKey,
  getGeneratedStarGroupLabel,
  groupGeneratedItems,
  humanizeGeneratedIdentifier,
  sortGeneratedSourceGroups,
  sortGeneratedStarGroups,
} from "@/lib/generated-grouping";

interface FilterableTableProps<T extends { table_name: string }> {
  data: T[];
  label: string;
  renderSummary: (entry: T) => ReactNode;
  renderEntry: (entry: T) => ReactNode;
}

type SurfaceKind = "raw" | "staging" | "star" | "other";

type EntryGroup<T> = {
  key: string;
  label: string;
  description: string;
  entries: T[];
};

function detectSurface<T extends { table_name: string }>(
  data: T[],
): SurfaceKind {
  if (data.some((entry) => entry.table_name.startsWith("raw_"))) {
    return "raw";
  }

  if (
    data.some(
      (entry) =>
        entry.table_name.startsWith("stg_") ||
        entry.table_name.startsWith("staging_"),
    )
  ) {
    return "staging";
  }

  if (
    data.some((entry) =>
      ["dim_", "fact_", "bridge_", "agg_", "analytics_"].some((prefix) =>
        entry.table_name.startsWith(prefix),
      ),
    )
  ) {
    return "star";
  }

  return "other";
}

function buildGroupMeta(key: string, surface: SurfaceKind) {
  if (surface === "star") {
    return {
      label: getGeneratedStarGroupLabel(key),
      description:
        {
          dim: "Identity, calendar, venue, and reference surfaces.",
          fact: "Analyst-facing event and measurement tables.",
          bridge: "Connector tables for many-to-many join lanes.",
          agg: "Pre-aggregated outputs for repeated reporting paths.",
          analytics: "Convenience surfaces for fast notebook and dashboard reads.",
        }[key] ?? "Generated warehouse surfaces grouped by family.",
    };
  }

  const familyLabel = humanizeGeneratedIdentifier(key);
  const laneLabel =
    surface === "raw"
      ? "source family"
      : surface === "staging"
        ? "cleanup lane"
        : "table family";

  return {
    label: familyLabel,
    description: `Open this ${laneLabel} when you only need the matching generated block, not the full board.`,
  };
}

function groupEntries<T extends { table_name: string }>(
  entries: T[],
  surface: SurfaceKind,
): EntryGroup<T>[] {
  const grouped = groupGeneratedItems(entries, (entry) => {
    const key =
      surface === "star"
        ? getGeneratedStarGroupKey(entry.table_name)
        : getGeneratedSourceGroupKey(entry.table_name);
    const meta = buildGroupMeta(key, surface);

    return {
      key,
      label: meta.label,
      description: meta.description,
    };
  }).map((group) => ({
    ...group,
    entries: group.items.sort((left, right) =>
      left.table_name.localeCompare(right.table_name),
    ),
  }));

  return surface === "star"
    ? sortGeneratedStarGroups(grouped)
    : sortGeneratedSourceGroups(grouped);
}

function FilterableTable<T extends { table_name: string }>({
  data,
  label,
  renderSummary,
  renderEntry,
}: FilterableTableProps<T>) {
  const [filter, setFilter] = useState("");
  const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>(
    {},
  );
  const [expandedEntries, setExpandedEntries] = useState<
    Record<string, boolean>
  >({});
  const [activeHash, setActiveHash] = useState("");
  const countId = useId();
  const surface = useMemo(() => detectSurface(data), [data]);
  const normalizedFilter = filter.trim().toLowerCase();

  const filtered = useMemo(
    () =>
      normalizedFilter
        ? data.filter((entry) =>
            entry.table_name.toLowerCase().includes(normalizedFilter),
          )
        : data,
    [data, normalizedFilter],
  );

  const groups = useMemo(
    () => groupEntries(filtered, surface),
    [filtered, surface],
  );

  useEffect(() => {
    const syncHash = () => {
      setActiveHash(decodeURIComponent(window.location.hash.replace(/^#/, "")));
    };

    syncHash();
    window.addEventListener("hashchange", syncHash);
    return () => window.removeEventListener("hashchange", syncHash);
  }, []);

  const handlePreviewOpen = (groupKey: string, tableName: string) => {
    setExpandedGroups((previous) => ({ ...previous, [groupKey]: true }));
    setExpandedEntries((previous) => ({ ...previous, [tableName]: true }));
  };

  return (
    <div>
      <div className="mb-6 rounded-2xl border border-border bg-card p-4 md:p-5">
        <div className="flex flex-col gap-3 xl:flex-row xl:items-start xl:justify-between">
          <div>
            <p className="nba-kicker">Progressive scan</p>
            <h2 className="mt-2 text-lg font-semibold tracking-tight text-foreground md:text-xl">
              Open only the generated family and contract you need
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
              The full board is still here, but it now stays grouped until you
              open a family or filter to the exact table you need.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Badge variant="primary">
              {filtered.length} {label}
            </Badge>
            <Badge variant="default">{groups.length} families</Badge>
            <Badge variant="muted">
              {normalizedFilter ? "Filtered view" : "Grouped view"}
            </Badge>
          </div>
        </div>

        <div className="mt-4 flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
          <input
            type="search"
            placeholder={`Filter ${data.length} ${label}…`}
            aria-label={`Filter ${data.length} ${label}`}
            aria-describedby={countId}
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            className="w-full rounded-[var(--radius-md)] border border-border bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/60 md:max-w-sm"
          />
          <span
            id={countId}
            className="text-xs leading-5 text-muted-foreground"
            aria-live="polite"
          >
            {filtered.length} of {data.length} visible • expand a family to
            render the detailed contract table.
          </span>
        </div>
      </div>

      {groups.length === 0 ? (
        <div className="rounded-2xl border border-dashed border-border bg-muted/50 px-4 py-6 text-sm text-muted-foreground">
          No {label} match <code>{filter}</code>.
        </div>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => {
            const isExpanded =
              normalizedFilter.length > 0 ||
              Boolean(expandedGroups[group.key]) ||
              group.entries.some((entry) => entry.table_name === activeHash);

            return (
              <section
                key={group.key}
                className="overflow-hidden rounded-2xl border border-border bg-card"
              >
                <button
                  type="button"
                  onClick={() =>
                    setExpandedGroups((previous) => ({
                      ...previous,
                      [group.key]: !isExpanded,
                    }))
                  }
                  className="flex w-full items-start justify-between gap-4 px-4 py-4 text-left transition-colors hover:bg-muted/50 md:px-5"
                  aria-expanded={isExpanded}
                >
                  <div>
                    <div className="flex flex-wrap items-center gap-2">
                      <Badge variant="outline">{group.label}</Badge>
                      <span className="text-xs font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        {group.entries.length} {label}
                      </span>
                    </div>
                    <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground">
                      {group.description}
                    </p>
                  </div>
                  <span className="mt-1 inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
                    {isExpanded ? (
                      <ChevronDown className="size-4" />
                    ) : (
                      <ChevronRight className="size-4" />
                    )}
                  </span>
                </button>

                {!isExpanded ? (
                  <div className="border-t border-border px-4 py-4 md:px-5">
                    <div className="flex flex-wrap gap-2">
                      {group.entries.slice(0, 5).map((entry) => (
                        <a
                          key={entry.table_name}
                          href={`#${entry.table_name}`}
                          onClick={() =>
                            handlePreviewOpen(group.key, entry.table_name)
                          }
                          className="inline-flex items-center rounded-full border border-border bg-muted px-2.5 py-1 text-xs font-semibold text-foreground transition-colors hover:border-primary/35 hover:text-primary"
                        >
                          <code>{entry.table_name}</code>
                        </a>
                      ))}
                      {group.entries.length > 5 ? (
                        <span className="inline-flex items-center rounded-full border border-dashed border-border px-2.5 py-1 text-xs text-muted-foreground">
                          +{group.entries.length - 5} more
                        </span>
                      ) : null}
                    </div>
                  </div>
                ) : null}

                {isExpanded ? (
                  <div className="border-t border-border">
                    {group.entries.map((entry) => {
                      const isEntryExpanded =
                        Boolean(expandedEntries[entry.table_name]) ||
                        entry.table_name === activeHash;

                      return (
                        <article
                          key={entry.table_name}
                          id={entry.table_name}
                          className="scroll-mt-24 border-b border-border last:border-b-0"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              setExpandedEntries((previous) => ({
                                ...previous,
                                [entry.table_name]: !isEntryExpanded,
                              }))
                            }
                            className="flex w-full items-start justify-between gap-4 px-4 py-4 text-left transition-colors hover:bg-muted/40 md:px-5"
                            aria-expanded={isEntryExpanded}
                          >
                            <div>
                              <h3 className="font-mono text-sm font-semibold text-foreground md:text-base">
                                {entry.table_name}
                              </h3>
                              <div className="mt-2 flex flex-wrap gap-x-4 gap-y-2 text-xs leading-5 text-muted-foreground">
                                {renderSummary(entry)}
                              </div>
                            </div>
                            <span className="mt-1 inline-flex size-8 shrink-0 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
                              {isEntryExpanded ? (
                                <ChevronDown className="size-4" />
                              ) : (
                                <ChevronRight className="size-4" />
                              )}
                            </span>
                          </button>

                          {isEntryExpanded ? (
                            <div className="px-4 pb-5 md:px-5">
                              {renderEntry(entry)}
                            </div>
                          ) : null}
                        </article>
                      );
                    })}
                  </div>
                ) : null}
              </section>
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  constraints: string;
  description: string;
}

export interface SchemaEntry {
  table_name: string;
  class_name: string;
  coerce: boolean;
  strict: boolean;
  columns: SchemaColumn[];
}

export interface DictionaryField {
  name: string;
  type: string;
  nullable: boolean;
  description: string;
  source: string;
  fk_ref: string;
}

export interface DictionaryEntry {
  table_name: string;
  fields: DictionaryField[];
}

const TH_CLASS =
  "px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground";

const TR_CLASS =
  "border-b border-border/50 transition-colors duration-150 even:bg-muted hover:bg-[color-mix(in_oklch,var(--primary)_6%,transparent)]";

function SchemaEntryDetail({ entry }: { entry: SchemaEntry }) {
  return (
    <div className="mt-1 overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">
          Schema columns for {entry.table_name}
        </caption>
        <thead>
          <tr className="border-b">
            <th scope="col" className={TH_CLASS}>
              Column
            </th>
            <th scope="col" className={TH_CLASS}>
              Type
            </th>
            <th scope="col" className={TH_CLASS}>
              Nullable
            </th>
            <th scope="col" className={TH_CLASS}>
              Constraints
            </th>
            <th scope="col" className={TH_CLASS}>
              Description
            </th>
          </tr>
        </thead>
        <tbody>
          {entry.columns.map((column) => (
            <tr key={column.name} className={TR_CLASS}>
              <td className="px-2 py-1">
                <code>{column.name}</code>
              </td>
              <td className="px-2 py-1">
                <code>{column.type}</code>
              </td>
              <td className="px-2 py-1">{column.nullable ? "Yes" : "No"}</td>
              <td className="px-2 py-1">{column.constraints}</td>
              <td className="px-2 py-1">{column.description}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function SchemaReferenceTable({ data }: { data: SchemaEntry[] }) {
  return (
    <FilterableTable
      data={data}
      label="schemas"
      renderSummary={(entry) => (
        <>
          <span>{entry.columns.length} columns</span>
          <span>
            Class: <code>{entry.class_name}</code>
          </span>
          <span>Coerce: {String(entry.coerce)}</span>
          <span>Strict: {String(entry.strict)}</span>
        </>
      )}
      renderEntry={(entry) => <SchemaEntryDetail entry={entry} />}
    />
  );
}

function DictionaryEntryDetail({ entry }: { entry: DictionaryEntry }) {
  return (
    <div className="mt-1 overflow-x-auto">
      <table className="w-full text-sm">
        <caption className="sr-only">
          Field definitions for {entry.table_name}
        </caption>
        <thead>
          <tr className="border-b">
            <th scope="col" className={TH_CLASS}>
              Column
            </th>
            <th scope="col" className={TH_CLASS}>
              Type
            </th>
            <th scope="col" className={TH_CLASS}>
              Nullable
            </th>
            <th scope="col" className={TH_CLASS}>
              Description
            </th>
            <th scope="col" className={TH_CLASS}>
              Source
            </th>
          </tr>
        </thead>
        <tbody>
          {entry.fields.map((field) => (
            <tr key={field.name} className={TR_CLASS}>
              <td className="px-2 py-1">
                <code>{field.name}</code>
              </td>
              <td className="px-2 py-1">
                <code>{field.type}</code>
              </td>
              <td className="px-2 py-1">{field.nullable ? "Yes" : "No"}</td>
              <td className="px-2 py-1">
                {field.description}
                {field.fk_ref ? ` (FK → ${field.fk_ref})` : ""}
              </td>
              <td className="px-2 py-1">
                <code>{field.source}</code>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function DataDictionaryTable({ data }: { data: DictionaryEntry[] }) {
  return (
    <FilterableTable
      data={data}
      label="tables"
      renderSummary={(entry) => (
        <>
          <span>{entry.fields.length} fields</span>
          <span>
            {entry.fields.filter((field) => field.fk_ref).length} foreign-key
            hints
          </span>
        </>
      )}
      renderEntry={(entry) => <DictionaryEntryDetail entry={entry} />}
    />
  );
}
