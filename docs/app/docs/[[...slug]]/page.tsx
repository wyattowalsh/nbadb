import { MDXContent } from "@/components/mdx";
import {
  DocsContextRail,
  DocsGeneratedEntrySurface,
  DocsGeneratedModules,
  DocsGeneratedScanSurface,
  DocsSchemaCoverageSurface,
  DocsPageHero,
} from "@/components/site/docs-shell";
import { getPageLastModified } from "@/lib/admin/content-audit";
import { source } from "@/lib/source";
import { getGeneratedPageFrame, siteName, siteOrigin } from "@/lib/site-config";
import { getDocBreadcrumbs, serializeJsonLd } from "@/lib/utils";
import type { ReactNode } from "react";
import { DocsBody, DocsPage } from "fumadocs-ui/page";
import { notFound } from "next/navigation";

export const dynamicParams = false;

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

function formatLastUpdated(isoDate: string | null): string | null {
  if (!isoDate) {
    return null;
  }

  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
  }).format(new Date(isoDate));
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

export default async function Page(props: {
  params: Promise<{ slug?: string[] }>;
}) {
  const params = await props.params;
  const page = source.getPage(params.slug);
  if (!page) notFound();
  const slug = params.slug ?? [];
  const breadcrumbs = getDocBreadcrumbs(slug);

  const MDX = page.data.body;
  const toc = stripDuplicateTitleHeading(
    page.data.toc as TOCItem[],
    page.data.title,
  );
  const tocCount = toc.length;
  const frame = getGeneratedPageFrame(params.slug);
  const isGeneratedPage = Boolean(frame);
  const lastUpdatedLabel = formatLastUpdated(await getPageLastModified(slug));
  const ownershipLabel = frame ? "Command-owned" : "Hand-authored";
  const ownershipHint = frame
    ? frame.ownershipNote
    : "Edit this page directly when the narrative needs to change.";
  const canonical = page.url;
  const canonicalUrl = `${siteOrigin}${canonical}`;
  const breadcrumbJsonLd = {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    itemListElement: breadcrumbs.map((crumb, index) => ({
      "@type": "ListItem",
      position: index + 1,
      name: crumb.label,
      item: `${siteOrigin}${crumb.href}`,
    })),
  };
  const articleJsonLd = {
    "@context": "https://schema.org",
    "@type": frame ? "TechArticle" : "Article",
    headline: page.data.title,
    description: page.data.description,
    url: canonicalUrl,
    isPartOf: {
      "@type": "WebSite",
      name: siteName,
      url: siteOrigin,
    },
  };

  return (
    <DocsPage toc={toc} full={page.data.full}>
      <div className="nba-docs-page">
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{
            __html: serializeJsonLd(breadcrumbJsonLd),
          }}
        />
        <script
          type="application/ld+json"
          dangerouslySetInnerHTML={{ __html: serializeJsonLd(articleJsonLd) }}
        />
        <DocsPageHero
          slug={params.slug}
          title={page.data.title}
          description={page.data.description}
          tocCount={tocCount}
          lastUpdatedLabel={lastUpdatedLabel}
          ownershipLabel={ownershipLabel}
          ownershipHint={ownershipHint}
        />
        <DocsGeneratedEntrySurface slug={params.slug} />
        <DocsSchemaCoverageSurface slug={params.slug} />
        <DocsGeneratedScanSurface slug={params.slug} toc={toc} />
        {isGeneratedPage ? (
          <DocsContextRail slug={params.slug} priority />
        ) : null}
        <div className="nba-reading-lane">
          <DocsBody>
            <div className="nba-mdx-body">
              <MDXContent Body={MDX} />
            </div>
          </DocsBody>
        </div>
        <DocsGeneratedModules slug={params.slug} />
        {!isGeneratedPage ? <DocsContextRail slug={params.slug} /> : null}
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
