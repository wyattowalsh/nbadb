"use client";

import { createColumnHelper } from "@tanstack/react-table";
import { DataTable } from "@/components/admin/data-table";

type TableProfile = {
  table: string;
  layer: string;
  rowCount: number;
  columnCount: number;
};

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
];

export function ProfilingLayerTable({ tables }: { tables: TableProfile[] }) {
  return <DataTable data={tables} columns={columns} />;
}
