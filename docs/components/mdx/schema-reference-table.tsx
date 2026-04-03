"use client";

import { type ReactNode, useId, useState } from "react";

/* ── Shared filterable wrapper ────────────────────────── */

interface FilterableTableProps<T extends { table_name: string }> {
  data: T[];
  label: string;
  renderEntry: (entry: T) => ReactNode;
}

function FilterableTable<T extends { table_name: string }>({
  data,
  label,
  renderEntry,
}: FilterableTableProps<T>) {
  const [filter, setFilter] = useState("");
  const countId = useId();
  const filtered = filter
    ? data.filter((s) => s.table_name.includes(filter.toLowerCase()))
    : data;

  return (
    <div>
      <div className="mb-4 flex items-center gap-3">
        <input
          type="search"
          placeholder={`Filter ${data.length} ${label}…`}
          aria-label={`Filter ${data.length} ${label}`}
          aria-describedby={countId}
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full rounded-[var(--radius-md)] border border-border bg-background px-3 py-1.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring/60 sm:max-w-sm"
        />
        <span
          id={countId}
          className="whitespace-nowrap text-xs text-muted-foreground"
          aria-live="polite"
        >
          {filtered.length} of {data.length}
        </span>
      </div>
      {filtered.map((entry) => (
        <section key={entry.table_name} id={entry.table_name} className="mb-8">
          {renderEntry(entry)}
        </section>
      ))}
    </div>
  );
}

/* ── Types ────────────────────────────────────────────── */

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

export interface DictionaryField {
  name: string;
  type: string;
  nullable: boolean;
  description: string;
  source: string;
  fk_ref: string;
}

export interface DictionaryEntry {
  table_name: string;
  fields: DictionaryField[];
}

/* ── Table header cell ────────────────────────────────── */

const TH_CLASS =
  "px-2 py-1.5 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground";

/* ── Schema Reference ─────────────────────────────────── */

function SchemaEntryView({ entry }: { entry: SchemaEntry }) {
  return (
    <>
      <h2 className="text-lg font-semibold">
        <code>{entry.table_name}</code>
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        <strong>Class</strong>: <code>{entry.class_name}</code>
        {" · "}
        <strong>Coerce</strong>: {String(entry.coerce)}
        {" · "}
        <strong>Strict</strong>: {String(entry.strict)}
      </p>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Schema columns for {entry.table_name}
          </caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className={TH_CLASS}>Column</th>
              <th scope="col" className={TH_CLASS}>Type</th>
              <th scope="col" className={TH_CLASS}>Nullable</th>
              <th scope="col" className={TH_CLASS}>Constraints</th>
              <th scope="col" className={TH_CLASS}>Description</th>
            </tr>
          </thead>
          <tbody>
            {entry.columns.map((col) => (
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
    </>
  );
}

export function SchemaReferenceTable({ data }: { data: SchemaEntry[] }) {
  return (
    <FilterableTable
      data={data}
      label="schemas"
      renderEntry={(entry) => <SchemaEntryView entry={entry} />}
    />
  );
}

/* ── Data Dictionary ──────────────────────────────────── */

function DictionaryEntryView({ entry }: { entry: DictionaryEntry }) {
  return (
    <>
      <h2 className="text-lg font-semibold">{entry.table_name}</h2>
      <div className="mt-2 overflow-x-auto">
        <table className="w-full text-sm">
          <caption className="sr-only">
            Field definitions for {entry.table_name}
          </caption>
          <thead>
            <tr className="border-b">
              <th scope="col" className={TH_CLASS}>Column</th>
              <th scope="col" className={TH_CLASS}>Type</th>
              <th scope="col" className={TH_CLASS}>Nullable</th>
              <th scope="col" className={TH_CLASS}>Description</th>
              <th scope="col" className={TH_CLASS}>Source</th>
            </tr>
          </thead>
          <tbody>
            {entry.fields.map((f) => (
              <tr key={f.name} className="border-b border-border/50">
                <td className="px-2 py-1"><code>{f.name}</code></td>
                <td className="px-2 py-1"><code>{f.type}</code></td>
                <td className="px-2 py-1">{f.nullable ? "Yes" : "No"}</td>
                <td className="px-2 py-1">
                  {f.description}
                  {f.fk_ref ? ` (FK → ${f.fk_ref})` : ""}
                </td>
                <td className="px-2 py-1"><code>{f.source}</code></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

export function DataDictionaryTable({ data }: { data: DictionaryEntry[] }) {
  return (
    <FilterableTable
      data={data}
      label="tables"
      renderEntry={(entry) => <DictionaryEntryView entry={entry} />}
    />
  );
}
