import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

export function humanizeSlug(segment: string): string {
  return segment
    .split("-")
    .filter(Boolean)
    .map((token) => {
      if (/^(api|cli|er|mdx|nba|pbp|sql)$/i.test(token)) {
        return token.toUpperCase();
      }

      return token.charAt(0).toUpperCase() + token.slice(1);
    })
    .join(" ");
}

export function buildDocHref(parts: string[]): string {
  return parts.length ? `/docs/${parts.join("/")}` : "/docs";
}

export type DocBreadcrumb = {
  label: string;
  href: string;
};

export function getDocBreadcrumbs(slug?: string[]): DocBreadcrumb[] {
  const breadcrumbs: DocBreadcrumb[] = [{ label: "Docs", href: "/docs" }];

  if (!slug?.length) {
    return breadcrumbs;
  }

  slug.forEach((segment, index) => {
    breadcrumbs.push({
      label: humanizeSlug(segment),
      href: buildDocHref(slug.slice(0, index + 1)),
    });
  });

  return breadcrumbs;
}
