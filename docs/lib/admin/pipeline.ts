import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { PipelineSummary, PipelineRunStatus } from "./types";

const PIPELINE_STATUS_PATHS = [
  resolve(process.cwd(), "pipeline-status.json"),
  resolve(process.cwd(), "../pipeline-status.json"),
  resolve(process.cwd(), "lib/admin/pipeline-telemetry.generated.json"),
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
  for (const filePath of PIPELINE_STATUS_PATHS) {
    try {
      const raw = await readFile(filePath, "utf-8");
      const data = JSON.parse(raw) as Partial<PipelineSummary>;
      return {
        ...EMPTY_SUMMARY,
        ...data,
        counts: { ...EMPTY_SUMMARY.counts, ...data.counts },
        totals: { ...EMPTY_SUMMARY.totals, ...data.totals },
        runs: data.runs ?? EMPTY_SUMMARY.runs,
        daily: data.daily ?? EMPTY_SUMMARY.daily,
        slowEndpoints: data.slowEndpoints ?? EMPTY_SUMMARY.slowEndpoints,
        failureHotspots:
          data.failureHotspots ?? EMPTY_SUMMARY.failureHotspots,
        recentErrors: data.recentErrors ?? EMPTY_SUMMARY.recentErrors,
      };
    } catch {
      continue;
    }
  }

  return EMPTY_SUMMARY;
}

export function overallPipelineStatus(
  summary: PipelineSummary,
): PipelineRunStatus {
  if (!summary.lastRun) return "abandoned";
  if (summary.counts.running > 0) return "running";
  if (summary.counts.failed > 0) return "failed";
  return "done";
}
