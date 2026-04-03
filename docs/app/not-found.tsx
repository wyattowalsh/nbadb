import Image from "next/image";
import Link from "next/link";

const helpfulLinks = [
  {
    label: "Documentation home",
    href: "/docs",
    description: "Start from the top",
  },
  {
    label: "Schema reference",
    href: "/docs/schema",
    description: "Tables, columns, relationships",
  },
  {
    label: "Guides",
    href: "/docs/guides",
    description: "Walkthroughs and tutorials",
  },
  {
    label: "Endpoint coverage",
    href: "/docs/endpoints",
    description: "NBA API extractors",
  },
];

export default function NotFound() {
  return (
    <main className="flex min-h-[80vh] flex-col items-center justify-center px-4 text-center">
      <div className="nba-reveal mx-auto max-w-lg">
        <Image
          src="/logo-600.png"
          alt=""
          width={600}
          height={600}
          className="mx-auto h-20 w-auto opacity-40"
          priority
        />

        <p className="nba-kicker mt-6">Technical foul</p>

        <h1 className="nba-display nba-title-gradient mt-2 text-4xl font-bold tracking-tight sm:text-5xl">
          Page Not Found
        </h1>

        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          The page you are looking for does not exist or has been moved. Try
          searching the docs or pick one of the links below.
        </p>

        <div className="mt-8 grid gap-px border border-border sm:grid-cols-2">
          {helpfulLinks.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className="group flex flex-col bg-card px-4 py-3 text-left transition-colors hover:bg-muted"
            >
              <span className="text-sm font-semibold text-foreground group-hover:text-primary">
                {link.label}
              </span>
              <span className="mt-0.5 text-xs text-muted-foreground">
                {link.description}
              </span>
            </Link>
          ))}
        </div>

        <p className="mt-6 text-xs text-muted-foreground">
          If you followed a link here, please{" "}
          <a
            href="https://github.com/wyattowalsh/nbadb/issues/new?template=bug_report.yml"
            className="text-primary underline underline-offset-2 hover:text-foreground"
            target="_blank"
            rel="noopener noreferrer"
          >
            report the broken link
          </a>
          .
        </p>
      </div>
    </main>
  );
}
