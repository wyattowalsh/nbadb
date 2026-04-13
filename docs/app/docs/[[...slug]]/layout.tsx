import Image from "next/image";
import type { ReactNode } from "react";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import {
  DocsNavBadge,
  DocsSidebarBanner,
  DocsSidebarFooter,
} from "@/components/site/docs-shell";
import { DocsFooter } from "@/components/site/footer";
import { docsNavLinks } from "@/lib/site-config";
import { source } from "@/lib/source";

export default async function Layout({
  children,
  params,
}: {
  children: ReactNode;
  params: Promise<{ slug?: string[] }>;
}) {
  const resolvedParams = await params;

  return (
    <DocsLayout
      tree={source.pageTree}
      containerProps={{ className: "nba-docs-layout" }}
      links={docsNavLinks}
      nav={{
        title: (
          <span className="nba-nav-brand">
            <span className="nba-nav-brand-mark">
              <Image
                src="/logo-600.png"
                alt="nbadb"
                width={600}
                height={600}
                className="h-8 w-auto"
                priority
              />
            </span>
            <span className="flex flex-col leading-none">
              <span className="nba-display text-base font-bold tracking-tight">
                nbadb
              </span>
              <span className="text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                NBA warehouse docs
              </span>
            </span>
          </span>
        ),
        transparentMode: "top",
        children: <DocsNavBadge slug={resolvedParams.slug} />,
      }}
      sidebar={{
        banner: <DocsSidebarBanner slug={resolvedParams.slug} />,
        footer: <DocsSidebarFooter slug={resolvedParams.slug} />,
        defaultOpenLevel: 1,
      }}
      themeSwitch={{ mode: "light-dark-system" }}
    >
      <div
        id="main-content"
        className="flex min-h-[calc(100vh-3.5rem)] flex-col"
      >
        <div className="flex-1">{children}</div>
        <DocsFooter />
      </div>
    </DocsLayout>
  );
}
