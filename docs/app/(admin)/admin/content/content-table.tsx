"use client";

import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/admin/data-table";
import { Badge } from "@/components/ui/badge";
import type { ContentPageMeta } from "@/lib/admin/types";

const columnHelper = createColumnHelper<ContentPageMeta>();

const columns = [
  columnHelper.accessor("title", {
    header: "Title",
    cell: (info) => (
      <a
        href={info.row.original.url}
        className="font-medium text-foreground hover:underline"
      >
        {info.getValue()}
      </a>
    ),
  }),
  columnHelper.accessor("section", {
    header: "Section",
    cell: (info) => (
      <Badge variant="outline" className="text-[0.65rem]">
        {info.getValue()}
      </Badge>
    ),
  }),
  columnHelper.accessor("description", {
    header: "Description",
    cell: (info) => {
      const desc = info.getValue();
      return desc ? (
        <span className="max-w-xs truncate text-muted-foreground">{desc}</span>
      ) : (
        <span className="text-destructive/70 text-xs">Missing</span>
      );
    },
  }),
  columnHelper.accessor("tocDepth", {
    header: "TOC depth",
    cell: (info) => (
      <span className="font-mono tabular-nums">{info.getValue()}</span>
    ),
  }),
];

export function ContentTable({ pages }: { pages: ContentPageMeta[] }) {
  return <DataTable data={pages} columns={columns} />;
}
