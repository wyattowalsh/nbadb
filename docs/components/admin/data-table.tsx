"use client";

import {
  flexRender,
  getCoreRowModel,
  getSortedRowModel,
  getPaginationRowModel,
  useReactTable,
  type ColumnDef,
  type SortingState,
} from "@tanstack/react-table";
import { useState } from "react";
import { cn } from "@/lib/utils";
import { ArrowDown, ArrowUp, ArrowUpDown } from "lucide-react";

type DataTableProps<TData> = {
  data: TData[];
  // TanStack column defs are invariant in TValue, so heterogeneous column arrays
  // need an erased value type at this component boundary.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  columns: ColumnDef<TData, any>[];
  className?: string;
};

export function DataTable<TData>({
  data,
  columns,
  className,
}: DataTableProps<TData>) {
  const [sorting, setSorting] = useState<SortingState>([]);

  // TanStack Table's mutable table instance is not React Compiler-compatible yet.
  // eslint-disable-next-line react-hooks/incompatible-library
  const table = useReactTable({
    data,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    getSortedRowModel: getSortedRowModel(),
    getPaginationRowModel: getPaginationRowModel(),
    initialState: { pagination: { pageSize: 20 } },
  });
  const rowModel = table.getRowModel();
  const visibleColumnCount = table.getVisibleLeafColumns().length || 1;

  return (
    <div
      className={cn(
        "overflow-hidden rounded-2xl border border-border/70",
        className,
      )}
    >
      <div className="overflow-x-auto">
        <table className="w-full">
          <thead>
            {table.getHeaderGroups().map((headerGroup) => (
              <tr
                key={headerGroup.id}
                className="border-b border-border/60 bg-muted/30"
              >
                {headerGroup.headers.map((header) => (
                  <th
                    key={header.id}
                    aria-sort={
                      header.column.getCanSort()
                        ? header.column.getIsSorted() === "asc"
                          ? "ascending"
                          : header.column.getIsSorted() === "desc"
                            ? "descending"
                            : "none"
                        : undefined
                    }
                    className={cn(
                      "px-4 py-3 text-left text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground",
                      header.column.getCanSort() &&
                        "cursor-pointer select-none",
                    )}
                    onClick={header.column.getToggleSortingHandler()}
                  >
                    <div className="flex items-center gap-1">
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                      {header.column.getCanSort() && (
                        <span className="text-muted-foreground/50">
                          {header.column.getIsSorted() === "asc" ? (
                            <ArrowUp className="size-3" />
                          ) : header.column.getIsSorted() === "desc" ? (
                            <ArrowDown className="size-3" />
                          ) : (
                            <ArrowUpDown className="size-3" />
                          )}
                        </span>
                      )}
                    </div>
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {rowModel.rows.length === 0 ? (
              <tr>
                <td
                  colSpan={visibleColumnCount}
                  className="px-4 py-8 text-center text-sm text-muted-foreground"
                >
                  No rows are available for this view yet.
                </td>
              </tr>
            ) : (
              rowModel.rows.map((row) => (
                <tr
                  key={row.id}
                  className="border-b border-border/40 transition-colors hover:bg-muted/20"
                >
                  {row.getVisibleCells().map((cell) => (
                    <td
                      key={cell.id}
                      className="px-4 py-3 text-sm text-foreground"
                    >
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </td>
                  ))}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
      {table.getPageCount() > 1 && (
        <div className="flex items-center justify-between border-t border-border/60 px-4 py-3">
          <span className="text-xs text-muted-foreground">
            Page {table.getState().pagination.pageIndex + 1} of{" "}
            {table.getPageCount()}
          </span>
          <div className="flex gap-1">
            <button
              className="rounded-lg px-3 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:bg-muted/40 disabled:opacity-40"
              onClick={() => table.previousPage()}
              disabled={!table.getCanPreviousPage()}
            >
              Prev
            </button>
            <button
              className="rounded-lg px-3 py-1 text-xs font-semibold text-muted-foreground transition-colors hover:bg-muted/40 disabled:opacity-40"
              onClick={() => table.nextPage()}
              disabled={!table.getCanNextPage()}
            >
              Next
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
