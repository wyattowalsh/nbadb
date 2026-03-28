"use client";

import Link from "next/link";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <main className="flex min-h-[80vh] flex-col items-center justify-center px-4 text-center">
      <div className="mx-auto max-w-lg">
        <p className="nba-kicker">Turnover</p>

        <h1 className="nba-display mt-2 text-3xl font-bold tracking-tight text-foreground sm:text-4xl">
          Something went wrong
        </h1>

        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          An unexpected error occurred while rendering this page.
          {error.digest && (
            <span className="mt-1 block font-mono text-xs text-muted-foreground/70">
              Error ID: {error.digest}
            </span>
          )}
        </p>

        <div className="mt-8 flex items-center justify-center gap-3">
          <button
            onClick={reset}
            type="button"
            className="inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-muted"
          >
            Try again
          </button>

          <Link
            href="/"
            className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary/90"
          >
            Back to home
          </Link>
        </div>
      </div>
    </main>
  );
}
