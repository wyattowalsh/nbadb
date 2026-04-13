import Image from "next/image";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";

const footerLinkClassName =
  "text-muted-foreground transition-colors hover:text-foreground";
const externalLinkProps = {
  target: "_blank",
  rel: "noopener noreferrer",
} as const;

export function DocsFooter() {
  return (
    <footer className="mx-auto w-full max-w-5xl px-4 pb-12 sm:px-6 lg:px-8">
      <div className="border-t border-border pt-8">
        <div className="flex flex-col gap-8 sm:flex-row sm:items-start sm:justify-between">
          <div className="max-w-sm">
            <div className="flex items-center gap-2">
              <Image
                src="/logo-600.png"
                alt=""
                width={600}
                height={600}
                className="h-6 w-auto"
              />
              <span className="nba-display text-base font-bold tracking-tight text-foreground">
                nbadb
              </span>
              <Badge variant="primary">v4</Badge>
            </div>
            <p className="mt-3 text-xs leading-5 text-muted-foreground">
              Star-schema NBA data warehouse documentation. DuckDB-first with
              full endpoint coverage, lineage, and schema docs.
            </p>
          </div>

          <nav
            aria-label="Documentation footer"
            className="flex gap-10 text-xs"
          >
            <div className="space-y-2">
              <span className="nba-kicker">Docs</span>
              <div className="flex flex-col gap-1.5">
                <Link
                  href="/docs/guides/role-based-onboarding-hub"
                  className={footerLinkClassName}
                >
                  Start here
                </Link>
                <Link href="/docs/schema" className={footerLinkClassName}>
                  Schema
                </Link>
                <Link href="/docs/endpoints" className={footerLinkClassName}>
                  Endpoints
                </Link>
                <Link href="/docs/lineage" className={footerLinkClassName}>
                  Lineage
                </Link>
                <Link href="/docs/guides" className={footerLinkClassName}>
                  Guides
                </Link>
                <Link
                  href="/docs/guides/whats-new"
                  className={footerLinkClassName}
                >
                  What&apos;s new
                </Link>
              </div>
            </div>
            <div className="space-y-2">
              <span className="nba-kicker">Resources</span>
              <div className="flex flex-col gap-1.5">
                <a
                  href="https://github.com/wyattowalsh/nbadb"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  GitHub
                </a>
                <a
                  href="https://www.kaggle.com/datasets/wyattowalsh/basketball"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  Kaggle
                </a>
                <a
                  href="https://pypi.org/project/nbadb/"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  PyPI
                </a>
              </div>
            </div>
            <div className="space-y-2">
              <span className="nba-kicker">Built with</span>
              <div className="flex flex-col gap-1.5">
                <a
                  href="https://duckdb.org"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  DuckDB
                </a>
                <a
                  href="https://pola.rs"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  Polars
                </a>
                <a
                  href="https://github.com/swar/nba_api"
                  className={footerLinkClassName}
                  {...externalLinkProps}
                >
                  nba_api
                </a>
              </div>
            </div>
          </nav>
        </div>

        <div className="mt-8 border-t border-border pt-4">
          <p className="text-xs text-muted-foreground">
            Open-source NBA data warehouse documentation.
          </p>
        </div>
      </div>
    </footer>
  );
}
