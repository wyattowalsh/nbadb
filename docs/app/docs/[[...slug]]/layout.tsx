import Link from "next/link";
import {
  BookOpenText,
  Database,
  LayoutGrid,
  Network,
  Route,
  Trophy,
} from "lucide-react";
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
    icon: <Database className="size-4" />,
  },
  {
    text: "Endpoints",
    url: "/docs/endpoints",
    active: "nested-url",
    on: "nav",
    icon: <Trophy className="size-4" />,
  },
  {
    text: "Lineage",
    url: "/docs/lineage",
    active: "nested-url",
    on: "nav",
    icon: <Network className="size-4" />,
  },
  {
    text: "Diagrams",
    url: "/docs/diagrams",
    active: "nested-url",
    on: "nav",
    icon: <LayoutGrid className="size-4" />,
  },
  {
    text: "Guides",
    url: "/docs/guides",
    active: "nested-url",
    on: "nav",
    icon: <Route className="size-4" />,
  },
  {
    type: "button",
    text: "Kaggle",
    url: "https://www.kaggle.com/datasets/wyattowalsh/basketball",
    external: true,
    on: "nav",
  },
  {
    type: "icon",
    text: "Role-based onboarding",
    label: "Role-based onboarding",
    url: "/docs/guides/role-based-onboarding-hub",
    on: "all",
    icon: <BookOpenText className="size-4" />,
  },
] satisfies LinkItemType[];

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <DocsLayout
      tree={source.pageTree}
      containerProps={{ className: "nba-docs-layout" }}
      links={links}
      nav={{
        title: (
          <Link href="/" className="flex items-center gap-2">
            <span className="nba-display text-lg tracking-tight">nbadb</span>
            <span className="text-[0.68rem] font-semibold uppercase tracking-[0.22em] text-muted-foreground">
              Arena Data Lab
            </span>
          </Link>
        ),
        transparentMode: "top",
        children: <DocsNavBadge />,
      }}
      sidebar={{
        banner: <DocsSidebarBanner />,
        footer: <DocsSidebarFooter />,
        defaultOpenLevel: 1,
      }}
      themeSwitch={{ mode: "light-dark-system" }}
    >
      {children}
    </DocsLayout>
  );
}
