import { statSync } from "node:fs";
import { join } from "node:path";
import type { MetadataRoute } from "next";
import { getGeneratedPageFrame, siteOrigin } from "@/lib/site-config";
import { source } from "@/lib/source";

const contentDir = join(process.cwd(), "content/docs");

const priorityMap = new Map<string, number>([
  ["/docs", 0.95],
  ["/docs/installation", 0.9],
  ["/docs/architecture", 0.9],
  ["/docs/cli-reference", 0.88],
  ["/docs/playground", 0.88],
  ["/docs/schema", 0.86],
  ["/docs/endpoints", 0.84],
  ["/docs/guides", 0.84],
  ["/docs/lineage", 0.78],
  ["/docs/diagrams", 0.76],
  ["/docs/data-dictionary", 0.76],
]);

/**
 * Resolve a page's URL to a priority tier:
 * - Primary landing/route pages: 0.84-0.95
 * - Guide pages and curated references: 0.75-0.8
 * - Heavy generated reference/detail pages: 0.58-0.68
 */
function pagePriority(page: { url: string; slugs: string[] }): number {
  const { url, slugs } = page;
  const explicit = priorityMap.get(url);
  if (explicit) return explicit;
  if (url.startsWith("/docs/guides/")) return 0.8;
  if (getGeneratedPageFrame(slugs)) return 0.62;
  if (url.startsWith("/docs/schema/")) return 0.74;
  return 0.72;
}

/**
 * Derive the content file path from the page's slugs and try to stat it.
 * Falls back to the build timestamp when the file cannot be found.
 */
function pageLastModified(page: {
  slugs: string[];
  absolutePath?: string;
}): Date {
  // Prefer the absolute path if fumadocs-mdx resolved it
  if (page.absolutePath) {
    try {
      return statSync(page.absolutePath).mtime;
    } catch {
      // fall through
    }
  }

  // Fallback: reconstruct path from slugs
  const slug = page.slugs.join("/");
  const candidates = slug
    ? [join(contentDir, `${slug}.mdx`), join(contentDir, slug, "index.mdx")]
    : [join(contentDir, "index.mdx")];

  for (const candidate of candidates) {
    try {
      return statSync(candidate).mtime;
    } catch {
      // try next candidate
    }
  }

  return new Date();
}

export default function sitemap(): MetadataRoute.Sitemap {
  const docsPages = source.getPages().map((page) => ({
    url: `${siteOrigin}${page.url}`,
    lastModified: pageLastModified(page),
    changeFrequency: "weekly" as const,
    priority: pagePriority(page),
  }));

  return [
    {
      url: siteOrigin,
      lastModified: new Date(),
      changeFrequency: "weekly",
      priority: 1,
    },
    ...docsPages,
  ];
}
