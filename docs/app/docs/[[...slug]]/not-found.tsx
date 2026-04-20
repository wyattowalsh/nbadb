import Link from "next/link";
import { Button } from "@/components/ui/button";

export default function DocsNotFound() {
  return (
    <div className="flex min-h-[40vh] flex-col items-center justify-center gap-4 px-4">
      <p className="nba-kicker">Page not found</p>
      <p className="text-sm text-muted-foreground">
        This page doesn&apos;t exist in the docs.
      </p>
      <Button asChild variant="outline" size="sm">
        <Link href="/docs">Back to docs</Link>
      </Button>
    </div>
  );
}
