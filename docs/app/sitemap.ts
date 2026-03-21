import type { MetadataRoute } from "next";
import { siteOrigin } from "@/lib/site-config";
import { source } from "@/lib/source";

export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  const docsPages = source.getPages().map((page) => ({
    url: `${siteOrigin}${page.url}`,
    lastModified,
    changeFrequency: "weekly" as const,
    priority: page.url === "/docs" ? 0.9 : 0.7,
  }));

  return [
    {
      url: siteOrigin,
      lastModified,
      changeFrequency: "weekly",
      priority: 1,
    },
    ...docsPages,
  ];
}