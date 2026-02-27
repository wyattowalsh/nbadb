import Link from "next/link";

export default function HomePage() {
  return (
    <main className="flex flex-1 flex-col items-center justify-center px-4 py-16 text-center">
      <h1 className="mb-4 text-4xl font-bold tracking-tight">nbadb</h1>
      <p className="mb-8 max-w-xl text-lg text-fd-muted-foreground">
        Comprehensive NBA database: 131 API endpoints normalized into a star
        schema with 58 tables. Available as SQLite, DuckDB, Parquet, and CSV.
      </p>
      <div className="flex gap-4">
        <Link
          href="/docs"
          className="rounded-lg bg-fd-primary px-6 py-3 text-sm font-medium text-fd-primary-foreground transition-colors hover:bg-fd-primary/90"
        >
          Documentation
        </Link>
        <a
          href="https://www.kaggle.com/datasets/wyattowalsh/basketball"
          target="_blank"
          rel="noopener noreferrer"
          className="rounded-lg border border-fd-border px-6 py-3 text-sm font-medium transition-colors hover:bg-fd-accent"
        >
          Kaggle Dataset
        </a>
      </div>
    </main>
  );
}
