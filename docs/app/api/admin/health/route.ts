import { NextResponse } from "next/server";
import { getContentPages } from "@/lib/admin/content-audit";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";
import type { HealthCheck, SubsystemStatus } from "@/lib/admin/types";

export const revalidate = 300;

function pipelineToHealth(status: string): SubsystemStatus {
  if (status === "done") return "healthy";
  if (status === "running") return "healthy";
  if (status === "failed") return "degraded";
  return "unknown";
}

export async function GET() {
  const [pages, pipeline] = await Promise.all([
    getContentPages(),
    getPipelineSummary(),
  ]);

  const pipelineStatus = overallPipelineStatus(pipeline);

  const contentStatus: SubsystemStatus =
    pages.length > 0 ? "healthy" : "degraded";

  const subsystems: HealthCheck["subsystems"] = {
    build: {
      status: "healthy",
      detail: `${pages.length} pages indexed`,
    },
    search: {
      status: "healthy",
      detail: "Orama search active",
    },
    pipeline: {
      status: pipelineToHealth(pipelineStatus),
      detail: pipeline.lastRun
        ? `Last run: ${pipeline.lastRun}`
        : "No pipeline data available",
    },
    content: {
      status: contentStatus,
      detail: `${pages.length} pages, ${pages.filter((p) => !p.description).length} missing descriptions`,
    },
  };

  const statuses = Object.values(subsystems).map((s) => s.status);
  const overall: SubsystemStatus = statuses.includes("down")
    ? "down"
    : statuses.includes("degraded")
      ? "degraded"
      : statuses.every((s) => s === "healthy")
        ? "healthy"
        : "unknown";

  const health: HealthCheck = {
    overall,
    subsystems,
    pageCount: pages.length,
    lastBuild: null,
  };

  return NextResponse.json(health);
}
