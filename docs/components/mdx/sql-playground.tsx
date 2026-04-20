"use client";

import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  BarChart3,
  Copy,
  Loader2,
  Play,
  RotateCcw,
  Table2,
} from "lucide-react";
import { type ChartInference, inferChart } from "@/lib/chart-inference";

const DEFAULT_QUERY = `SELECT 42 AS answer, 'Hello from DuckDB-WASM!' AS message;`;
const QUERY_TIMEOUT_MS = 15_000;

type SqlPlaygroundExample = {
  label: string;
  sql: string;
  description?: string;
};

type ParquetTable = {
  tableName: string;
  url: string;
};

type CopyStatus = {
  tone: "default" | "destructive";
  message: string;
};

function rowsToCsv(columns: string[], rows: Record<string, unknown>[]): string {
  const escapeCell = (value: unknown) =>
    `"${String(value ?? "").replaceAll('"', '""')}"`;

  return [
    columns.map(escapeCell).join(","),
    ...rows.map((row) =>
      columns.map((column) => escapeCell(row[column])).join(","),
    ),
  ].join("\n");
}

function formatResultSummary(rowCount: number, executionTimeMs: number | null) {
  const summary =
    rowCount >= 1000
      ? "Showing first 1,000 rows"
      : `${rowCount} row${rowCount !== 1 ? "s" : ""}`;

  return executionTimeMs !== null
    ? `${summary} • ${executionTimeMs.toFixed(0)}ms`
    : summary;
}

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
  const [executionTimeMs, setExecutionTimeMs] = useState<number | null>(null);
  const [copyStatus, setCopyStatus] = useState<CopyStatus | null>(null);
  const [activeExample, setActiveExample] = useState<string | null>(
    examples?.find((example) => example.sql === initialQuery)?.label ?? null,
  );
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const initRef = useRef(false);
  const runIdRef = useRef(0);
  const copyStatusTimeoutRef = useRef<number | null>(null);
  const textareaId = useId();
  const helperTextId = useId();

  const tableNames = useMemo(() => {
    if (tables?.length) return tables.map((t) => t.tableName);
    if (tableName) return [tableName];
    return [];
  }, [tables, tableName]);
  const csv = useMemo(() => rowsToCsv(columns, rows), [columns, rows]);

  const clearResults = useCallback((nextError: string | null = null) => {
    setError(nextError);
    setColumns([]);
    setRows([]);
    setExecutionTimeMs(null);
  }, []);

  useEffect(() => {
    const textarea = textareaRef.current;
    if (!textarea) return;
    textarea.style.height = "auto";
    textarea.style.height = `${Math.min(textarea.scrollHeight, 480)}px`;
  }, [query]);

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
    const runId = ++runIdRef.current;
    clearResults();
    setLoading(true);
    setResultView("table");
    try {
      if (!ready) await initDb();
      const startedAt = performance.now();
      const { runQuery: exec } = await import("@/lib/duckdb");
      const result = await exec(query, { timeoutMs: QUERY_TIMEOUT_MS });
      if (runIdRef.current !== runId) return;
      setColumns(result.columns);
      setRows(result.rows.slice(0, 1000));
      setExecutionTimeMs(performance.now() - startedAt);
    } catch (err) {
      if (runIdRef.current !== runId) return;
      clearResults(err instanceof Error ? err.message : "Query failed");
    } finally {
      if (runIdRef.current === runId) {
        setLoading(false);
      }
    }
  }, [clearResults, query, ready, initDb]);

  const cancelQuery = useCallback(async () => {
    runIdRef.current += 1;
    const { destroyDb } = await import("@/lib/duckdb");
    await destroyDb();
    initRef.current = false;
    setReady(false);
    setLoading(false);
    setLoadProgress("");
    clearResults("Query cancelled. The in-browser DuckDB session was reset.");
  }, [clearResults]);

  const loadQueryState = useCallback(
    (nextQuery: string, nextExample: string | null) => {
      setQuery(nextQuery);
      setActiveExample(nextExample);
      clearResults();
      textareaRef.current?.focus();
    },
    [clearResults],
  );

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
    loadQueryState(example.sql, example.label);
  }, [loadQueryState]);

  const resetQuery = useCallback(() => {
    loadQueryState(
      initialQuery,
      examples?.find((example) => example.sql === initialQuery)?.label ?? null,
    );
  }, [examples, initialQuery, loadQueryState]);

  const setTimedCopyStatus = useCallback((status: CopyStatus) => {
    if (copyStatusTimeoutRef.current) {
      window.clearTimeout(copyStatusTimeoutRef.current);
    }

    setCopyStatus(status);
    copyStatusTimeoutRef.current = window.setTimeout(() => {
      setCopyStatus(null);
      copyStatusTimeoutRef.current = null;
    }, 2400);
  }, []);

  const copyText = useCallback(
    async (text: string, label: string) => {
      try {
        await navigator.clipboard.writeText(text);
        setTimedCopyStatus({
          tone: "default",
          message: `Copied ${label} to clipboard.`,
        });
      } catch {
        setTimedCopyStatus({
          tone: "destructive",
          message: `Couldn't copy ${label}. Your browser blocked clipboard access.`,
        });
      }
    },
    [setTimedCopyStatus],
  );

  useEffect(() => {
    return () => {
      if (copyStatusTimeoutRef.current) {
        window.clearTimeout(copyStatusTimeoutRef.current);
      }
      runIdRef.current += 1;
      initRef.current = false;
      void import("@/lib/duckdb")
        .then(({ destroyDb }) => destroyDb())
        .catch((error: unknown) => {
          console.error("[SQL Playground] Cleanup failed", error);
        });
    };
  }, []);

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
        <label htmlFor={textareaId} className="sr-only">
          SQL query editor
        </label>
        <textarea
          id={textareaId}
          ref={textareaRef}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setActiveExample(null);
          }}
          onKeyDown={handleKeyDown}
          rows={10}
          spellCheck={false}
          aria-describedby={helperTextId}
          className="w-full resize-y bg-card px-4 py-3 font-mono text-sm text-foreground outline-none placeholder:text-muted-foreground focus:ring-2 focus:ring-inset focus:ring-primary/40 transition-shadow duration-150"
          placeholder="Enter SQL query..."
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
            onClick={cancelQuery}
            disabled={!loading}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-background disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => {
              void copyText(query, "SQL");
            }}
            disabled={loading}
            className="inline-flex items-center gap-1.5 rounded border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground transition-colors hover:bg-background disabled:opacity-50"
          >
            <Copy className="size-3.5" />
            Copy SQL
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
          <span id={helperTextId} className="text-xs text-muted-foreground">
            Cmd/Ctrl+Enter to run • {QUERY_TIMEOUT_MS / 1000}s timeout
          </span>
          {copyStatus ? (
            <span
              role="status"
              aria-live="polite"
              className={`text-xs ${
                copyStatus.tone === "destructive"
                  ? "text-destructive"
                  : "text-muted-foreground"
              }`}
            >
              {copyStatus.message}
            </span>
          ) : null}
          <span className="text-xs text-muted-foreground max-sm:hidden">
            {tableNames.length > 0
              ? `Tables: ${tableNames.join(", ")}`
              : "Self-contained SQL sandbox in this tab"}
          </span>
        </div>
      </div>

      {/* Error */}
      {error ? (
        <div
          role="alert"
          className="border-t border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive"
        >
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
            onCopyCsv={() => {
              void copyText(csv, "CSV");
            }}
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
              <div className="border-t border-border bg-muted px-4 py-2 text-xs text-muted-foreground">
                {formatResultSummary(rows.length, executionTimeMs)}
              </div>
            </div>
          )}
        </div>
      ) : !error && !loading ? (
        <div className="border-t border-border bg-muted/40 px-4 py-4 text-sm text-muted-foreground">
          Pick an example or write your own SQL, then press Run to initialize
          DuckDB-WASM in this tab.
        </div>
      ) : null}
    </div>
  );
}

function ResultToolbar({
  resultView,
  setResultView,
  columns,
  rows,
  onCopyCsv,
}: {
  resultView: "table" | "chart";
  setResultView: (v: "table" | "chart") => void;
  columns: string[];
  rows: Record<string, unknown>[];
  onCopyCsv: () => void;
}) {
  const inference = useMemo(() => inferChart(columns, rows), [columns, rows]);
  const canChart = inference.type !== "none";

  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-b border-border bg-muted px-3 py-1.5">
      <div className="flex items-center gap-1">
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
      </div>
      <button
        type="button"
        onClick={onCopyCsv}
        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-background hover:text-foreground"
      >
        <Copy className="size-3" />
        CSV
      </button>
    </div>
  );
}

function ChartView({
  columns,
  rows,
}: {
  columns: string[];
  rows: Record<string, unknown>[];
}) {
  const [PlotComponent, setPlotComponent] = useState<React.ComponentType<{
    columns: string[];
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

  return <PlotComponent columns={columns} rows={rows} inference={inference} />;
}
