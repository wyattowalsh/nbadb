import { cn } from "@/lib/utils";

type FreshnessItem = {
  slug: string;
  title: string;
  section: string;
  daysOld: number;
};

function ageColor(days: number): string {
  if (days < 14) return "bg-primary/70";
  if (days < 30) return "bg-primary/40";
  if (days < 60) return "bg-accent/50";
  if (days < 90) return "bg-muted-foreground/30";
  return "bg-destructive/50";
}

type ContentFreshnessProps = {
  data: FreshnessItem[];
  className?: string;
};

export function ContentFreshness({ data, className }: ContentFreshnessProps) {
  return (
    <div className={cn("space-y-4", className)}>
      <div className="flex items-center gap-4 text-xs text-muted-foreground">
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-primary/70" />{" "}
          &lt;14d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-primary/40" />{" "}
          14-30d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-accent/50" />{" "}
          30-60d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-muted-foreground/30" />{" "}
          60-90d
        </span>
        <span className="flex items-center gap-1.5">
          <span className="inline-block size-3 rounded-sm bg-destructive/50" />{" "}
          &gt;90d
        </span>
      </div>
      <div className="flex flex-wrap gap-1">
        {data.map((item) => (
          <div
            key={item.slug}
            className={cn(
              "size-6 rounded-sm transition-opacity hover:opacity-80",
              ageColor(item.daysOld),
            )}
            title={`${item.title} (${item.section}) — ${item.daysOld}d old`}
          />
        ))}
      </div>
    </div>
  );
}
