"use client";

import { useEffect, useState } from "react";
import { SparklineCard } from "@/components/admin/sparkline-card";
import { Skeleton } from "@/components/ui/skeleton";
import type { UmamiPageview } from "@/lib/admin/types";

export function OverviewSparklines() {
  const [data7d, setData7d] = useState<{ value: number }[] | null>(null);
  const [data30d, setData30d] = useState<{ value: number }[] | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [res7, res30] = await Promise.all([
          fetch("/api/admin/umami?metric=pageviews&range=7d"),
          fetch("/api/admin/umami?metric=pageviews&range=30d"),
        ]);

        if (res7.ok) {
          const pv7: UmamiPageview[] = await res7.json();
          setData7d(pv7.map((d) => ({ value: d.views })));
        }
        if (res30.ok) {
          const pv30: UmamiPageview[] = await res30.json();
          setData30d(pv30.map((d) => ({ value: d.views })));
        }
      } catch {
        // Analytics unavailable — show fallback
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) {
    return (
      <div className="grid gap-4 sm:grid-cols-2">
        <Skeleton className="h-32" />
        <Skeleton className="h-32" />
      </div>
    );
  }

  if (!data7d && !data30d) {
    return (
      <div className="rounded-2xl border border-border/70 p-6 text-center text-sm text-muted-foreground">
        Analytics not configured. Set{" "}
        <code className="rounded bg-muted px-1 py-0.5 text-xs">
          UMAMI_API_TOKEN
        </code>{" "}
        to enable traffic sparklines.
      </div>
    );
  }

  const sum7 = data7d?.reduce((s, d) => s + d.value, 0) ?? 0;
  const sum30 = data30d?.reduce((s, d) => s + d.value, 0) ?? 0;

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      {data7d && (
        <SparklineCard
          label="Pageviews (7d)"
          value={sum7.toLocaleString()}
          data={data7d}
          color="var(--primary)"
        />
      )}
      {data30d && (
        <SparklineCard
          label="Pageviews (30d)"
          value={sum30.toLocaleString()}
          data={data30d}
          color="var(--accent)"
        />
      )}
    </div>
  );
}
