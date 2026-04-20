"use client";

import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/admin/data-table";
import type { TableProfile } from "@/lib/admin/types";

const columnHelper = createColumnHelper<TableProfile>();

const columns = [
  columnHelper.accessor("table", {
    header: "Table",
    cell: (info) => <span className="font-mono">{info.getValue()}</span>,
  }),
  columnHelper.accessor("rowCount", {
    header: "Rows",
    cell: (info) => (
      <span className="font-mono tabular-nums text-muted-foreground">
        {info.getValue().toLocaleString()}
      </span>
    ),
  }),
  columnHelper.accessor("columnCount", {
    header: "Columns",
    cell: (info) => (
      <span className="font-mono tabular-nums text-muted-foreground">
        {info.getValue()}
      </span>
    ),
  }),
  columnHelper.display({
    id: "columnProfile",
    header: "Column profile",
    cell: (info) => {
      const columns = info.row.original.columns;

      return (
        <div className="flex flex-wrap gap-1.5">
          {columns.slice(0, 6).map((column) => (
            <span
              key={`${info.row.original.table}-${column.name}`}
              className="inline-flex rounded-full border border-border/70 bg-muted/40 px-2 py-0.5 font-mono text-[0.7rem] text-muted-foreground"
            >
              {column.name}
              <span className="ml-1 text-foreground/70">{column.type}</span>
            </span>
          ))}
          {columns.length > 6 ? (
            <span className="inline-flex rounded-full border border-dashed border-border/70 px-2 py-0.5 text-[0.7rem] text-muted-foreground">
              +{columns.length - 6} more
            </span>
          ) : null}
        </div>
      );
    },
  }),
];

export function ProfilingLayerTable({ tables }: { tables: TableProfile[] }) {
  return <DataTable data={tables} columns={columns} />;
}
