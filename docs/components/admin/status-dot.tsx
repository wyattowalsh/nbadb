import { cn } from "@/lib/utils";
import type { SubsystemStatus } from "@/lib/admin/types";

const dotColors: Record<SubsystemStatus, string> = {
  healthy: "bg-primary",
  degraded: "bg-accent",
  down: "bg-destructive",
  unknown: "bg-muted-foreground/40",
};

const dotLabels: Record<SubsystemStatus, string> = {
  healthy: "Healthy",
  degraded: "Degraded",
  down: "Down",
  unknown: "Unknown",
};

type StatusDotProps = {
  status: SubsystemStatus;
  label: string;
  detail?: string;
  className?: string;
};

export function StatusDot({
  status,
  label,
  detail,
  className,
}: StatusDotProps) {
  return (
    <div className={cn("flex items-center gap-3", className)}>
      <span className="relative flex size-3">
        {status !== "healthy" && (
          <span
            className={cn(
              "absolute inline-flex size-full rounded-full opacity-40 motion-safe:animate-ping",
              dotColors[status],
            )}
          />
        )}
        <span
          className={cn(
            "relative inline-flex size-3 rounded-full",
            dotColors[status],
          )}
        />
      </span>
      <div>
        <span className="text-sm font-semibold text-foreground">{label}</span>
        <span className="ml-2 text-xs text-muted-foreground">
          {detail ?? dotLabels[status]}
        </span>
      </div>
    </div>
  );
}
