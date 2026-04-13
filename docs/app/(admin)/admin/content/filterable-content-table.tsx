"use client";

import { useState, useMemo } from "react";
import { ContentTable } from "./content-table";
import type { ContentPageMeta } from "@/lib/admin/types";

export function FilterableContentTable({
  pages,
}: {
  pages: ContentPageMeta[];
}) {
  const [filter, setFilter] = useState("");
  const [section, setSection] = useState("all");
  const sections = useMemo(
    () => ["all", ...new Set(pages.map((page) => page.section))],
    [pages],
  );

  const filteredPages = useMemo(() => {
    const query = filter.toLowerCase().trim();
    return pages.filter((page) => {
      const matchesSection = section === "all" || page.section === section;
      const matchesQuery =
        !query ||
        page.slug.toLowerCase().includes(query) ||
        page.title.toLowerCase().includes(query);

      return matchesSection && matchesQuery;
    });
  }, [pages, filter, section]);

  return (
    <div className="space-y-3">
      <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_14rem]">
        <input
          type="text"
          placeholder="Filter by slug or title..."
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          className="w-full rounded-xl border border-border/70 bg-background px-4 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
        <select
          value={section}
          onChange={(e) => setSection(e.target.value)}
          className="w-full rounded-xl border border-border/70 bg-background px-4 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-primary/30"
        >
          {sections.map((value) => (
            <option key={value} value={value}>
              {value === "all" ? "All sections" : value}
            </option>
          ))}
        </select>
      </div>
      <ContentTable pages={filteredPages} />
    </div>
  );
}
