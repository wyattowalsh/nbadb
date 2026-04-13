import { stat } from "node:fs/promises";
import { resolve } from "node:path";
import { source } from "@/lib/source";
import type { ContentPageMeta } from "./types";

const CONTENT_DIR = resolve(
  /* turbopackIgnore: true */ process.cwd(),
  "content",
  "docs",
);

async function getFileModifiedDate(
  slugParts: string[],
): Promise<string | null> {
  // Try index file first (e.g. content/docs/guides/index.mdx), then leaf file.
  // The docs landing page is represented by an empty slug array.
  const candidates = slugParts.length
    ? [
        resolve(
          /* turbopackIgnore: true */ CONTENT_DIR,
          ...slugParts,
          "index.mdx",
        ),
        resolve(
          /* turbopackIgnore: true */ CONTENT_DIR,
          `${slugParts.join("/")}.mdx`,
        ),
      ]
    : [resolve(/* turbopackIgnore: true */ CONTENT_DIR, "index.mdx")];
  for (const filePath of candidates) {
    try {
      const info = await stat(filePath);
      return info.mtime.toISOString();
    } catch {
      continue;
    }
  }
  return null;
}

export async function getPageLastModified(
  slugParts: string[],
): Promise<string | null> {
  return getFileModifiedDate(slugParts);
}

export async function getContentPages(): Promise<ContentPageMeta[]> {
  const pages = source.getPages();

  return Promise.all(
    pages.map(async (page) => {
      const slugParts = page.slugs;
      const section = slugParts[0] ?? "root";

      return {
        title: page.data.title ?? "Untitled",
        slug: slugParts.join("/"),
        url: page.url,
        section,
        description: page.data.description ?? null,
        tocDepth: page.data.toc?.length ?? 0,
        lastModified: await getFileModifiedDate(slugParts),
      };
    }),
  );
}

export async function getContentAudit() {
  const pages = await getContentPages();
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
