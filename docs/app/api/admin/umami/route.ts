import { type NextRequest, NextResponse } from "next/server";
import {
  getStats,
  getPageviews,
  getTopPages,
  getTopReferrers,
} from "@/lib/admin/umami";
import type { DateRange } from "@/lib/admin/types";

export const revalidate = 300;

const VALID_METRICS = ["stats", "pageviews", "pages", "referrers"] as const;
const VALID_RANGES: DateRange[] = ["24h", "7d", "30d", "90d"];

export async function GET(request: NextRequest) {
  const { searchParams } = request.nextUrl;
  const metric = searchParams.get("metric") ?? "stats";
  const range = (searchParams.get("range") ?? "7d") as DateRange;

  if (!VALID_METRICS.includes(metric as (typeof VALID_METRICS)[number])) {
    return NextResponse.json(
      { error: `Invalid metric. Use: ${VALID_METRICS.join(", ")}` },
      { status: 400 },
    );
  }

  if (!VALID_RANGES.includes(range)) {
    return NextResponse.json(
      { error: `Invalid range. Use: ${VALID_RANGES.join(", ")}` },
      { status: 400 },
    );
  }

  let data: unknown = null;

  switch (metric) {
    case "stats":
      data = await getStats(range);
      break;
    case "pageviews":
      data = await getPageviews(range);
      break;
    case "pages":
      data = await getTopPages(range);
      break;
    case "referrers":
      data = await getTopReferrers(range);
      break;
  }

  if (data === null) {
    return NextResponse.json(
      { error: "Analytics not configured or unavailable" },
      { status: 503 },
    );
  }

  return NextResponse.json(data);
}
