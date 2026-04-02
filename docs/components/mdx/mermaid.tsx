"use client";

import {
  Component,
  Suspense,
  use,
  useCallback,
  useEffect,
  useId,
  useRef,
  useState,
} from "react";
import type { ErrorInfo, ReactNode } from "react";
import { useTheme } from "next-themes";
import { Maximize2, Minus, Plus } from "lucide-react";
import { useZoomPan } from "@/lib/use-zoom-pan";

/* ── Render timeout ─────────────────────────────────── */

const RENDER_TIMEOUT_MS = 10_000;

function withTimeout<T>(
  promise: Promise<T>,
  ms: number,
  label: string,
): Promise<T> {
  return Promise.race([
    promise,
    new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new Error(`${label} timed out after ${ms}ms`)),
        ms,
      ),
    ),
  ]);
}

/* ── ErrorBoundary ──────────────────────────────────── */

interface ErrorBoundaryProps {
  chart: string;
  children: ReactNode;
}

interface ErrorBoundaryState {
  hasError: boolean;
  error: Error | null;
}

class MermaidErrorBoundary extends Component<
  ErrorBoundaryProps,
  ErrorBoundaryState
> {
  constructor(props: ErrorBoundaryProps) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): ErrorBoundaryState {
    return { hasError: true, error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("[Mermaid] Render error:", error, info);
  }

  render() {
    if (this.state.hasError) {
      return (
        <MermaidFallback
          chart={this.props.chart}
          detail={`Render failed: ${this.state.error?.message ?? "unknown error"}. Showing source instead.`}
          status="Error"
        />
      );
    }
    return this.props.children;
  }
}

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
    <MermaidErrorBoundary chart={normalizedChart}>
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
    </MermaidErrorBoundary>
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

let _probeCtx: CanvasRenderingContext2D | null = null;

function toHex(cssColor: string): string {
  if (typeof document === "undefined") return cssColor;
  if (/^#[0-9a-f]{3,8}$/i.test(cssColor)) return cssColor;

  if (!_probeCtx) {
    const c = document.createElement("canvas");
    c.width = c.height = 1;
    _probeCtx = c.getContext("2d", { willReadFrequently: true });
  }
  const ctx = _probeCtx;
  if (!ctx) return cssColor;

  ctx.clearRect(0, 0, 1, 1);
  ctx.fillStyle = cssColor;
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function getThemeToken(name: string, fallback: string) {
  const raw =
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() ||
    fallback;
  return toHex(raw);
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

function ZoomControls({
  pct,
  onZoomIn,
  onZoomOut,
  onReset,
}: {
  pct: number;
  onZoomIn: () => void;
  onZoomOut: () => void;
  onReset: () => void;
}) {
  return (
    <div
      className="nba-zoom-controls"
      role="toolbar"
      aria-label="Diagram zoom controls"
    >
      <button onClick={onZoomOut} aria-label="Zoom out" title="Zoom out">
        <Minus className="size-3.5" />
      </button>
      <span className="nba-zoom-pct" aria-live="polite">
        {pct}%
      </span>
      <button onClick={onZoomIn} aria-label="Zoom in" title="Zoom in">
        <Plus className="size-3.5" />
      </button>
      <button onClick={onReset} aria-label="Fit to view" title="Fit to view">
        <Maximize2 className="size-3.5" />
      </button>
    </div>
  );
}

function MermaidContent({ chart }: { chart: string }) {
  const id = useId();
  const { resolvedTheme } = useTheme();
  const svgRef = useRef<HTMLDivElement>(null);
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
      return withTimeout(
        mermaid.render(id, chart),
        RENDER_TIMEOUT_MS,
        "Mermaid render",
      );
    }),
  );

  const {
    viewportRef,
    canvasRef,
    canvasStyle,
    zoomIn,
    zoomOut,
    resetView,
    fitToView,
    pct,
    pointerHandlers,
    onKeyDown,
  } = useZoomPan();

  // Inject SVG and bind mermaid interactivity, then fit to view
  const combinedCanvasRef = useCallback(
    (node: HTMLDivElement | null) => {
      svgRef.current = node;
      canvasRef(node);
    },
    [canvasRef],
  );

  useEffect(() => {
    const el = svgRef.current;
    if (!el) return;
    el.innerHTML = svg;
    bindFunctions?.(el);

    // Fit after the browser has laid out the SVG
    requestAnimationFrame(() => {
      fitToView();
    });
  }, [svg, bindFunctions, fitToView]);

  return (
    <div className="nba-viz-shell">
      <div className="nba-viz-toolbar">
        <div>
          <p className="nba-kicker">Mermaid diagram</p>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            Scroll to zoom, drag to pan. Keyboard: +/− zoom, arrows pan, 0
            reset.
          </p>
        </div>
        <div className="nba-viz-toolbar-actions">
          <ZoomControls
            pct={pct}
            onZoomIn={zoomIn}
            onZoomOut={zoomOut}
            onReset={resetView}
          />
          <div className="nba-viz-status max-sm:hidden">
            {resolvedTheme === "dark" ? "Dark board" : "Light board"}
          </div>
        </div>
      </div>
      <div className="nba-mermaid-shell">
        <div
          className="nba-mermaid-viewport"
          ref={viewportRef}
          tabIndex={0}
          role="application"
          aria-label="Zoomable Mermaid diagram"
          onDoubleClick={resetView}
          onKeyDown={onKeyDown}
          {...pointerHandlers}
        >
          <div
            className="nba-mermaid-canvas"
            ref={combinedCanvasRef}
            style={canvasStyle}
          />
        </div>
      </div>
    </div>
  );
}
