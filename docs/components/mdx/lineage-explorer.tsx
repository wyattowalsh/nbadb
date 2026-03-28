"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

/* ── Types ───────────────────────────────────────────── */

type LineageEntry = {
  sql_lineage?: {
    source_tables?: string[];
    columns?: string[];
    class_name?: string;
  };
};

type LineageData = Record<string, LineageEntry>;

type LayerKey =
  | "stg"
  | "dim"
  | "fact"
  | "bridge"
  | "agg"
  | "analytics"
  | "other";

type DepthOption = 1 | 2 | typeof Infinity;

/* ── Layer config ────────────────────────────────────── */

const LAYERS: {
  key: LayerKey;
  prefix: string;
  label: string;
  color: string;
  border: string;
}[] = [
  { key: "stg", prefix: "stg_", label: "stg", color: "#fff3e0", border: "#ef6c00" },
  { key: "dim", prefix: "dim_", label: "dim", color: "#e8f5e9", border: "#2e7d32" },
  { key: "fact", prefix: "fact_", label: "fact", color: "#fce4ec", border: "#c62828" },
  { key: "bridge", prefix: "bridge_", label: "bridge", color: "#e3f2fd", border: "#1565c0" },
  { key: "agg", prefix: "agg_", label: "agg", color: "#f3e5f5", border: "#6a1b9a" },
  { key: "analytics", prefix: "analytics_", label: "analytics", color: "#e0f7fa", border: "#00838f" },
];

function classifyTable(name: string): LayerKey {
  for (const layer of LAYERS) {
    if (name.startsWith(layer.prefix)) return layer.key;
  }
  return "other";
}

function layerStyle(layer: LayerKey) {
  const match = LAYERS.find((l) => l.key === layer);
  return match
    ? { bg: match.color, border: match.border }
    : { bg: "#f5f5f5", border: "#9e9e9e" };
}

/* ── Graph helpers ───────────────────────────────────── */

function buildAdjacency(data: LineageData) {
  const forward = new Map<string, string[]>(); // source -> consumers
  const reverse = new Map<string, string[]>(); // consumer -> sources

  for (const [table, entry] of Object.entries(data)) {
    const sources = entry.sql_lineage?.source_tables ?? [];
    for (const src of sources) {
      if (!reverse.has(table)) reverse.set(table, []);
      reverse.get(table)!.push(src);

      if (!forward.has(src)) forward.set(src, []);
      forward.get(src)!.push(table);
    }
  }

  return { forward, reverse };
}

function bfs(
  start: string,
  adjacency: Map<string, string[]>,
  maxDepth: number,
): Map<string, number> {
  const visited = new Map<string, number>();
  const queue: [string, number][] = [[start, 0]];

  while (queue.length > 0) {
    const [node, depth] = queue.shift()!;
    if (node === start && depth > 0) continue;
    if (depth > maxDepth) continue;
    if (visited.has(node)) continue;

    if (node !== start) visited.set(node, depth);

    const neighbors = adjacency.get(node) ?? [];
    for (const n of neighbors) {
      if (!visited.has(n)) {
        queue.push([n, depth + 1]);
      }
    }
  }

  return visited;
}

/* ── Sub-components ──────────────────────────────────── */

function LayerPill({
  layerKey,
  label,
  color,
  border,
  active,
  onClick,
}: {
  layerKey: LayerKey;
  label: string;
  color: string;
  border: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-opacity"
      style={{
        borderColor: border,
        background: active ? color : "transparent",
        opacity: active ? 1 : 0.4,
      }}
      aria-pressed={active}
      aria-label={`${active ? "Hide" : "Show"} ${layerKey} tables`}
    >
      <span
        className="inline-block size-2 rounded-full"
        style={{ background: border }}
      />
      {label}
    </button>
  );
}

function TableItem({
  name,
  depth,
  selected,
  onClick,
}: {
  name: string;
  depth?: number;
  selected: boolean;
  onClick: () => void;
}) {
  const layer = classifyTable(name);
  const style = layerStyle(layer);

  return (
    <button
      onClick={onClick}
      className="flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left text-sm transition-colors hover:bg-muted/50"
      style={{
        borderLeftWidth: 3,
        borderLeftColor: style.border,
        background: selected ? style.bg : undefined,
      }}
    >
      {depth != null && depth > 1 && (
        <span
          className="inline-flex size-5 shrink-0 items-center justify-center rounded-full bg-muted text-[10px] font-bold text-muted-foreground"
          title={`${depth} hops away`}
        >
          {depth}
        </span>
      )}
      <span className="truncate font-mono text-xs">{name}</span>
    </button>
  );
}

function ColumnList({ columns }: { columns: string[] }) {
  const [expanded, setExpanded] = useState(false);
  const limit = 20;
  const shown = expanded ? columns : columns.slice(0, limit);
  const hasMore = columns.length > limit;

  return (
    <div className="mt-3">
      <p className="nba-metric-label mb-1">
        Columns ({columns.length})
      </p>
      <div className="flex flex-wrap gap-1">
        {shown.map((col) => (
          <span
            key={col}
            className="inline-block rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground"
          >
            {col}
          </span>
        ))}
      </div>
      {hasMore && (
        <button
          onClick={() => setExpanded(!expanded)}
          className="mt-1 text-xs text-primary hover:underline"
        >
          {expanded ? "Show less" : `+ ${columns.length - limit} more`}
        </button>
      )}
    </div>
  );
}

/* ── Main component ──────────────────────────────────── */

export function LineageExplorer({ data }: { data: LineageData }) {
  const allTables = useMemo(() => Object.keys(data).sort(), [data]);

  const { forward, reverse } = useMemo(() => buildAdjacency(data), [data]);

  /* State */
  const [selectedTable, setSelectedTable] = useState<string>(() => {
    const firstDim = allTables.find((t) => t.startsWith("dim_"));
    return firstDim ?? allTables[0] ?? "";
  });
  const [searchQuery, setSearchQuery] = useState("");
  const [enabledLayers, setEnabledLayers] = useState<Set<LayerKey>>(
    () => new Set(LAYERS.map((l) => l.key).concat("other" as LayerKey)),
  );
  const [maxDepth, setMaxDepth] = useState<DepthOption>(1);

  /* Debounced search */
  const [debouncedQuery, setDebouncedQuery] = useState(searchQuery);
  const timerRef = useRef<ReturnType<typeof setTimeout>>(undefined);

  useEffect(() => {
    timerRef.current = setTimeout(() => setDebouncedQuery(searchQuery), 150);
    return () => clearTimeout(timerRef.current);
  }, [searchQuery]);

  /* Filtered search results */
  const searchResults = useMemo(() => {
    const q = debouncedQuery.toLowerCase().trim();
    return allTables.filter((t) => {
      const layer = classifyTable(t);
      if (!enabledLayers.has(layer)) return false;
      if (q && !t.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [allTables, debouncedQuery, enabledLayers]);

  /* Upstream / downstream */
  const upstream = useMemo(
    () => (selectedTable ? bfs(selectedTable, reverse, maxDepth) : new Map<string, number>()),
    [selectedTable, reverse, maxDepth],
  );

  const downstream = useMemo(
    () => (selectedTable ? bfs(selectedTable, forward, maxDepth) : new Map<string, number>()),
    [selectedTable, forward, maxDepth],
  );

  const sortedUpstream = useMemo(
    () =>
      [...upstream.entries()]
        .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]))
        .filter(([t]) => enabledLayers.has(classifyTable(t))),
    [upstream, enabledLayers],
  );

  const sortedDownstream = useMemo(
    () =>
      [...downstream.entries()]
        .sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0]))
        .filter(([t]) => enabledLayers.has(classifyTable(t))),
    [downstream, enabledLayers],
  );

  /* Selected table detail */
  const entry = selectedTable ? data[selectedTable] : undefined;
  const layer = selectedTable ? classifyTable(selectedTable) : "other";
  const style = layerStyle(layer);

  const toggleLayer = useCallback((key: LayerKey) => {
    setEnabledLayers((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  }, []);

  const depthOptions: { label: string; value: DepthOption }[] = [
    { label: "1 hop", value: 1 },
    { label: "2 hops", value: 2 },
    { label: "All", value: Infinity },
  ];

  return (
    <div className="nba-viz-shell">
      {/* Toolbar */}
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">Lineage Explorer</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Click a table to inspect its upstream sources and downstream consumers.
          </p>
        </div>
        <div className="nba-viz-status max-sm:hidden">
          {allTables.length} tables
        </div>
      </div>

      {/* Controls row */}
      <div className="mb-3 flex flex-wrap items-center gap-2">
        <input
          type="text"
          value={searchQuery}
          onChange={(e) => setSearchQuery(e.target.value)}
          placeholder="Search tables..."
          className="h-8 w-48 rounded border border-border bg-background px-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-1 focus:ring-primary"
          aria-label="Search tables"
        />
        <span className="mx-1 h-4 w-px bg-border" />
        {LAYERS.map((l) => (
          <LayerPill
            key={l.key}
            layerKey={l.key}
            label={l.label}
            color={l.color}
            border={l.border}
            active={enabledLayers.has(l.key)}
            onClick={() => toggleLayer(l.key)}
          />
        ))}
        <span className="mx-1 h-4 w-px bg-border" />
        <div className="inline-flex overflow-hidden rounded border border-border text-xs">
          {depthOptions.map((opt) => (
            <button
              key={opt.label}
              onClick={() => setMaxDepth(opt.value)}
              className="px-2.5 py-1 transition-colors"
              style={{
                background: maxDepth === opt.value ? "var(--primary)" : "transparent",
                color: maxDepth === opt.value ? "var(--primary-foreground)" : "inherit",
              }}
              aria-pressed={maxDepth === opt.value}
            >
              {opt.label}
            </button>
          ))}
        </div>
      </div>

      {/* Three-panel layout */}
      <div className="grid gap-px overflow-hidden rounded border border-border bg-border md:grid-cols-[1fr_1.4fr_1fr]">
        {/* Upstream panel */}
        <div className="flex flex-col bg-background">
          <div className="flex items-center justify-between border-b border-border bg-muted px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Upstream
            </span>
            <span className="inline-flex size-5 items-center justify-center rounded-full bg-background text-[10px] font-bold text-muted-foreground">
              {sortedUpstream.length}
            </span>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {sortedUpstream.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                No upstream dependencies
              </p>
            ) : (
              sortedUpstream.map(([t, d]) => (
                <TableItem
                  key={t}
                  name={t}
                  depth={d}
                  selected={false}
                  onClick={() => setSelectedTable(t)}
                />
              ))
            )}
          </div>
        </div>

        {/* Center detail panel */}
        <div className="flex flex-col bg-background">
          <div
            className="flex items-center justify-between border-b px-3 py-2"
            style={{ borderBottomColor: style.border, borderBottomWidth: 2 }}
          >
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Selected
            </span>
            <span
              className="rounded-full px-2 py-0.5 text-[10px] font-bold uppercase"
              style={{ background: style.bg, color: style.border }}
            >
              {layer}
            </span>
          </div>
          <div className="max-h-96 overflow-y-auto px-4 py-3">
            {selectedTable ? (
              <>
                <p className="font-mono text-sm font-bold text-foreground">
                  {selectedTable}
                </p>
                {entry?.sql_lineage?.class_name && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    Class: <code className="rounded bg-muted px-1 py-0.5 font-mono text-[11px]">{entry.sql_lineage.class_name}</code>
                  </p>
                )}
                <div className="mt-3 flex gap-4 text-xs text-muted-foreground">
                  <span>
                    <strong className="text-foreground">{upstream.size}</strong> upstream
                  </span>
                  <span>
                    <strong className="text-foreground">{downstream.size}</strong> downstream
                  </span>
                </div>
                {entry?.sql_lineage?.columns && entry.sql_lineage.columns.length > 0 && (
                  <ColumnList columns={entry.sql_lineage.columns} />
                )}
              </>
            ) : (
              <p className="py-4 text-center text-xs text-muted-foreground">
                Select a table to view details
              </p>
            )}
          </div>

          {/* Search results below detail */}
          <div className="border-t border-border">
            <div className="flex items-center justify-between bg-muted px-3 py-2">
              <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                All Tables
              </span>
              <span className="inline-flex size-5 items-center justify-center rounded-full bg-background text-[10px] font-bold text-muted-foreground">
                {searchResults.length}
              </span>
            </div>
            <div className="max-h-48 overflow-y-auto">
              {searchResults.map((t) => (
                <TableItem
                  key={t}
                  name={t}
                  selected={t === selectedTable}
                  onClick={() => setSelectedTable(t)}
                />
              ))}
            </div>
          </div>
        </div>

        {/* Downstream panel */}
        <div className="flex flex-col bg-background">
          <div className="flex items-center justify-between border-b border-border bg-muted px-3 py-2">
            <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
              Downstream
            </span>
            <span className="inline-flex size-5 items-center justify-center rounded-full bg-background text-[10px] font-bold text-muted-foreground">
              {sortedDownstream.length}
            </span>
          </div>
          <div className="max-h-96 overflow-y-auto">
            {sortedDownstream.length === 0 ? (
              <p className="px-3 py-4 text-center text-xs text-muted-foreground">
                No downstream consumers
              </p>
            ) : (
              sortedDownstream.map(([t, d]) => (
                <TableItem
                  key={t}
                  name={t}
                  depth={d}
                  selected={false}
                  onClick={() => setSelectedTable(t)}
                />
              ))
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
