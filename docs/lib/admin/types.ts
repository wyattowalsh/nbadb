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

export type PipelineSummary = {
  lastRun: string | null;
  totalTables: number;
  stagingCoverage: number;
  runs: PipelineRun[];
  recentErrors: string[];
  counts: Record<PipelineRunStatus, number>;
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
