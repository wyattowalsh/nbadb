import { clsx, type ClassValue } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function humanizeSlug(segment: string): string {
  return segment
    .split("-")
    .filter(Boolean)
    .map((token) => {
      if (/^(api|cli|er|mdx|nba|pbp|sql)$/i.test(token)) {
        return token.toUpperCase()
      }
      return token.charAt(0).toUpperCase() + token.slice(1)
    })
    .join(" ")
}

/** Format milliseconds as human-readable latency (e.g., 1200 -> "1.2s") */
export function formatLatency(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${(ms / 1000).toFixed(1)}s`;
  return `${(ms / 60_000).toFixed(1)}m`;
}

export function buildDocHref(parts: string[]): string {
  return parts.length ? `/docs/${parts.join("/")}` : "/docs"
}

export type DocBreadcrumb = {
  label: string
  href: string
  /** When false the segment has no backing page and should render as plain text. */
  hasPage: boolean
}

/**
 * Build breadcrumbs for a docs page.
 *
 * @param slug    - the current page slug segments
 * @param validPaths - optional set of known routable paths (e.g. "/docs/guides").
 *                     When provided, intermediate segments not in the set get
 *                     `hasPage: false` so the consumer can render them as plain
 *                     text instead of links, preventing 404 navigation.
 *                     The final (current-page) segment always gets `hasPage: true`.
 */
export function getDocBreadcrumbs(
  slug?: string[],
  validPaths?: ReadonlySet<string>,
): DocBreadcrumb[] {
  const breadcrumbs: DocBreadcrumb[] = [
    { label: "Docs", href: "/docs", hasPage: true },
  ]

  if (!slug?.length) {
    return breadcrumbs
  }

  slug.forEach((segment, index) => {
    const href = buildDocHref(slug.slice(0, index + 1))
    const isFinal = index === slug.length - 1
    const hasPage =
      isFinal || !validPaths ? true : validPaths.has(href)

    breadcrumbs.push({
      label: humanizeSlug(segment),
      href,
      hasPage,
    })
  })

  return breadcrumbs
}
