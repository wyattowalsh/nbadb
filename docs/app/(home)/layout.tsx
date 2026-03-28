import Image from "next/image";
import Link from "next/link";
import type { ReactNode } from "react";

export default function HomeLayout({ children }: { children: ReactNode }) {
  return (
    <>
      <header className="sticky top-0 z-50 border-b border-border bg-background/80 backdrop-blur-sm">
        <nav className="mx-auto flex h-14 max-w-5xl items-center justify-between px-4 sm:px-6 lg:px-8">
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
          <Link
            href="/docs"
            className="text-sm font-medium text-muted-foreground transition-colors hover:text-foreground"
          >
            Docs
          </Link>
        </nav>
      </header>
      {children}
    </>
  );
}
