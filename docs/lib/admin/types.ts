export type ContentPageMeta = {
  title: string;
  slug: string;
  url: string;
  section: string;
  description: string | null;
  tocDepth: number;
  lastModified: string | null;
};

export type PipelineRunStatus = "done" | "failed" | "running" | "abandoned";

export type PipelineRun = {
  timestamp: string;
  status: PipelineRunStatus;
  tablesProcessed: number;
  rowsExtracted: number;
  durationMs: number;
  errors: string[];
};

export type PipelineDailyRollup = {
  date: string;
  label: string;
  runCount: number;
  tablesProcessed: number;
  rowsExtracted: number;
  errorCount: number;
  durationMs: number;
  avgDurationMs: number;
  p95DurationMs: number;
};

export type PipelineEndpointTelemetry = {
  endpoint: string;
  runCount: number;
  rowsExtracted: number;
  errorCount: number;
  errorRate: number;
  avgDurationMs: number;
  p95DurationMs: number;
  maxDurationMs: number;
  lastRun: string | null;
};

export type PipelineFailureHotspot = {
  endpoint: string;
  status: Extract<PipelineRunStatus, "failed" | "abandoned">;
  count: number;
  lastSeen: string | null;
  sampleError: string | null;
};

export type PipelineWindowTotals = {
  runs: number;
  rowsExtracted: number;
  errorCount: number;
  avgDurationMs: number;
  p95DurationMs: number;
};

export type PipelineSummary = {
  generatedAt: string | null;
  lastRun: string | null;
  totalTables: number;
  stagingCoverage: number;
  runs: PipelineRun[];
  recentErrors: string[];
  counts: Record<PipelineRunStatus, number>;
  windowDays: number;
  daily: PipelineDailyRollup[];
  slowEndpoints: PipelineEndpointTelemetry[];
  failureHotspots: PipelineFailureHotspot[];
  totals: PipelineWindowTotals;
};

export type UmamiStats = {
  pageviews: number;
  visitors: number;
  bounceRate: number;
  avgDuration: number;
};

export type UmamiPageview = {
  date: string;
  views: number;
  visitors: number;
};

export type UmamiTopPage = {
  url: string;
  views: number;
  visitors: number;
  avgDuration: number;
  bounceRate: number;
};

export type UmamiReferrer = {
  referrer: string;
  views: number;
  visitors: number;
};

export type SubsystemStatus = "healthy" | "degraded" | "down" | "unknown";

export type HealthCheck = {
  overall: SubsystemStatus;
  subsystems: {
    build: { status: SubsystemStatus; detail: string };
    search: { status: SubsystemStatus; detail: string };
    pipeline: { status: SubsystemStatus; detail: string };
    content: { status: SubsystemStatus; detail: string };
  };
  pageCount: number;
  lastBuild: string | null;
};

export type DateRange = "24h" | "7d" | "30d" | "90d";
