"use client";

import React, {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BarChart3,
  ClipboardCopy,
  Loader2,
  Play,
  RotateCcw,
  Table2,
} from "lucide-react";
import { type ChartInference, inferChart } from "@/lib/chart-inference";

const DEFAULT_QUERY = `SELECT 42 AS answer, 'Hello from DuckDB-WASM!' AS message;`;

type SqlPlaygroundExample = {
  label: string;
  sql: string;
  description?: string;
};

type ParquetTable = {
  tableName: string;
  url: string;
};

export function SqlPlayground({
  defaultQuery,
  parquetUrl,
  tableName,
  tables,
  examples,
}: {
  /** Pre-filled SQL query */
  defaultQuery?: string;
  /** URL to a Parquet file to load as a table */
  parquetUrl?: string;
  /** Table name for the loaded Parquet file */
  tableName?: string;
  /** Multiple Parquet tables to register */
  tables?: ParquetTable[];
  /** One-click example queries for the playground */
  examples?: SqlPlaygroundExample[];
}) {
  const initialQuery = useMemo(
    () => defaultQuery ?? examples?.[0]?.sql ?? DEFAULT_QUERY,
    [defaultQuery, examples],
  );
  const [query, setQuery] = useState(initialQuery);
  const [columns, setColumns] = useState<string[]>([]);
  const [rows, setRows] = useState<Record<string, unknown>[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [ready, setReady] = useState(false);
  const [loadProgress, setLoadProgress] = useState("");
  const [resultView, setResultView] = useState<"table" | "chart">("table");
  const [activeExample, setActiveExample] = useState<string | null>(
    examples?.find((example) => example.sql === initialQuery)?.label ?? null,
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const initRef = useRef(false);

  const tableNames = useMemo(() => {
    if (tables?.length) return tables.map((t) => t.tableName);
    if (tableName) return [tableName];
    return [];
  }, [tables, tableName]);

  const initDb = useCallback(async () => {
    if (initRef.current) return;
    initRef.current = true;
    setLoading(true);
    try {
      const duckdbLib = await import("@/lib/duckdb");
      await duckdbLib.getDb();
      if (tables?.length) {
        await duckdbLib.registerMultipleParquet(
          tables,
          (loaded, total, name) => {
            if (loaded < total)
              setLoadProgress(`Loading ${name} (${loaded + 1}/${total})...`);
            else setLoadProgress("");
          },
        );
      } else if (parquetUrl && tableName) {
        await duckdbLib.registerParquet(tableName, parquetUrl);
      }
      setReady(true);
    } catch (err) {
      initRef.current = false;
      setError(
        err instanceof Error ? err.message : "Failed to initialize DuckDB",
      );
    } finally {
      setLoading(false);
      setLoadProgress("");
    }
  }, [parquetUrl, tableName, tables]);

  const runQuery = useCallback(async () => {
    setError(null);
    setLoading(true);
    setResultView("table");
    try {
      if (!ready) await initDb();
      const { runQuery: exec } = await import("@/lib/duckdb");
      const result = await exec(query);
      setColumns(result.columns);
      setRows(result.rows.slice(0, 1000));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Query failed");
      setColumns([]);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, [query, ready, initDb]);

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter") {
        e.preventDefault();
        runQuery();
      }
    },
    [runQuery],
  );

  const loadExample = useCallback((example: SqlPlaygroundExample) => {
    setQuery(example.sql);
    setActiveExample(example.label);
    setError(null);
    setColumns([]);
    setRows([]);
    textareaRef.current?.focus();
  }, []);

  const resetQuery = useCallback(() => {
    setQuery(initialQuery);
    setActiveExample(
      examples?.find((example) => example.sql === initialQuery)?.label ?? null,
    );
    setError(null);
    setColumns([]);
    setRows([]);
    textareaRef.current?.focus();
  }, [examples, initialQuery]);

  return (
    <div className="nba-viz-shell">
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">SQL Playground</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Powered by DuckDB-WASM — runs entirely in your browser.
            {tableName ? ` Table: ${tableName}` : ""}
          </p>
        </div>
        <div className="nba-viz-status max-sm:hidden">
          {loadProgress ||
            (ready ? "Engine loaded" : "Click Run to initialize")}
        </div>
      </div>

      {/* Query editor */}
      <div className="border-t border-border">
        <textarea
          ref={textareaRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveExample(null);
          }}
          onKeyDown={handleKeyDown}
          rows={10}
          spellCheck={false}
          className="w-full resize-y bg-card px-4 py-3 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-inset focus:ring-primary/40 transition-shadow duration-150"
          placeholder="Enter SQL query..."
          aria-label="SQL query editor"
        />
        {examples && examples.length > 0 ? (
          <div className="flex flex-wrap items-center gap-2 border-t border-border bg-card px-4 py-3">
            <span className="text-[0.7rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              Load example
            </span>
            {examples.map((example) => (
              <button
                key={example.label}
                type="button"
                onClick={() => loadExample(example)}
                title={example.description}
                className={
                  activeExample === example.label
                    ? "rounded-full border border-primary/30 bg-primary/10 px-3 py-1 text-xs font-medium text-primary"
                    : "rounded-full border border-border bg-muted px-3 py-1 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/25 hover:text-foreground"
                }
              >
                {example.label}
              </button>
            ))}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2 border-t border-border bg-muted px-4 py-2">
          <button
            type="button"
            onClick={runQuery}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-colors hover:bg-primary/90 disabled:opacity-50"
          >
            {loading ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <Play className="size-3.5" />
            )}
            {loading ? "Running..." : "Run"}
          </button>
          <button
            type="button"
            onClick={resetQuery}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-background disabled:opacity-50"
          >
            <RotateCcw className="size-3.5" />
            Reset
          </button>
          <span className="text-xs text-muted-foreground">
            {"\u2318"}+Enter to run
          </span>
          <span className="text-xs text-muted-foreground max-sm:hidden">
            {tableNames.length > 0
              ? `Tables: ${tableNames.join(", ")}`
              : "Self-contained SQL sandbox in this tab"}
          </span>
        </div>
      </div>

      {/* Error */}
      {error ? (
        <div className="border-t border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
          {error}
        </div>
      ) : null}

      {/* Results */}
      {columns.length > 0 ? (
        <div className="border-t border-border">
          <ResultToolbar
            resultView={resultView}
            setResultView={setResultView}
            columns={columns}
            rows={rows}
          />
          {resultView === "chart" ? (
            <ChartView columns={columns} rows={rows} />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-border bg-muted">
                    {columns.map((col) => (
                      <th
                        key={col}
                        className="px-3 py-2 text-left font-medium text-foreground"
                      >
                        {col}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rows.map((row, i) => (
                    <tr
                      key={i}
                      className="border-b border-border last:border-b-0 hover:bg-muted/50"
                    >
                      {columns.map((col) => (
                        <td
                          key={col}
                          className="px-3 py-1.5 font-mono text-xs text-muted-foreground"
                        >
                          {String(row[col] ?? "")}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
              {rows.length >= 1000 ? (
                <div className="border-t border-border bg-muted px-4 py-2 text-xs text-muted-foreground">
                  Showing first 1,000 rows
                </div>
              ) : (
                <div className="border-t border-border bg-muted px-4 py-2 text-xs text-muted-foreground">
                  {rows.length} row{rows.length !== 1 ? "s" : ""}
                </div>
              )}
            </div>
          )}
        </div>
      ) : !error && !loading ? (
        <div className="border-t border-border bg-muted/40 px-4 py-4 text-sm text-muted-foreground">
          <p>
            Pick an example or write your own SQL, then press Run to initialize
            DuckDB-WASM in this tab.
          </p>
          {!ready ? (
            <p className="mt-1 text-xs text-muted-foreground/70">
              First run downloads ~4 MB DuckDB engine (cached for future runs).
            </p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function toCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const escape = (v: unknown) => {
    const s = String(v ?? "");
    return s.includes(",") || s.includes('"') || s.includes("\n")
      ? `"${s.replace(/"/g, '""')}"`
      : s;
  };
  const header = columns.map(escape).join(",");
  const body = rows.map((row) =>
    columns.map((col) => escape(row[col])).join(","),
  );
  return [header, ...body].join("\n");
}

function ResultToolbar({
  resultView,
  setResultView,
  columns,
  rows,
}: {
  resultView: "table" | "chart";
  setResultView: (v: "table" | "chart") => void;
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  const inference = useMemo(() => inferChart(columns, rows), [columns, rows]);
  const canChart = inference.type !== "none";
  const [copied, setCopied] = useState(false);

  const copyAsCsv = useCallback(() => {
    const csv = toCsv(columns, rows);
    navigator.clipboard.writeText(csv).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    });
  }, [columns, rows]);

  return (
    <div className="flex items-center gap-1 border-b border-border bg-muted px-3 py-1">
      <button
        type="button"
        onClick={() => setResultView("table")}
        className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
          resultView === "table"
            ? "bg-background text-foreground shadow-sm"
            : "text-muted-foreground hover:text-foreground"
        }`}
      >
        <Table2 className="size-3" />
        Table
      </button>
      {canChart ? (
        <button
          type="button"
          onClick={() => setResultView("chart")}
          className={`inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium transition-colors ${
            resultView === "chart"
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground"
          }`}
        >
          <BarChart3 className="size-3" />
          {inference.label}
        </button>
      ) : null}
      <span className="mx-1 h-4 w-px bg-border" />
      <button
        type="button"
        onClick={copyAsCsv}
        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground"
        title="Copy results as CSV to clipboard"
      >
        <ClipboardCopy className="size-3" />
        {copied ? "Copied!" : "Copy CSV"}
      </button>
    </div>
  );
}

class ChartErrorBoundary extends React.Component<
  { children: React.ReactNode },
  { hasError: boolean }
> {
  constructor(props: { children: React.ReactNode }) {
    super(props);
    this.state = { hasError: false };
  }

  static getDerivedStateFromError(): { hasError: boolean } {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="flex items-center justify-center py-12 text-sm text-destructive">
          Chart rendering failed. Try a different query or switch to table view.
        </div>
      );
    }
    return this.props.children;
  }
}

function ChartView({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  const [PlotComponent, setPlotComponent] = useState<React.ComponentType<{
    rows: Record<string, unknown>[];
    inference: ChartInference;
  }> | null>(null);

  const inference = useMemo(() => inferChart(columns, rows), [columns, rows]);

  useEffect(() => {
    import("@/components/mdx/plot-from-result").then((m) => {
      setPlotComponent(() => m.PlotFromResult);
    });
  }, []);

  if (!PlotComponent) {
    return (
      <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
        <Loader2 className="mr-2 size-4 animate-spin" />
        Loading chart...
      </div>
    );
  }

  return (
    <ChartErrorBoundary>
      <PlotComponent rows={rows} inference={inference} />
    </ChartErrorBoundary>
  );
}
