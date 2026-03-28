import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";
import { DocsLayout } from "fumadocs-ui/layouts/docs";
import type { LinkItemType } from "fumadocs-ui/layouts/shared";
import {
  DocsNavBadge,
  DocsSidebarBanner,
  DocsSidebarFooter,
} from "@/components/site/docs-shell";
import { source } from "@/lib/source";

const links = [
  {
    text: "Docs",
    url: "/docs",
    active: "nested-url",
    on: "nav",
  },
  {
    text: "Schema",
    url: "/docs/schema",
    active: "nested-url",
    on: "nav",
  },
  {
    text: "Endpoints",
    url: "/docs/endpoints",
    active: "nested-url",
    on: "nav",
  },
  {
    text: "Lineage",
    url: "/docs/lineage",
    active: "nested-url",
    on: "nav",
  },
  {
    text: "Diagrams",
    url: "/docs/diagrams",
    active: "nested-url",
    on: "nav",
  },
  {
    text: "Guides",
    url: "/docs/guides",
    active: "nested-url",
    on: "nav",
  },
  {
    type: "button",
    text: "Kaggle",
    url: "https://www.kaggle.com/datasets/wyattowalsh/basketball",
    external: true,
    on: "nav",
  },
] satisfies LinkItemType[];

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
      links={links}
      nav={{
        title: (
          <Link href="/" className="nba-nav-brand">
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
              <span className="nba-display text-base font-bold tracking-tight">nbadb</span>
              <span className="text-[0.62rem] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                NBA warehouse docs
              </span>
            </span>
          </Link>
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
      {children}
    </DocsLayout>
  );
}
