import { source } from "@/lib/source";
import type { ContentPageMeta } from "./types";

export function getContentPages(): ContentPageMeta[] {
  const pages = source.getPages();

  return pages.map((page) => {
    const slugParts = page.slugs;
    const section = slugParts[0] ?? "root";

    return {
      title: page.data.title ?? "Untitled",
      slug: slugParts.join("/"),
      url: page.url,
      section,
      description: page.data.description ?? null,
      tocDepth: page.data.toc?.length ?? 0,
      lastModified: null,
    };
  });
}

export function getContentAudit() {
  const pages = getContentPages();
  const missingDescription = pages.filter((p) => !p.description);
  const shallowToc = pages.filter((p) => p.tocDepth < 3);

  const sectionCounts: Record<string, number> = {};
  for (const page of pages) {
    sectionCounts[page.section] = (sectionCounts[page.section] ?? 0) + 1;
  }

  return {
    pages,
    totalPages: pages.length,
    missingDescription,
    shallowToc,
    sectionCounts,
  };
}
