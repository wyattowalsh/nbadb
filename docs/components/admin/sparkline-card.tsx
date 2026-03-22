"use client";

import { Area, AreaChart, ResponsiveContainer } from "recharts";
import { Card } from "@/components/ui/card";
import { cn } from "@/lib/utils";

type SparklineCardProps = {
  label: string;
  value: string | number;
  data: { value: number }[];
  color?: string;
  className?: string;
};

export function SparklineCard({
  label,
  value,
  data,
  color = "var(--primary)",
  className,
}: SparklineCardProps) {
  return (
    <Card className={cn("p-4", className)}>
      <p className="nba-kicker">{label}</p>
      <div className="mt-1 nba-scoreboard-value text-3xl text-foreground">
        {value}
      </div>
      <div className="mt-3 h-12">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={data}>
            <defs>
              <linearGradient id={`spark-${label}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={color} stopOpacity={0.3} />
                <stop offset="100%" stopColor={color} stopOpacity={0} />
              </linearGradient>
            </defs>
            <Area
              type="monotone"
              dataKey="value"
              stroke={color}
              strokeWidth={2}
              fill={`url(#spark-${label})`}
              dot={false}
              isAnimationActive={false}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </Card>
  );
}
