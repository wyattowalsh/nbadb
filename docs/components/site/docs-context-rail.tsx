import Link from "next/link";
import { ArrowRight, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getDocsContextRail, getSectionMeta } from "@/lib/site-config";
import { buildDocHref, cn, getDocSlugFromHref } from "@/lib/utils";
import { SearchShortcutKey, SearchTrigger } from "./search-trigger";

export function DocsContextRail({
  slug,
  priority = false,
}: {
  slug?: string[];
  priority?: boolean;
}) {
  const section = getSectionMeta(slug);
  const contextRail = getDocsContextRail(slug);
  const currentPath = buildDocHref(slug ?? []);
  const links = contextRail.links
    .filter((link) => link.href !== currentPath)
    .slice(0, 3);

  const getLinkBadge = (href: string) => {
    if (!href.startsWith("/docs")) {
      return section.label;
    }

    return getSectionMeta(getDocSlugFromHref(href)).label;
  };

  return (
    <section className={cn("space-y-4", priority ? "mt-8" : "mt-12")}>
      <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
        <div>
          <p className="nba-kicker">{contextRail.eyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {contextRail.title}
          </h2>
          <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
            {contextRail.description}
          </p>
        </div>
        <Button
          asChild
          size="sm"
          variant={priority ? "secondary" : "ghost"}
          className="max-sm:hidden"
        >
          <Link href={contextRail.hubHref}>{contextRail.hubLabel}</Link>
        </Button>
      </div>

      <div
        className={cn(
          "grid gap-4",
          priority
            ? "lg:grid-cols-[minmax(18rem,22rem)_minmax(0,1fr)] xl:grid-cols-[minmax(19rem,23rem)_minmax(0,1fr)]"
            : "xl:grid-cols-[minmax(0,1fr)_minmax(18rem,22rem)]",
        )}
      >
        <aside
          className={cn(
            "nba-discovery-panel border border-border p-4 md:p-5",
            priority && "order-first",
          )}
        >
          <div className="flex items-center justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                {priority ? (
                  <Badge variant="default">Fastest route</Badge>
                ) : null}
                <p className="nba-kicker">Search and discovery</p>
              </div>
              <h3 className="mt-2 text-xl font-semibold tracking-tight text-foreground">
                Prompt the surface
              </h3>
            </div>
            <Search className="size-5 text-primary" />
          </div>
          <p className="mt-3 text-sm leading-6 text-muted-foreground">
            {priority
              ? "Start with a seeded prompt or the section hub before you read the full generated artifact."
              : "Open the docs search with a seeded prompt, then branch into the right section without restarting your scan."}
          </p>
          <div className="mt-4 space-y-3">
            {contextRail.prompts.map((prompt) => (
              <SearchTrigger
                key={prompt.query}
                query={prompt.query}
                className="nba-discovery-prompt block w-full border border-border bg-muted px-3 py-3 text-left transition-colors hover:border-primary/30 hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
              >
                <div className="flex items-center justify-between gap-3">
                  <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
                    {prompt.label}
                  </div>
                  <div className="flex items-center gap-2">
                    <SearchShortcutKey className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground" />
                    <ArrowRight className="size-3.5 text-muted-foreground" />
                  </div>
                </div>
                <div className="mt-2 font-mono text-[0.8rem] leading-6 text-foreground">
                  {prompt.query}
                </div>
                <p className="mt-1 text-xs leading-5 text-muted-foreground">
                  {prompt.description}
                </p>
              </SearchTrigger>
            ))}
          </div>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button asChild size="sm" variant="secondary">
              <Link href={contextRail.hubHref}>{contextRail.hubLabel}</Link>
            </Button>
            {links.slice(0, 2).map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="inline-flex items-center gap-2 rounded-full border border-border bg-background/80 px-3 py-1.5 text-xs font-semibold text-foreground transition-colors hover:border-primary/35 hover:text-primary"
              >
                <span>{link.title}</span>
                <ArrowRight className="size-3.5" />
              </Link>
            ))}
          </div>
        </aside>

        <div
          className={cn(
            "grid gap-4",
            priority ? "sm:grid-cols-2 xl:grid-cols-3" : "md:grid-cols-3",
          )}
        >
          {links.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="nba-related-card group border border-border bg-card p-4 transition-colors hover:bg-muted"
            >
              <div className="flex items-center justify-between gap-3">
                <Badge variant="outline">{getLinkBadge(link.href)}</Badge>
                <ArrowRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
              </div>
              <h3 className="mt-4 text-base font-semibold tracking-tight text-foreground md:text-lg">
                {link.title}
              </h3>
              <p className="mt-2 text-sm leading-6 text-muted-foreground">
                {link.description}
              </p>
            </Link>
          ))}
        </div>
      </div>
    </section>
  );
}
