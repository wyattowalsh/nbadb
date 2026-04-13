import { humanizeSlug } from "@/lib/utils";

export type GeneratedGroupSeed = {
  key: string;
  label: string;
  description: string;
};

export type GeneratedGroup<T> = GeneratedGroupSeed & {
  items: T[];
};

const GENERATED_STAR_GROUP_LABELS = {
  dim: "Dimensions",
  fact: "Facts",
  bridge: "Bridges",
  agg: "Rollups",
  analytics: "Analytics Views",
} as const;

const GENERATED_STAR_GROUP_ORDER = [
  "dim",
  "fact",
  "bridge",
  "agg",
  "analytics",
] as const;

export function humanizeGeneratedIdentifier(value: string): string {
  return humanizeSlug(value.replace(/_/g, "-"));
}

export function getGeneratedStarGroupKey(name: string): string {
  const [family = "other"] = name.split("_");
  return family;
}

export function getGeneratedStarGroupLabel(key: string): string {
  return (
    GENERATED_STAR_GROUP_LABELS[
      key as keyof typeof GENERATED_STAR_GROUP_LABELS
    ] ?? humanizeGeneratedIdentifier(key)
  );
}

export function getGeneratedSourceGroupKey(name: string): string {
  const normalized = name.replace(/^(raw|stg|staging)_/, "");
  const parts = normalized.split("_").filter(Boolean);

  if (parts.length === 0) {
    return name;
  }

  return parts.slice(0, Math.min(parts.length, 2)).join("_");
}

export function groupGeneratedItems<T>(
  items: T[],
  resolveSeed: (item: T) => GeneratedGroupSeed,
): GeneratedGroup<T>[] {
  const groups = new Map<string, GeneratedGroup<T>>();

  for (const item of items) {
    const seed = resolveSeed(item);
    const existing = groups.get(seed.key);

    if (existing) {
      existing.items.push(item);
      continue;
    }

    groups.set(seed.key, { ...seed, items: [item] });
  }

  return Array.from(groups.values());
}

export function sortGeneratedSourceGroups<
  T extends { items: Array<unknown>; label: string },
>(groups: T[]): T[] {
  return [...groups].sort((left, right) => {
    if (right.items.length !== left.items.length) {
      return right.items.length - left.items.length;
    }

    return left.label.localeCompare(right.label);
  });
}

export function sortGeneratedStarGroups<T extends { key: string; label: string }>(
  groups: T[],
): T[] {
  const rank = new Map<string, number>(
    GENERATED_STAR_GROUP_ORDER.map((groupKey, index) => [groupKey, index]),
  );

  return [...groups].sort((left, right) => {
    const leftRank = rank.get(left.key);
    const rightRank = rank.get(right.key);

    if (leftRank === undefined || rightRank === undefined) {
      return left.label.localeCompare(right.label);
    }

    return leftRank - rightRank;
  });
}
