import { readFile } from "node:fs/promises";
import { resolve } from "node:path";
import type { PipelineSummary, PipelineRunStatus } from "./types";

const PIPELINE_STATUS_PATH = resolve(process.cwd(), "../pipeline-status.json");

const EMPTY_SUMMARY: PipelineSummary = {
  lastRun: null,
  totalTables: 0,
  stagingCoverage: 0,
  runs: [],
  recentErrors: [],
  counts: { done: 0, failed: 0, running: 0, abandoned: 0 },
};

export async function getPipelineSummary(): Promise<PipelineSummary> {
  try {
    const raw = await readFile(PIPELINE_STATUS_PATH, "utf-8");
    const data = JSON.parse(raw) as PipelineSummary;
    return {
      ...EMPTY_SUMMARY,
      ...data,
      counts: { ...EMPTY_SUMMARY.counts, ...data.counts },
    };
  } catch {
    return EMPTY_SUMMARY;
  }
}

export function overallPipelineStatus(
  summary: PipelineSummary,
): PipelineRunStatus {
  if (!summary.lastRun) return "abandoned";
  if (summary.counts.running > 0) return "running";
  if (summary.counts.failed > 0) return "failed";
  return "done";
}
