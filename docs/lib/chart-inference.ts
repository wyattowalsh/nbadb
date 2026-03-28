export type ChartType =
  | "bar"
  | "line"
  | "scatter"
  | "grouped-bar"
  | "multi-line"
  | "none";

export interface ChartInference {
  type: ChartType;
  xColumn: string;
  yColumns: string[];
  /** Human-readable label, e.g. "Bar chart" or "Line chart" */
  label: string;
}

type ColumnKind = "categorical" | "temporal" | "quantitative";

const TEMPORAL_NAME_PATTERNS =
  /(?:^|_)(date|year|season|month|quarter|week)(?:$|_)/i;

const DATE_VALUE_PATTERN =
  /^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?$/;

/** Sample up to 20 rows, classify columns, pick a chart type. */
export function inferChart(
  columns: string[],
  rows: Record<string, unknown>[],
): ChartInference {
  const none: ChartInference = { type: "none", xColumn: "", yColumns: [], label: "" };

  if (rows.length < 2 || columns.length < 2) return none;

  const sample = rows.slice(0, 20);
  const kinds = new Map<string, ColumnKind>();

  for (const col of columns) {
    kinds.set(col, classifyColumn(col, sample));
  }

  const temporal = columns.filter((c) => kinds.get(c) === "temporal");
  const categorical = columns.filter((c) => kinds.get(c) === "categorical");
  const quantitative = columns.filter((c) => kinds.get(c) === "quantitative");

  // --- Apply rules (temporal preferred over categorical for x-axis) ---

  // 1 temporal + 2+ quantitative → multi-line
  if (temporal.length >= 1 && quantitative.length >= 2) {
    return {
      type: "multi-line",
      xColumn: temporal[0],
      yColumns: quantitative,
      label: "Multi-line chart",
    };
  }

  // 1 temporal + 1 quantitative → line
  if (temporal.length >= 1 && quantitative.length === 1) {
    return {
      type: "line",
      xColumn: temporal[0],
      yColumns: [quantitative[0]],
      label: "Line chart",
    };
  }

  // 1 categorical + 2+ quantitative → grouped-bar
  if (categorical.length >= 1 && quantitative.length >= 2) {
    return {
      type: "grouped-bar",
      xColumn: categorical[0],
      yColumns: quantitative,
      label: "Grouped bars",
    };
  }

  // 1 categorical + 1 quantitative → bar
  if (categorical.length >= 1 && quantitative.length === 1) {
    return {
      type: "bar",
      xColumn: categorical[0],
      yColumns: [quantitative[0]],
      label: "Bar chart",
    };
  }

  // 2 quantitative (no categorical / temporal) → scatter
  if (quantitative.length >= 2 && categorical.length === 0 && temporal.length === 0) {
    return {
      type: "scatter",
      xColumn: quantitative[0],
      yColumns: [quantitative[1]],
      label: "Scatter plot",
    };
  }

  return none;
}

// ---------------------------------------------------------------------------
// Column classification helpers
// ---------------------------------------------------------------------------

function classifyColumn(
  name: string,
  sample: Record<string, unknown>[],
): ColumnKind {
  // Check temporal first — column-name heuristic or value pattern
  if (TEMPORAL_NAME_PATTERNS.test(name)) return "temporal";

  const values = sample
    .map((r) => r[name])
    .filter((v) => v != null && v !== "");

  if (values.length === 0) return "categorical";

  // If every non-null value matches a date/datetime pattern → temporal
  if (values.every((v) => typeof v === "string" && DATE_VALUE_PATTERN.test(v))) {
    return "temporal";
  }

  // Numeric check
  const numericValues = values.filter((v) => typeof v === "number" || isFiniteNumber(v));

  if (numericValues.length === values.length) {
    // All numeric — categorical if < 15 distinct, otherwise quantitative
    const distinct = new Set(numericValues.map(Number));
    // Also treat integers-only with few distinct values as categorical
    const allIntegers = numericValues.every((v) => Number.isInteger(Number(v)));
    if (allIntegers && distinct.size < 15) return "categorical";
    return distinct.size < 15 ? "categorical" : "quantitative";
  }

  // String values → categorical
  return "categorical";
}

function isFiniteNumber(v: unknown): boolean {
  if (typeof v === "number") return Number.isFinite(v);
  if (typeof v === "string") {
    const n = Number(v);
    return v.trim() !== "" && Number.isFinite(n);
  }
  return false;
}
