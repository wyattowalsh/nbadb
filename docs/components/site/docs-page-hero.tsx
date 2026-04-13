import Image from "next/image";
import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSectionMeta } from "@/lib/site-config";
import { buildDocHref, getDocBreadcrumbs, humanizeSlug } from "@/lib/utils";

type DocsChromeProps = {
  slug?: string[];
  title: string;
  description?: string;
  tocCount?: number;
  lastUpdatedLabel?: string | null;
  ownershipLabel?: string;
  ownershipHint?: string | null;
};

function DocsPageMeta({
  lastUpdatedLabel,
  ownershipLabel,
  ownershipHint,
}: Pick<
  DocsChromeProps,
  "lastUpdatedLabel" | "ownershipLabel" | "ownershipHint"
>) {
  if (!lastUpdatedLabel && !ownershipLabel) {
    return null;
  }

  return (
    <div className="flex max-w-3xl flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {ownershipLabel && <Badge variant="outline">{ownershipLabel}</Badge>}
      {lastUpdatedLabel && (
        <Badge variant="muted">Updated {lastUpdatedLabel}</Badge>
      )}
      {ownershipHint && <span className="leading-6">{ownershipHint}</span>}
    </div>
  );
}

export function DocsPageHero({
  slug,
  title,
  description,
  tocCount = 0,
  lastUpdatedLabel,
  ownershipLabel,
  ownershipHint,
}: DocsChromeProps) {
  const section = getSectionMeta(slug);
  const breadcrumbs = getDocBreadcrumbs(slug);
  const currentPath = buildDocHref(slug ?? []);
  const currentLabel = slug?.length
    ? humanizeSlug(slug[slug.length - 1])
    : "Index";
  const leadLink =
    currentPath === section.hubHref
      ? section.quickLinks[0]
      : {
          title: section.id === "core" ? "Docs front door" : "Section hub",
          href: section.hubHref,
          description: section.blurb,
        };
  const relatedLinks = section.quickLinks
    .filter((link) => link.href !== currentPath && link.href !== leadLink?.href)
    .slice(0, 2);

  return (
    <section className="nba-page-hero @container">
      <div className="nba-page-hero-shell">
        <div>
          <nav aria-label="Breadcrumb">
            <ol className="flex list-none flex-wrap items-center gap-2 p-0">
              {breadcrumbs.map((crumb, index) => {
                const isCurrent = index === breadcrumbs.length - 1;

                return (
                  <li key={crumb.href} className="flex items-center gap-2">
                    {isCurrent ? (
                      <span aria-current="page" className="nba-crumb-current">
                        {crumb.label}
                      </span>
                    ) : (
                      <Link href={crumb.href} className="nba-crumb-link">
                        {crumb.label}
                      </Link>
                    )}
                    {index < breadcrumbs.length - 1 ? (
                      <span
                        aria-hidden="true"
                        className="text-muted-foreground/60"
                      >
                        /
                      </span>
                    ) : null}
                  </li>
                );
              })}
            </ol>
          </nav>

          <div className="mt-4 space-y-4">
            <div className="flex flex-wrap gap-2">
              <Badge variant="primary">{section.label}</Badge>
              <Badge variant="default">{section.cue}</Badge>
              {tocCount > 0 && (
                <Badge variant="muted">{tocCount} guideposts</Badge>
              )}
            </div>

            <div>
              <p className="nba-kicker">{section.eyebrow}</p>
              <h1 className="mt-3 text-balance text-3xl font-bold tracking-tight text-foreground md:text-4xl">
                {title}
              </h1>
            </div>
            {description && (
              <p className="max-w-3xl text-sm leading-7 text-muted-foreground">
                {description}
              </p>
            )}
            <DocsPageMeta
              lastUpdatedLabel={lastUpdatedLabel}
              ownershipLabel={ownershipLabel}
              ownershipHint={ownershipHint}
            />

            <div className="nba-page-hero-actions">
              {leadLink ? (
                <Button asChild size="sm">
                  <Link href={leadLink.href}>
                    {leadLink.title}
                    <ArrowRight className="size-3.5" />
                  </Link>
                </Button>
              ) : null}

              {relatedLinks.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="nba-page-hero-link"
                >
                  <span>{link.title}</span>
                  <ArrowRight className="size-3.5" />
                </Link>
              ))}
            </div>

            <div className="nba-page-hero-stats">
              {section.stats.map((stat) => (
                <div key={stat.label} className="nba-page-hero-stat-card">
                  <span className="nba-page-hero-stat-value">{stat.value}</span>
                  <span className="nba-page-hero-stat-label">{stat.label}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="nba-page-hero-mark" aria-hidden="true">
          <Image
            src="/logo-600.png"
            alt=""
            width={600}
            height={600}
            className="h-auto w-full"
            priority
          />
          <div className="nba-page-hero-stat">
            <span className="nba-kicker">{section.cue}</span>
            <span>{currentLabel}</span>
          </div>
        </div>
      </div>
    </section>
  );
}
