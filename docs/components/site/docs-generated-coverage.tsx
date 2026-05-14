import { Badge } from "@/components/ui/badge";
import schemaCoverage from "@/lib/generated/schema-coverage.json";

type SchemaCoverageSurfaceMeta = {
  eyebrow: string;
  title: string;
  description: string;
};

const schemaCoverageSurfaceMeta: Record<string, SchemaCoverageSurfaceMeta> = {
  schema: {
    eyebrow: "Coverage boundary",
    title:
      "Schema-backed reference coverage is narrower than total lineage coverage",
    description:
      "The generated schema reference layer is intentionally exact, but it does not cover every transform output yet. Use this summary to see what the contract layer currently includes before you assume an output has a schema-backed final-tier reference.",
  },
  "schema/star-reference": {
    eyebrow: "Coverage boundary",
    title:
      "This contract page covers only outputs with generated schema entries",
    description:
      "The star reference is the exact contract layer for outputs that currently have generated schema metadata. Some lineage-tracked outputs still sit outside this reference layer, so absence here is a coverage limit, not proof that an output does not exist.",
  },
  "lineage/lineage-auto": {
    eyebrow: "Coverage boundary",
    title: "Lineage coverage is broader than schema-reference coverage",
    description:
      "This page can list more outputs than the generated schema reference pages because lineage is sourced from transform metadata. The gap below is the current set of outputs that still lack a generated schema-backed contract entry.",
  },
};

function formatCoveragePercent(value: number) {
  return `${new Intl.NumberFormat("en-US", {
    maximumFractionDigits: 1,
  }).format(value)}%`;
}

export function DocsSchemaCoverageSurface({ slug }: { slug?: string[] }) {
  const pageKey = slug?.join("/") ?? "";
  const meta = schemaCoverageSurfaceMeta[pageKey];

  if (!meta) {
    return null;
  }

  const coveredOutputs = schemaCoverage.schema_table_count;
  const totalOutputs = schemaCoverage.lineage_output_count;
  const uncoveredOutputs = schemaCoverage.missing_schema_output_count;
  const coveragePercent =
    totalOutputs === 0 ? 0 : (coveredOutputs / totalOutputs) * 100;
  const exampleOutputs = schemaCoverage.missing_schema_outputs.slice(0, 3);
  const remainingExampleCount = Math.max(
    uncoveredOutputs - exampleOutputs.length,
    0,
  );

  return (
    <section className="mt-8 border border-border bg-card p-4 md:p-5">
      <div className="flex flex-wrap gap-2">
        <Badge variant="primary">Coverage boundary</Badge>
        <Badge variant="default">
          {coveredOutputs} / {totalOutputs} outputs
        </Badge>
        <Badge variant="muted">
          {formatCoveragePercent(coveragePercent)} schema-backed
        </Badge>
      </div>

      <div className="mt-4 space-y-3">
        <p className="nba-kicker">{meta.eyebrow}</p>
        <h2 className="text-2xl font-semibold tracking-tight text-foreground md:text-3xl">
          {meta.title}
        </h2>
        <p className="max-w-3xl text-sm leading-7 text-muted-foreground md:text-base">
          {meta.description}
        </p>
      </div>

      <div className="mt-5 grid gap-3 md:grid-cols-3">
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            What coverage means
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            An output counts as covered only when <code>docs-autogen</code> can
            pair a lineage-tracked output with a generated schema reference
            entry.
          </p>
        </div>
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            What it does not mean
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            The remaining {uncoveredOutputs} outputs may still appear in lineage
            or curated docs, but they do not yet have this schema-backed
            contract layer.
          </p>
        </div>
        <div className="border border-border bg-muted px-3 py-3">
          <div className="text-xs font-semibold uppercase tracking-[0.18em] text-primary">
            Verify current numbers
          </div>
          <p className="mt-2 text-sm leading-6 text-muted-foreground">
            Source of truth:{" "}
            <code>docs/lib/generated/schema-coverage.json</code>. Refresh it
            with{" "}
            <code>uv run nbadb docs-autogen --docs-root docs/content/docs</code>
            .
          </p>
        </div>
      </div>

      {exampleOutputs.length > 0 ? (
        <p className="mt-4 text-xs leading-5 text-muted-foreground">
          Current examples outside this layer:{" "}
          {exampleOutputs.map((output, index) => (
            <span key={output}>
              <code>{output}</code>
              {index < exampleOutputs.length - 1 ? ", " : ""}
            </span>
          ))}
          {remainingExampleCount > 0
            ? `, and ${remainingExampleCount} more.`
            : "."}
        </p>
      ) : null}
    </section>
  );
}
