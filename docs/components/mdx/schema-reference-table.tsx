"use client";

import { useState } from "react";

export interface SchemaColumn {
  name: string;
  type: string;
  nullable: boolean;
  constraints: string;
  description: string;
}

export interface SchemaEntry {
  table_name: string;
  class_name: string;
  coerce: boolean;
  strict: boolean;
  columns: SchemaColumn[];
}

export function SchemaReferenceTable({ data }: { data: SchemaEntry[] }) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? data.filter((s) => s.table_name.includes(filter.toLowerCase()))
    : data;

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <input
          type="search"
          placeholder={`Filter ${data.length} schemas…`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full max-w-sm rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/60"
        />
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {filtered.length} of {data.length}
        </span>
      </div>
      {filtered.map((schema) => (
        <section key={schema.table_name} id={schema.table_name} className="mb-8">
          <h2 className="text-lg font-semibold">
            <code>{schema.table_name}</code>
          </h2>
          <p className="mt-1 text-sm text-muted-foreground">
            <strong>Class</strong>: <code>{schema.class_name}</code>{" · "}
            <strong>Coerce</strong>: {String(schema.coerce)}{" · "}
            <strong>Strict</strong>: {String(schema.strict)}
          </p>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <th className="px-2 py-1.5">Column</th>
                  <th className="px-2 py-1.5">Type</th>
                  <th className="px-2 py-1.5">Nullable</th>
                  <th className="px-2 py-1.5">Constraints</th>
                  <th className="px-2 py-1.5">Description</th>
                </tr>
              </thead>
              <tbody>
                {schema.columns.map((col) => (
                  <tr key={col.name} className="border-b border-border/50">
                    <td className="px-2 py-1"><code>{col.name}</code></td>
                    <td className="px-2 py-1"><code>{col.type}</code></td>
                    <td className="px-2 py-1">{col.nullable ? "Yes" : "No"}</td>
                    <td className="px-2 py-1">{col.constraints}</td>
                    <td className="px-2 py-1">{col.description}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}

export function DataDictionaryTable({
  data,
}: {
  data: { table_name: string; fields: { name: string; type: string; nullable: boolean; description: string; source: string; fk_ref: string }[] }[];
}) {
  const [filter, setFilter] = useState("");
  const filtered = filter
    ? data.filter((s) => s.table_name.includes(filter.toLowerCase()))
    : data;

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <input
          type="search"
          placeholder={`Filter ${data.length} tables…`}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full max-w-sm rounded-md border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/60"
        />
        <span className="whitespace-nowrap text-xs text-muted-foreground">
          {filtered.length} of {data.length}
        </span>
      </div>
      {filtered.map((entry) => (
        <section key={entry.table_name} id={entry.table_name} className="mb-8">
          <h2 className="text-lg font-semibold">{entry.table_name}</h2>
          <div className="mt-2 overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                  <th className="px-2 py-1.5">Column</th>
                  <th className="px-2 py-1.5">Type</th>
                  <th className="px-2 py-1.5">Nullable</th>
                  <th className="px-2 py-1.5">Description</th>
                  <th className="px-2 py-1.5">Source</th>
                </tr>
              </thead>
              <tbody>
                {entry.fields.map((f) => (
                  <tr key={f.name} className="border-b border-border/50">
                    <td className="px-2 py-1"><code>{f.name}</code></td>
                    <td className="px-2 py-1"><code>{f.type}</code></td>
                    <td className="px-2 py-1">{f.nullable ? "Yes" : "No"}</td>
                    <td className="px-2 py-1">{f.description}{f.fk_ref ? ` (FK → ${f.fk_ref})` : ""}</td>
                    <td className="px-2 py-1"><code>{f.source}</code></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      ))}
    </div>
  );
}
