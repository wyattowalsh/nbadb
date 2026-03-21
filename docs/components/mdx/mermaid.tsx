"use client";

import { Suspense, use, useEffect, useId, useState } from "react";
import { useTheme } from "next-themes";

export function Mermaid({ chart }: { chart: string }) {
  const [mounted, setMounted] = useState(false);
  const normalizedChart = chart.replaceAll("\\n", "\n");

  useEffect(() => {
    setMounted(true); // eslint-disable-line react-hooks/set-state-in-effect -- standard SSR guard pattern
  }, []);

  if (!mounted) {
    return (
      <MermaidFallback
        chart={normalizedChart}
        detail="Showing Mermaid source preview until the SVG diagram hydrates."
        status="Preparing board"
      />
    );
  }

  return (
    <Suspense
      fallback={
        <MermaidFallback
          chart={normalizedChart}
          detail="Client-side Mermaid render in progress."
          status="Rendering board"
        />
      }
    >
      <MermaidContent chart={normalizedChart} />
    </Suspense>
  );
}

const cache = new Map<string, Promise<unknown>>();

function cachePromise<T>(
  key: string,
  setPromise: () => Promise<T>,
): Promise<T> {
  const cached = cache.get(key);
  if (cached) return cached as Promise<T>;

  const promise = setPromise();
  cache.set(key, promise);
  return promise;
}

function getThemeToken(name: string, fallback: string) {
  return (
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback
  );
}

function getMermaidTheme() {
  return {
    theme: "base" as const,
    themeVariables: {
      background: getThemeToken("--card", "#ffffff"),
      mainBkg: getThemeToken("--card", "#ffffff"),
      primaryColor: getThemeToken("--primary", "#2563eb"),
      primaryTextColor: getThemeToken("--primary-foreground", "#ffffff"),
      primaryBorderColor: getThemeToken("--border", "#d4d4d8"),
      secondaryColor: getThemeToken("--secondary", "#f4f4f5"),
      tertiaryColor: getThemeToken("--accent", "#fbbf24"),
      lineColor: getThemeToken("--foreground", "#111827"),
      textColor: getThemeToken("--foreground", "#111827"),
      edgeLabelBackground: getThemeToken("--background", "#ffffff"),
      clusterBkg: getThemeToken("--muted", "#f5f5f5"),
      clusterBorder: getThemeToken("--border", "#d4d4d8"),
      nodeBorder: getThemeToken("--border", "#d4d4d8"),
      defaultLinkColor: getThemeToken("--foreground", "#111827"),
      titleColor: getThemeToken("--foreground", "#111827"),
      actorTextColor: getThemeToken("--foreground", "#111827"),
      actorBorder: getThemeToken("--border", "#d4d4d8"),
      actorBkg: getThemeToken("--secondary", "#f4f4f5"),
      labelTextColor: getThemeToken("--foreground", "#111827"),
      cScale0: getThemeToken("--primary", "#2563eb"),
      cScale1: getThemeToken("--accent", "#fbbf24"),
      cScale2: getThemeToken("--secondary", "#f4f4f5"),
      cScale3: getThemeToken("--muted", "#e5e7eb"),
    },
  };
}

function MermaidFallback({
  chart,
  detail,
  status,
}: {
  chart: string;
  detail: string;
  status: string;
}) {
  const previewLines = chart
    .trim()
    .split("\n")
    .map((line) => line.trimEnd())
    .filter(Boolean);
  const preview = previewLines.slice(0, 12).join("\n");
  const hasMore = previewLines.length > 12;

  return (
    <div className="nba-viz-shell">
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">Mermaid diagram</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            {detail}
          </p>
        </div>
        <div aria-live="polite" className="nba-viz-status max-sm:hidden">
          {status}
        </div>
      </div>
      <div
        aria-label="Mermaid diagram preview"
        className="nba-mermaid-shell nba-mermaid-shell--placeholder"
      >
        <div className="nba-mermaid-placeholder-label">Source preview</div>
        <pre className="nba-mermaid-placeholder-code">
          <code>
            {preview}
            {hasMore ? "\n…" : ""}
          </code>
        </pre>
      </div>
    </div>
  );
}

function MermaidContent({ chart }: { chart: string }) {
  const id = useId();
  const { resolvedTheme } = useTheme();
  const { default: mermaid } = use(
    cachePromise("mermaid", () => import("mermaid")),
  );

  mermaid.initialize({
    startOnLoad: false,
    securityLevel: "loose",
    fontFamily: "inherit",
    themeCSS: "margin: 0 auto; max-width: 100%;",
    ...getMermaidTheme(),
  });

  const cacheKey = `${chart}-${resolvedTheme ?? "system"}`;
  const { svg, bindFunctions } = use(
    cachePromise(cacheKey, () => {
      return mermaid.render(id, chart);
    }),
  );

  return (
    <div className="nba-viz-shell">
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">Mermaid diagram</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Theme-synced with the site palette for cleaner contrast in light and
            dark mode.
          </p>
        </div>
        <div className="nba-viz-status max-sm:hidden">
          {resolvedTheme === "dark" ? "Dark board" : "Light board"}
        </div>
      </div>
      <div
        aria-label="Mermaid diagram"
        className="nba-mermaid-shell"
        ref={(container) => {
          if (container) bindFunctions?.(container);
        }}
        dangerouslySetInnerHTML={{ __html: svg }}
      />
    </div>
  );
}
