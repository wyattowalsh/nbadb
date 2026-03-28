import { statSync } from "node:fs";
import { join } from "node:path";
import type { MetadataRoute } from "next";
import { siteOrigin } from "@/lib/site-config";
import { source } from "@/lib/source";

const contentDir = join(process.cwd(), "content/docs");

/** Known section-index paths that deserve elevated priority. */
const sectionIndexPaths = new Set([
  "/docs",
  "/docs/schema",
  "/docs/endpoints",
  "/docs/guides",
  "/docs/lineage",
  "/docs/diagrams",
  "/docs/data-dictionary",
]);

/**
 * Resolve a page's URL to a priority tier:
 * - /docs (landing): 0.9
 * - Section index pages: 0.8
 * - Regular pages: 0.7
 */
function pagePriority(url: string): number {
  if (url === "/docs") return 0.9;
  if (sectionIndexPaths.has(url)) return 0.8;
  return 0.7;
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
    priority: pagePriority(page.url),
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
