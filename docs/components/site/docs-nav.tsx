import Image from "next/image";
import Link from "next/link";
import { ArrowRight, Command, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { getSectionMeta } from "@/lib/site-config";
import { buildDocHref } from "@/lib/utils";
import { SearchShortcutKey, SearchTrigger } from "./search-trigger";

type DocsChromeSlugProps = {
  slug?: string[];
};

export function DocsNavBadge({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);

  return (
    <div className="flex items-center gap-2">
      <Link href={section.hubHref} className="nba-nav-route hidden md:flex">
        <span className="nba-nav-route-section">{section.label}</span>
        <span aria-hidden="true" className="text-muted-foreground/50">
          /
        </span>
        <span className="nba-nav-route-cue">{section.cue}</span>
      </Link>
      <SearchTrigger className="nba-nav-command" aria-label="Open search">
        <Search className="size-3.5 md:hidden" />
        <Command className="hidden size-3.5 md:block" />
        <span className="hidden md:inline">Search</span>
        <SearchShortcutKey className="hidden md:inline" />
      </SearchTrigger>
    </div>
  );
}

export function DocsSidebarBanner({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);
  const currentPath = buildDocHref(slug ?? []);
  const quickLinks = section.quickLinks
    .filter((link) => link.href !== currentPath)
    .slice(0, 2);

  return (
    <div className="nba-sidebar-banner border border-border bg-card p-3">
      <div className="flex items-center justify-between gap-2">
        <span className="flex items-center gap-2 text-[0.65rem] font-semibold uppercase tracking-[0.2em] text-muted-foreground">
          <Image
            src="/android-chrome-192x192.png"
            alt=""
            width={192}
            height={192}
            className="h-4 w-auto"
          />
          nbadb
        </span>
        <Badge variant="default">{section.cue}</Badge>
      </div>
      <div className="mt-3 space-y-3">
        <div>
          <p className="nba-kicker">{section.eyebrow}</p>
          <h2 className="mt-2 text-base font-semibold tracking-tight text-foreground">
            {section.label}
          </h2>
          <p className="mt-2 text-xs leading-5 text-muted-foreground">
            {section.blurb}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          {section.stats.slice(0, 2).map((stat) => (
            <div key={stat.label} className="nba-sidebar-stat">
              <span className="nba-sidebar-stat-value">{stat.value}</span>
              <span className="nba-sidebar-stat-label">{stat.label}</span>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-4 grid gap-2">
        <Button asChild size="sm" className="justify-between">
          <Link href={section.hubHref}>
            {section.id === "core" ? "Docs front door" : "Section hub"}
            <ArrowRight className="size-3.5" />
          </Link>
        </Button>

        {quickLinks.map((link) => (
          <Link
            key={link.href}
            href={link.href}
            className="nba-sidebar-route-link"
          >
            <div className="flex items-start justify-between gap-3">
              <div>
                <div className="nba-sidebar-route-eyebrow">Quick route</div>
                <div className="mt-1 text-sm font-semibold text-foreground">
                  {link.title}
                </div>
              </div>
              <ArrowRight className="mt-0.5 size-3.5 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5 group-hover:text-primary" />
            </div>
            <p className="mt-2 text-xs leading-5 text-muted-foreground">
              {link.description}
            </p>
          </Link>
        ))}
      </div>
    </div>
  );
}

export function DocsSidebarFooter({ slug }: DocsChromeSlugProps) {
  const section = getSectionMeta(slug);
  const searchPrompt = section.prompts[0];

  return (
    <div className="nba-sidebar-footer space-y-2 text-xs">
      <div className="flex flex-wrap gap-2">
        <Badge variant="default">{section.label}</Badge>
        <Badge variant="muted">{section.cue}</Badge>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <a
          href="https://github.com/wyattowalsh/nbadb"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center rounded-full border border-border px-2.5 py-1 font-semibold text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
        >
          GitHub
        </a>
        <a
          href="https://pypi.org/project/nbadb/"
          target="_blank"
          rel="noopener noreferrer"
          className="inline-flex items-center rounded-full border border-border px-2.5 py-1 font-semibold text-muted-foreground transition-colors hover:border-primary/30 hover:text-foreground"
        >
          PyPI
        </a>
      </div>
      <SearchTrigger
        query={searchPrompt.query}
        className="nba-sidebar-prompt block w-full text-left transition-colors hover:border-primary/30 hover:bg-muted/80 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/30"
      >
        <div className="text-[0.68rem] font-semibold uppercase tracking-[0.18em] text-primary">
          Try in search
        </div>
        <div className="mt-1 font-mono text-[0.78rem] text-foreground">
          {searchPrompt.query}
        </div>
      </SearchTrigger>
      <p className="text-muted-foreground">
        <SearchShortcutKey /> to search tables, endpoints, guides, and diagrams.
      </p>
    </div>
  );
}
