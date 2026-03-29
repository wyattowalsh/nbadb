"use client";

import { useCallback, useMemo, useRef, useState } from "react";
import { Link2, Search } from "lucide-react";

/* ── Types ────────────────────────────────────────────── */

type SchemaColumn = { name: string; type: string; key: string };
type SchemaRelationship = {
  from_col: string;
  to_table: string;
  to_col: string;
};
type SchemaTable = {
  family: string;
  columns: SchemaColumn[];
  relationships: SchemaRelationship[];
};
type SchemaData = { tables: Record<string, SchemaTable> };

/* ── Family styling ───────────────────────────────────── */

const FAMILIES = ["dim", "fact", "bridge", "agg", "analytics"] as const;
type Family = (typeof FAMILIES)[number];

const FAMILY_COLORS: Record<
  Family,
  { border: string; bg: string; text: string }
> = {
  dim: {
    border: "border-green-500",
    bg: "bg-green-500/10",
    text: "text-green-700 dark:text-green-400",
  },
  fact: {
    border: "border-pink-500",
    bg: "bg-pink-500/10",
    text: "text-pink-700 dark:text-pink-400",
  },
  bridge: {
    border: "border-blue-500",
    bg: "bg-blue-500/10",
    text: "text-blue-700 dark:text-blue-400",
  },
  agg: {
    border: "border-purple-500",
    bg: "bg-purple-500/10",
    text: "text-purple-700 dark:text-purple-400",
  },
  analytics: {
    border: "border-cyan-500",
    bg: "bg-cyan-500/10",
    text: "text-cyan-700 dark:text-cyan-400",
  },
};

function familyColor(family: string) {
  return FAMILY_COLORS[family as Family] ?? FAMILY_COLORS.fact;
}

/* ── Component ────────────────────────────────────────── */

export function SchemaExplorer({ data }: { data: SchemaData }) {
  const [search, setSearch] = useState("");
  const [activeFilters, setActiveFilters] = useState<Set<string>>(new Set());
  const [selectedTable, setSelectedTable] = useState<string>(() => {
    const keys = Object.keys(data.tables).sort();
    return keys[0] ?? "";
  });
  const debounceRef = useRef<ReturnType<typeof setTimeout>>(undefined);
  const [debouncedSearch, setDebouncedSearch] = useState("");

  const handleSearch = useCallback((value: string) => {
    setSearch(value);
    clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => setDebouncedSearch(value), 200);
  }, []);

  const toggleFilter = useCallback((family: string) => {
    setActiveFilters((prev) => {
      const next = new Set(prev);
      if (next.has(family)) next.delete(family);
      else next.add(family);
      return next;
    });
  }, []);

  /* filtered + grouped table names */
  const grouped = useMemo(() => {
    const lowerSearch = debouncedSearch.toLowerCase();
    const entries = Object.entries(data.tables)
      .filter(([name, table]) => {
        if (lowerSearch && !name.includes(lowerSearch)) return false;
        if (activeFilters.size > 0 && !activeFilters.has(table.family))
          return false;
        return true;
      })
      .sort(([a], [b]) => a.localeCompare(b));

    const groups: Record<string, string[]> = {};
    for (const [name, table] of entries) {
      const fam = table.family;
      (groups[fam] ??= []).push(name);
    }
    return groups;
  }, [data.tables, debouncedSearch, activeFilters]);

  const totalVisible = Object.values(grouped).reduce((n, g) => n + g.length, 0);
  const detail = selectedTable ? data.tables[selectedTable] : null;

  return (
    <div className="nba-viz-shell">
      {/* toolbar */}
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">Schema Explorer</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Browse star-schema tables, columns, and foreign-key relationships.
          </p>
        </div>
        <div className="nba-viz-status max-sm:hidden">
          {totalVisible} tables
        </div>
      </div>

      {/* search + filter pills */}
      <div className="flex flex-wrap items-center gap-2 mb-3">
        <div className="relative flex-1 min-w-[180px]">
          <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 size-3.5 text-muted-foreground pointer-events-none" />
          <input
            type="text"
            placeholder="Filter tables..."
            value={search}
            onChange={(e) => handleSearch(e.target.value)}
            className="w-full rounded border border-border bg-background pl-8 pr-3 py-1.5 text-sm placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-ring"
          />
        </div>
        {FAMILIES.map((f) => {
          const c = familyColor(f);
          const active = activeFilters.has(f);
          return (
            <button
              key={f}
              onClick={() => toggleFilter(f)}
              className={`rounded-full border px-2.5 py-0.5 text-xs font-semibold transition-colors ${
                active
                  ? `${c.border} ${c.bg} ${c.text}`
                  : "border-border text-muted-foreground hover:border-foreground/30"
              }`}
            >
              {f}
            </button>
          );
        })}
      </div>

      {/* main two-column layout */}
      <div className="grid grid-cols-[minmax(180px,1fr)_2.5fr] border border-border rounded overflow-hidden min-h-[420px] max-sm:grid-cols-1">
        {/* left: table list */}
        <div className="overflow-y-auto border-r border-border max-h-[560px] max-sm:max-h-[240px] max-sm:border-r-0 max-sm:border-b">
          {Object.keys(grouped).length === 0 && (
            <p className="p-4 text-xs text-muted-foreground">
              No tables match.
            </p>
          )}
          {FAMILIES.filter((f) => f in grouped).map((family) => {
            const c = familyColor(family);
            return (
              <div key={family}>
                <div
                  className={`sticky top-0 z-10 border-b border-border px-3 py-1.5 text-[0.65rem] font-bold uppercase tracking-widest ${c.bg} ${c.text}`}
                >
                  {family}
                </div>
                {grouped[family]!.map((name) => (
                  <button
                    key={name}
                    onClick={() => setSelectedTable(name)}
                    className={`block w-full text-left px-3 py-1.5 text-xs truncate transition-colors ${
                      name === selectedTable
                        ? "bg-accent text-accent-foreground font-medium"
                        : "hover:bg-muted/60 text-foreground"
                    }`}
                  >
                    {name}
                  </button>
                ))}
              </div>
            );
          })}
        </div>

        {/* right: detail panel */}
        <div className="overflow-y-auto max-h-[560px] p-4">
          {detail ? (
            <TableDetail
              name={selectedTable}
              table={detail}
              onNavigate={setSelectedTable}
              allTables={data.tables}
            />
          ) : (
            <p className="text-sm text-muted-foreground">Select a table.</p>
          )}
        </div>
      </div>
    </div>
  );
}

/* ── Detail panel ─────────────────────────────────────── */

function TableDetail({
  name,
  table,
  onNavigate,
  allTables,
}: {
  name: string;
  table: SchemaTable;
  onNavigate: (t: string) => void;
  allTables: Record<string, SchemaTable>;
}) {
  const c = familyColor(table.family);

  return (
    <div className="space-y-5">
      {/* header */}
      <div className="flex items-center gap-2">
        <span
          className={`inline-block rounded-full border px-2 py-0.5 text-[0.6rem] font-bold uppercase tracking-wider ${c.border} ${c.bg} ${c.text}`}
        >
          {table.family}
        </span>
        <h3 className="text-base font-semibold tracking-tight">{name}</h3>
      </div>

      {/* columns table */}
      <div>
        <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          Columns ({table.columns.length})
        </h4>
        <div className="overflow-x-auto rounded border border-border">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border bg-muted/40">
                <th className="px-3 py-1.5 text-left font-semibold">Name</th>
                <th className="px-3 py-1.5 text-left font-semibold">Type</th>
                <th className="px-3 py-1.5 text-left font-semibold">Key</th>
              </tr>
            </thead>
            <tbody>
              {table.columns.map((col) => (
                <tr
                  key={col.name}
                  className="border-b border-border last:border-0"
                >
                  <td className="px-3 py-1.5 font-mono">{col.name}</td>
                  <td className="px-3 py-1.5 text-muted-foreground">
                    {col.type}
                  </td>
                  <td className="px-3 py-1.5">
                    <KeyBadge keyType={col.key} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>

      {/* relationships */}
      {table.relationships.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Relationships ({table.relationships.length})
          </h4>
          <ul className="space-y-1">
            {table.relationships.map((rel) => {
              const targetExists = rel.to_table in allTables;
              return (
                <li
                  key={`${rel.from_col}-${rel.to_table}`}
                  className="flex items-center gap-1.5 text-xs"
                >
                  <span className="font-mono">{rel.from_col}</span>
                  <span className="text-muted-foreground">&#8594;</span>
                  {targetExists ? (
                    <button
                      onClick={() => onNavigate(rel.to_table)}
                      className="inline-flex items-center gap-1 font-mono text-primary hover:underline"
                    >
                      <Link2 className="size-3" />
                      {rel.to_table}.{rel.to_col}
                    </button>
                  ) : (
                    <span className="font-mono text-muted-foreground">
                      {rel.to_table}.{rel.to_col}
                    </span>
                  )}
                </li>
              );
            })}
          </ul>
        </div>
      )}
    </div>
  );
}

/* ── Key badge ────────────────────────────────────────── */

function KeyBadge({ keyType }: { keyType: string }) {
  if (!keyType) return null;
  const isPK = keyType === "PK";
  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded-full px-1.5 py-px text-[0.6rem] font-bold uppercase tracking-wider ${
        isPK
          ? "bg-amber-500/15 text-amber-700 dark:text-amber-400 border border-amber-500/30"
          : "bg-blue-500/15 text-blue-700 dark:text-blue-400 border border-blue-500/30"
      }`}
    >
      {!isPK && <Link2 className="size-2.5" />}
      {keyType}
    </span>
  );
}
