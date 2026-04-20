import { cn } from "@/lib/utils";

type BarListItem = {
  name: string;
  value: number;
  href?: string;
};

type BarListProps = {
  data: BarListItem[];
  color?: string;
  className?: string;
};

export function BarList({
  data,
  color = "var(--primary)",
  className,
}: BarListProps) {
  const maxValue = Math.max(...data.map((d) => d.value), 1);

  return (
    <div className={cn("space-y-2", className)}>
      {data.map((item) => (
        <div key={item.name} className="group flex items-center gap-3">
          <div className="relative flex-1 overflow-hidden rounded-lg">
            <div
              className="absolute inset-y-0 left-0 rounded-lg opacity-15"
              style={{
                width: `${(item.value / maxValue) * 100}%`,
                backgroundColor: color,
              }}
            />
            <div className="relative px-3 py-1.5 text-sm text-foreground">
              {item.href ? (
                <a href={item.href} className="hover:underline">
                  {item.name}
                </a>
              ) : (
                item.name
              )}
            </div>
          </div>
          <span className="w-12 text-right font-mono text-sm font-semibold text-muted-foreground tabular-nums">
            {item.value.toLocaleString()}
          </span>
        </div>
      ))}
    </div>
  );
}
