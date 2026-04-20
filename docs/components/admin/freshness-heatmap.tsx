"use client";

import { cn } from "@/lib/utils";

type FreshnessCell = {
  label: string;
  layer: string;
  hoursSinceSuccess: number | null;
};

function cellColor(hours: number | null): string {
  if (hours === null) return "bg-muted-foreground/20";
  if (hours < 24) return "bg-emerald-500/70";
  if (hours < 72) return "bg-amber-500/60";
  if (hours < 168) return "bg-orange-500/50";
  return "bg-red-500/50";
}

function cellTooltip(cell: FreshnessCell): string {
  if (cell.hoursSinceSuccess === null)
    return `${cell.label} (${cell.layer}) — never succeeded`;
  const days = Math.floor(cell.hoursSinceSuccess / 24);
  const hours = Math.round(cell.hoursSinceSuccess % 24);
  const age = days > 0 ? `${days}d ${hours}h` : `${hours}h`;
  return `${cell.label} (${cell.layer}) — ${age} ago`;
}

type FreshnessHeatmapProps = {
  data: FreshnessCell[];
  className?: string;
};

export function FreshnessHeatmap({ data, className }: FreshnessHeatmapProps) {
  const grouped = new Map<string, FreshnessCell[]>();
  for (const cell of data) {
    const existing = grouped.get(cell.layer);
    if (existing) {
      existing.push(cell);
    } else {
      grouped.set(cell.layer, [cell]);
    }
  }

  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-emerald-500/70" />{" "}
          &lt;24h
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-amber-500/60" />{" "}
          24-72h
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-orange-500/50" />{" "}
          3-7d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-red-500/50" />{" "}
          &gt;7d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-muted-foreground/20" />{" "}
          never
        </span>
      </div>

      {[...grouped.entries()].map(([layer, cells]) => (
        <div key={layer}>
          <p className="mb-1.5 text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {layer}
          </p>
          <div className="flex flex-wrap gap-1">
            {cells.map((cell) => (
              <div
                key={`${cell.layer}-${cell.label}`}
                className={cn(
                  "size-6 rounded-sm transition-opacity hover:opacity-80",
                  cellColor(cell.hoursSinceSuccess),
                )}
                title={cellTooltip(cell)}
              >
                <span className="sr-only">{cell.label}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
