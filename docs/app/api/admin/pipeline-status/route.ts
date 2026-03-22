import { NextResponse } from "next/server";
import {
  getPipelineSummary,
  overallPipelineStatus,
} from "@/lib/admin/pipeline";

export const revalidate = 300;

export async function GET() {
  const summary = await getPipelineSummary();
  const status = overallPipelineStatus(summary);
  return NextResponse.json({ ...summary, overallStatus: status });
}
