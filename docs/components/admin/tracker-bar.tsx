import { cn } from "@/lib/utils";

type TrackerItem = {
  status: "done" | "failed" | "running" | "abandoned";
  label?: string;
};

const statusColors: Record<TrackerItem["status"], string> = {
  done: "bg-primary",
  failed: "bg-destructive",
  running: "bg-accent",
  abandoned: "bg-muted",
};

type TrackerBarProps = {
  data: TrackerItem[];
  className?: string;
};

export function TrackerBar({ data, className }: TrackerBarProps) {
  return (
    <div className={cn("flex items-center gap-0.5", className)}>
      {data.map((item, i) => (
        <div
          key={i}
          className={cn(
            "h-8 flex-1 rounded-sm transition-opacity",
            statusColors[item.status],
            "hover:opacity-80",
          )}
          title={item.label ?? item.status}
        />
      ))}
    </div>
  );
}
