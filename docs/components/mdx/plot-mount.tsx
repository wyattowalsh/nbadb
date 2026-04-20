"use client";

import { useEffect, useRef } from "react";
import * as Plot from "@observablehq/plot";

export type PlotOptions = NonNullable<Parameters<typeof Plot.plot>[0]>;
export type PlotElement = SVGSVGElement | HTMLElement;

const DEFAULT_PLOT_STYLE = {
  background: "transparent",
  color: "currentColor",
  fontFamily: "inherit",
  fontSize: "12px",
} as const;

export function withDefaultPlotStyle(options: PlotOptions): PlotOptions {
  const style = options.style;

  return {
    ...options,
    style: {
      ...DEFAULT_PLOT_STYLE,
      ...(style && typeof style === "object" ? style : {}),
    },
  };
}

export function PlotMount({
  createPlot,
  className,
  ariaLabel,
}: {
  createPlot: () => PlotElement | null;
  className: string;
  ariaLabel?: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const plot = createPlot();
    if (!plot) return;

    container.append(plot);
    return () => plot.remove();
  }, [createPlot]);

  return (
    <div
      ref={containerRef}
      className={className}
      role={ariaLabel ? "img" : undefined}
      aria-label={ariaLabel}
    />
  );
}
