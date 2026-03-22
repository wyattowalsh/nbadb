import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";
import { TrendingDown, TrendingUp } from "lucide-react";

type KpiCardProps = {
  label: string;
  value: string | number;
  trend?: { value: number; label: string };
  className?: string;
};

export function KpiCard({ label, value, trend, className }: KpiCardProps) {
  return (
    <Card className={cn("p-4", className)}>
      <p className="nba-kicker">{label}</p>
      <div className="mt-2 nba-scoreboard-value text-3xl text-foreground">
        {value}
      </div>
      {trend && (
        <div
          className={cn(
            "mt-2 flex items-center gap-1 text-xs font-semibold",
            trend.value >= 0 ? "text-primary" : "text-destructive",
          )}
        >
          {trend.value >= 0 ? (
            <TrendingUp className="size-3.5" />
          ) : (
            <TrendingDown className="size-3.5" />
          )}
          {trend.value >= 0 ? "+" : ""}
          {trend.value}% {trend.label}
        </div>
      )}
    </Card>
  );
}
