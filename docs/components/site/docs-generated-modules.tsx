import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { getGeneratedPageFrame } from "@/lib/site-config";

export function DocsGeneratedModules({ slug }: { slug?: string[] }) {
  const frame = getGeneratedPageFrame(slug);

  if (!frame) {
    return null;
  }

  return (
    <section className="mt-12 space-y-4">
      <div className="flex flex-col gap-3 md:flex-row md:items-end md:justify-between">
        <div>
          <p className="nba-kicker">{frame.modulesEyebrow}</p>
          <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
            {frame.modulesTitle}
          </h2>
          <p className="mt-2 max-w-3xl text-sm leading-6 text-muted-foreground">
            {frame.modulesDescription}
          </p>
        </div>
        <Badge variant="muted">{frame.modules.length} related routes</Badge>
      </div>

      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-3">
        {frame.modules.map((module) => (
          <Link
            key={module.href}
            href={module.href}
            className="nba-related-card group border border-border bg-card p-4 md:p-5 transition-colors hover:bg-muted"
          >
            <div className="flex items-center justify-between gap-3">
              <Badge variant="outline">{module.label}</Badge>
              <ArrowRight className="size-4 text-muted-foreground transition-transform duration-200 group-hover:translate-x-0.5" />
            </div>
            <h3 className="mt-4 text-lg font-semibold tracking-tight text-foreground">
              {module.title}
            </h3>
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              {module.description}
            </p>
          </Link>
        ))}
      </div>
    </section>
  );
}
