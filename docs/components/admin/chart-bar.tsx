"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

type ChartBarProps = {
  data: Record<string, unknown>[];
  xKey: string;
  yKey: string;
  color?: string;
  height?: number;
  /** Maximum character width for x-axis labels before ellipsis (default 20) */
  xLabelMaxChars?: number;
};

function EllipsisTick({
  x,
  y,
  payload,
  maxChars,
}: {
  x: number;
  y: number;
  payload: { value: string };
  maxChars: number;
}) {
  const label = String(payload.value ?? "");
  const display =
    label.length > maxChars ? `${label.slice(0, maxChars - 1)}...` : label;
  return (
    <text
      x={x}
      y={y + 10}
      textAnchor="middle"
      fill="var(--muted-foreground)"
      fontSize={11}
    >
      <title>{label}</title>
      {display}
    </text>
  );
}

export function ChartBar({
  data,
  xKey,
  yKey,
  color = "var(--primary)",
  height = 240,
  xLabelMaxChars = 20,
}: ChartBarProps) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid
          strokeDasharray="3 3"
          stroke="var(--border)"
          strokeOpacity={0.5}
          vertical={false}
        />
        <XAxis
          dataKey={xKey}
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          tick={(props: any) => (
            <EllipsisTick
              x={Number(props.x)}
              y={Number(props.y)}
              payload={props.payload}
              maxChars={xLabelMaxChars}
            />
          )}
          axisLine={false}
          tickLine={false}
        />
        <YAxis
          tick={{ fill: "var(--muted-foreground)", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
          width={40}
        />
        <Tooltip
          contentStyle={{
            backgroundColor: "var(--popover)",
            border: "1px solid var(--border)",
            borderRadius: "0.75rem",
            color: "var(--popover-foreground)",
            fontSize: 12,
          }}
        />
        <Bar
          dataKey={yKey}
          fill={color}
          radius={[4, 4, 0, 0]}
          maxBarSize={40}
        />
      </BarChart>
    </ResponsiveContainer>
  );
}
