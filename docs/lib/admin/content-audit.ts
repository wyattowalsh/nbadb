import { statSync } from "node:fs";
import { resolve } from "node:path";
import { source } from "@/lib/source";
import type { ContentPageMeta } from "./types";

const CONTENT_DIR = resolve(process.cwd(), "content/docs");

function getFileModifiedDate(slugParts: string[]): string | null {
  // Try index file first (e.g. content/docs/guides/index.mdx), then leaf file
  const candidates = [
    resolve(CONTENT_DIR, ...slugParts, "index.mdx"),
    resolve(CONTENT_DIR, `${slugParts.join("/")}.mdx`),
  ];
  for (const filePath of candidates) {
    try {
      const stat = statSync(filePath);
      return stat.mtime.toISOString();
    } catch {
      continue;
    }
  }
  return null;
}

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
      lastModified: getFileModifiedDate(slugParts),
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
