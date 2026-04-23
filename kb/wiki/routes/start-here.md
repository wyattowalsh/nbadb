---
title: Start Here
tags:
  - kb
  - routes
  - onboarding
aliases:
  - Reader Route Hub
kind: overview
status: active
updated: 2026-04-16
source_count: 2
---

# Start Here

Use this note to pick the shortest route for the job you need done today.

| If you need to... | Start with | First win |
| --- | --- | --- |
| Answer an analytics question | [[analyst-route|Analyst Route]] | One working query against `analytics_*`, `agg_*`, or `fact_*` |
| Check freshness, gaps, or reruns | [[operator-route|Operator Route]] | One clean status check and the right refresh decision |
| Change code or docs safely | [[contributor-route|Contributor Route]] | One narrow verification loop and the right contract file |
| Understand the project or share status | [[stakeholder-route|Stakeholder Route]] | One high-level project story or briefing surface |

> [!tip]
> For analytics readers, browser-first is the fastest warm-up when you only need query shape. Local DuckDB is the right next step when you need real rows.

## Fast rules
- Start with `analytics_*`.
- Drop to `agg_*` when you need season or rolling summaries.
- Drop to `fact_*` when you need exact grain.
- Treat `nbadb status --output-format json` as the first operator command, not a later check.

## Open next
- [[analyst-route|Analyst Route]]
- [[operator-route|Operator Route]]
- [[contributor-route|Contributor Route]]
- [[stakeholder-route|Stakeholder Route]]
- [[../topics/analytics-skill-guide|Analytics Skill Guide]]
- [[../topics/query-patterns|Query Patterns]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| root reader routing | `docs/content/docs/index.mdx` | public docs landing |
| analyst/operator route split | `docs/content/docs/start/onboarding.mdx` | role-based guidance |
