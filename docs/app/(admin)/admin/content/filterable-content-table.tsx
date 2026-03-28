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

  const filteredPages = useMemo(() => {
    const query = filter.toLowerCase().trim();
    if (!query) return pages;
    return pages.filter(
      (p) =>
        p.slug.toLowerCase().includes(query) ||
        p.title.toLowerCase().includes(query),
    );
  }, [pages, filter]);

  return (
    <div className="space-y-3">
      <input
        type="text"
        placeholder="Filter by slug or title..."
        value={filter}
        onChange={(e) => setFilter(e.target.value)}
        className="w-full rounded-xl border border-border/70 bg-background px-4 py-2 text-sm text-foreground placeholder:text-muted-foreground/60 focus:outline-none focus:ring-2 focus:ring-primary/30"
      />
      <ContentTable pages={filteredPages} />
    </div>
  );
}
