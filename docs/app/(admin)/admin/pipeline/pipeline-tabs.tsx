"use client";

import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PipelineCharts } from "./pipeline-charts";
import { PipelineHistory } from "./pipeline-history";

export function PipelineTabs({
  chartsProps,
  historyProps,
}: {
  chartsProps: Parameters<typeof PipelineCharts>[0];
  historyProps?: Parameters<typeof PipelineHistory>[0];
}) {
  return (
    <Tabs defaultValue="current">
      <TabsList>
        <TabsTrigger value="current">Current</TabsTrigger>
        <TabsTrigger value="history">History</TabsTrigger>
      </TabsList>

      <TabsContent value="current">
        <PipelineCharts {...chartsProps} />
      </TabsContent>

      <TabsContent value="history">
        {historyProps ? (
          <PipelineHistory {...historyProps} />
        ) : (
          <div className="flex items-center justify-center rounded-2xl border border-border/60 bg-muted/20 px-6 py-12">
            <p className="text-sm text-muted-foreground">
              No history data available. Pipeline history will appear here after
              extraction runs are recorded.
            </p>
          </div>
        )}
      </TabsContent>
    </Tabs>
  );
}
