import { execSync } from "node:child_process";
import { MDXContent } from "@/components/mdx";
import {
  DocsContextRail,
  DocsGeneratedEntrySurface,
  DocsGeneratedModules,
  DocsGeneratedScanSurface,
  DocsPageHero,
} from "@/components/site/docs-shell";
import { DocsFooter } from "@/components/site/footer";
import { source } from "@/lib/source";
import { siteName, siteOrigin } from "@/lib/site-config";
import type { ReactNode } from "react";
import { DocsBody, DocsPage } from "fumadocs-ui/page";
import { findNeighbour } from "fumadocs-core/page-tree";
import { notFound } from "next/navigation";

type TOCItem = {
  title: ReactNode;
  url: string;
  depth: number;
};

function tocTitleText(title: ReactNode): string {
  if (typeof title === "string" || typeof title === "number") {
    return String(title);
  }

  return "";
}

function normalizeHeading(text: string): string {
  return text.trim().replace(/\s+/g, " ").toLowerCase();
}

function stripDuplicateTitleHeading(toc: TOCItem[], pageTitle: string) {
  const normalizedPageTitle = normalizeHeading(pageTitle);

  return toc.filter((item) => {
    const isDuplicateTitle =
      item.depth === 1 &&
      normalizeHeading(tocTitleText(item.title)) === normalizedPageTitle;

    return !isDuplicateTitle;
  });
}

/**
 * Resolve a page's last-modified date from git history.
 * Uses git log instead of filesystem mtime so timestamps survive CI builds.
 */
function getGitLastModified(filePath: string): Date | undefined {
  try {
    const result = execSync(
      `git log --format=%aI -1 -- "${filePath}"`,
      { encoding: "utf-8", timeout: 5000 },
    ).trim();
    return result ? new Date(result) : undefined;
  } catch {
    return undefined;
  }
}

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  const MDX = page.data.body;
  const toc = stripDuplicateTitleHeading(
    page.data.toc as TOCItem[],
    page.data.title,
  );

  const neighbours = findNeighbour(source.pageTree, page.url);
  const contentPath = params.slug?.length
    ? `docs/content/docs/${params.slug.join("/")}.mdx`
    : "docs/content/docs/index.mdx";
  const lastModified = getGitLastModified(contentPath);

  return (
    <DocsPage
      toc={toc}
      full={page.data.full}
      footer={{ items: neighbours }}
      editOnGithub={{
        owner: "wyattowalsh",
        repo: "nba-db",
        sha: "main",
        path: `docs/content/docs/${page.path}`,
      }}
      lastUpdate={lastModified}
    >
      <div className="nba-docs-page">
        <DocsPageHero
          slug={params.slug}
          title={page.data.title}
          description={page.data.description}
        />
        <DocsGeneratedEntrySurface slug={params.slug} />
        <DocsGeneratedScanSurface slug={params.slug} toc={toc} />
        <div className="nba-reading-lane">
          <DocsBody>
            <div className="nba-mdx-body">
              <MDXContent Body={MDX} />
            </div>
          </DocsBody>
        </div>
        <DocsGeneratedModules slug={params.slug} />
        <DocsContextRail slug={params.slug} />
        {/* Site footer in content column — intentional (matches docs layout flow) */}
        <DocsFooter />
      </div>
    </DocsPage>
  );
}

export async function generateStaticParams() {
  return source.generateParams();
}

export async function generateMetadata(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();

  const canonical = page.url;
  const ogImagePath = params.slug?.length
    ? `/docs-og/${params.slug.map(encodeURIComponent).join("/")}`
    : "/docs-og";
  const ogImageUrl = `${siteOrigin}${ogImagePath}`;

  return {
    title: page.data.title,
    description: page.data.description,
    alternates: {
      canonical,
    },
    openGraph: {
      type: "article",
      title: page.data.title,
      description: page.data.description,
      url: canonical,
      siteName,
      images: [
        {
          url: ogImageUrl,
          width: 1200,
          height: 630,
          alt: `${page.data.title} — ${siteName}`,
        },
      ],
    },
    twitter: {
      card: "summary_large_image",
      title: page.data.title,
      description: page.data.description,
      images: [ogImageUrl],
    },
  };
}
