import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { SearchTrigger } from "@/components/site/search-trigger";

const mobileQuickLinks = [
  { href: "/docs/guides/role-based-onboarding-hub", label: "Start here" },
  { href: "/docs/playground", label: "Playground" },
  { href: "/docs/schema", label: "Schema" },
  { href: "/docs/guides/daily-updates", label: "Ops" },
] as const;

export default function HomeLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
        <nav
          aria-label="Home"
          className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6 lg:px-8"
        >
          <Link href="/" className="flex items-center gap-2">
            <Image
              src="/logo-600.png"
              alt="nbadb"
              width={600}
              height={600}
              className="h-7 w-auto"
              priority
            />
            <span className="nba-display text-base font-bold tracking-tight">
              nbadb
            </span>
          </Link>
          <div className="flex items-center gap-2 sm:gap-3">
            <Link
              href="/docs"
              className="rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
            >
              Docs
            </Link>
            <Link
              href="/docs/playground"
              className="hidden rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground sm:inline-flex"
            >
              Playground
            </Link>
            <Link
              href="/docs/guides/role-based-onboarding-hub"
              className="hidden rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground md:inline-flex"
            >
              Start here
            </Link>
            <a
              href="https://github.com/wyattowalsh/nbadb"
              target="_blank"
              rel="noopener noreferrer"
              className="hidden rounded-full px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground lg:inline-flex"
            >
              GitHub
            </a>
            <SearchTrigger
              query="analytics quickstart role based onboarding schema map browser playground"
              className="inline-flex rounded-full border border-border/70 px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:bg-muted/60 hover:text-foreground"
            >
              Search
            </SearchTrigger>
          </div>
        </nav>
        <div className="border-t border-border/70 md:hidden">
          <div className="mx-auto flex max-w-5xl gap-2 overflow-x-auto px-4 py-2 sm:px-6">
            {mobileQuickLinks.map((link) => (
              <Link
                key={link.href}
                href={link.href}
                className="shrink-0 rounded-full border border-border/70 px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:border-primary/30 hover:bg-muted/60 hover:text-foreground"
              >
                {link.label}
              </Link>
            ))}
          </div>
        </div>
      </header>
      {children}
    </>
  );
}
