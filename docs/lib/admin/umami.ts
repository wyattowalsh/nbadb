import type {
  DateRange,
  UmamiPageview,
  UmamiReferrer,
  UmamiStats,
  UmamiTopPage,
} from "./types";

const UMAMI_API_URL = process.env.UMAMI_API_URL ?? "https://api.umami.is/v1";
const UMAMI_API_TOKEN = process.env.UMAMI_API_TOKEN ?? "";
const UMAMI_WEBSITE_ID = process.env.NEXT_PUBLIC_UMAMI_WEBSITE_ID ?? "";

function rangeToMs(range: DateRange): { startAt: number; endAt: number } {
  const now = Date.now();
  const durations: Record<DateRange, number> = {
    "24h": 24 * 60 * 60 * 1000,
    "7d": 7 * 24 * 60 * 60 * 1000,
    "30d": 30 * 24 * 60 * 60 * 1000,
    "90d": 90 * 24 * 60 * 60 * 1000,
  };
  return { startAt: now - durations[range], endAt: now };
}

async function umamiGet<T>(
  path: string,
  params?: Record<string, string>,
): Promise<T | null> {
  if (!UMAMI_API_TOKEN || !UMAMI_WEBSITE_ID) return null;

  const url = new URL(`${UMAMI_API_URL}/websites/${UMAMI_WEBSITE_ID}${path}`);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }

  try {
    const res = await fetch(url.toString(), {
      headers: { Authorization: `Bearer ${UMAMI_API_TOKEN}` },
      next: { revalidate: 300 },
    });
    if (!res.ok) return null;
    return res.json() as Promise<T>;
  } catch {
    return null;
  }
}

export async function getStats(
  range: DateRange = "7d",
): Promise<UmamiStats | null> {
  const { startAt, endAt } = rangeToMs(range);
  return umamiGet<UmamiStats>("/stats", {
    startAt: String(startAt),
    endAt: String(endAt),
  });
}

export async function getPageviews(
  range: DateRange = "7d",
): Promise<UmamiPageview[] | null> {
  const { startAt, endAt } = rangeToMs(range);
  const unit = range === "24h" ? "hour" : "day";
  const data = await umamiGet<{ pageviews: UmamiPageview[] }>("/pageviews", {
    startAt: String(startAt),
    endAt: String(endAt),
    unit,
  });
  return data?.pageviews ?? null;
}

export async function getTopPages(
  range: DateRange = "30d",
): Promise<UmamiTopPage[] | null> {
  const { startAt, endAt } = rangeToMs(range);
  return umamiGet<UmamiTopPage[]>("/metrics", {
    startAt: String(startAt),
    endAt: String(endAt),
    type: "url",
  });
}

export async function getTopReferrers(
  range: DateRange = "30d",
): Promise<UmamiReferrer[] | null> {
  const { startAt, endAt } = rangeToMs(range);
  return umamiGet<UmamiReferrer[]>("/metrics", {
    startAt: String(startAt),
    endAt: String(endAt),
    type: "referrer",
  });
}
