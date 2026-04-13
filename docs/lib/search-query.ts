const SEARCH_ALIASES = {
  ppg: ["points per game", "scoring average"],
  rpg: ["rebounds per game"],
  apg: ["assists per game"],
  spg: ["steals per game"],
  bpg: ["blocks per game"],
  fg_pct: ["field goal percentage"],
  ts_pct: ["true shooting percentage"],
  bpm: ["box plus minus"],
} as const;

export function expandSearchQuery(query: string): string {
  const expansions = new Set<string>();

  for (const token of query.trim().toLowerCase().split(/\s+/).filter(Boolean)) {
    for (const phrase of SEARCH_ALIASES[token as keyof typeof SEARCH_ALIASES] ??
      []) {
      expansions.add(phrase);
    }
  }

  if (expansions.size === 0) {
    return query;
  }

  return `${query} ${Array.from(expansions).join(" ")}`;
}
