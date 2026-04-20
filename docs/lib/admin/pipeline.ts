import { resolve } from "node:path";
import { readFirstJson } from "./files";
import type {
  PipelineSummary,
  PipelineRunStatus,
  SubsystemStatus,
} from "./types";

const PIPELINE_STATUS_PATHS = [
  resolve(
    /* turbopackIgnore: true */ process.cwd(),
    "lib",
    "admin",
    "pipeline-status.json",
  ),
  resolve(
    /* turbopackIgnore: true */ process.cwd(),
    "lib",
    "admin",
    "pipeline-telemetry.generated.json",
  ),
];

const EMPTY_SUMMARY: PipelineSummary = {
  generatedAt: null,
  lastRun: null,
  totalTables: 0,
  stagingCoverage: 0,
  runs: [],
  recentErrors: [],
  counts: { done: 0, failed: 0, running: 0, abandoned: 0 },
  windowDays: 14,
  daily: [],
  slowEndpoints: [],
  failureHotspots: [],
  totals: {
    runs: 0,
    rowsExtracted: 0,
    errorCount: 0,
    avgDurationMs: 0,
    p95DurationMs: 0,
  },
};

export async function getPipelineSummary(): Promise<PipelineSummary> {
  const data = await readFirstJson<Partial<PipelineSummary>>(
    PIPELINE_STATUS_PATHS,
  );
  if (!data) {
    return EMPTY_SUMMARY;
  }

  return {
    ...EMPTY_SUMMARY,
    ...data,
    counts: { ...EMPTY_SUMMARY.counts, ...data.counts },
    totals: { ...EMPTY_SUMMARY.totals, ...data.totals },
    runs: data.runs ?? EMPTY_SUMMARY.runs,
    daily: data.daily ?? EMPTY_SUMMARY.daily,
    slowEndpoints: data.slowEndpoints ?? EMPTY_SUMMARY.slowEndpoints,
    failureHotspots: data.failureHotspots ?? EMPTY_SUMMARY.failureHotspots,
    recentErrors: data.recentErrors ?? EMPTY_SUMMARY.recentErrors,
  };
}

export function overallPipelineStatus(
  summary: PipelineSummary,
): PipelineRunStatus {
  if (!summary.lastRun) return "abandoned";
  if (summary.counts.running > 0) return "running";
  if (summary.counts.failed > 0) return "failed";
  return "done";
}

export function pipelineToHealth(status: PipelineRunStatus): SubsystemStatus {
  if (status === "done" || status === "running") return "healthy";
  if (status === "failed") return "degraded";
  return "unknown";
}
