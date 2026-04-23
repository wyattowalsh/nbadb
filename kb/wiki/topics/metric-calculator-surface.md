---
title: Metric Calculator Surface
tags:
  - kb
  - topics
  - analytics
  - metrics
  - chat
aliases:
  - Metric Calculator API
  - Analytics Helper Surface
kind: concept
status: active
updated: 2026-04-14
source_count: 7
---

# Metric Calculator Surface

This note describes the lightweight analytics helper exposed to the chat skill as `mc`.

It is a plain Python skill script under `chat/skills/nba-data-analytics/scripts/metric_calculator.py`, then pre-imported into the `run_python` sandbox so the assistant can compute common NBA metrics without re-deriving formulas inline.

## Runtime surface
- The analytics skill documents the API as `metric_calculator as mc`.
- The shared Python preamble inserts the skill `scripts/` directory onto `sys.path` and imports `metric_calculator as mc`.
- Both the MCP sandbox and Copilot backend describe `mc` as a built-in helper available during `run_python` calls.
- The script is intentionally simple: standalone functions, no class wrapper, no package install step.

## What it covers

### Efficiency and rating helpers
| Function | Purpose |
|----------|---------|
| `mc.true_shooting_pct` | `TS% = pts / (2 * (fga + 0.44 * fta))` |
| `mc.effective_fg_pct` | `eFG% = (fgm + 0.5 * fg3m) / fga` |
| `mc.usage_rate` | player share of team possessions used |
| `mc.pace` | possessions per 48 minutes |
| `mc.offensive_rating` | points scored per 100 possessions |
| `mc.defensive_rating` | points allowed per 100 possessions |
| `mc.net_rating` | offensive rating minus defensive rating |

### Possession, per-minute, and play-result helpers
| Function | Purpose |
|----------|---------|
| `mc.possessions` | box-score possession estimate |
| `mc.per_minute` | per-36 or per-48 normalization |
| `mc.game_score` | Hollinger single-game summary metric |
| `mc.assist_to_turnover` | assist/turnover ratio |
| `mc.turnover_pct` | turnovers per play |

### On-floor share helpers
| Function | Purpose |
|----------|---------|
| `mc.rebound_pct` | share of available rebounds |
| `mc.assist_pct` | share of teammate FGs assisted while on floor |
| `mc.steal_pct` | steals per opponent possessions while on floor |
| `mc.block_pct` | blocks per opponent 2PT FGA while on floor |

## Behavioral contract
- Nullable inputs are normalized through the private `_f()` helper: `None -> 0.0`.
- Most zero-denominator cases return `0.0` instead of raising.
- `mc.assist_to_turnover` is the exception: it returns `None` when turnovers are zero, which keeps downstream JSON serialization safe.
- The module is computation-only. It does not query the database, persist state, or format output.

## How the chat skill uses it
1. Pull base rows with `run_sql`.
2. Switch to `run_python`.
3. Compute derived metrics with `mc.*` against the returned DataFrame.
4. Display via `table(df)` or chart with Plotly helpers.

Typical pattern:

```python
df = query("""<sql>""")
df["ts_pct"] = df.apply(
    lambda r: mc.true_shooting_pct(r["pts"], r["fga"], r["fta"]),
    axis=1,
)
table(df)
```

## Boundaries and intent
- Use `mc` for row-level or post-query calculations inside the sandbox.
- Prefer warehouse columns or `analytics_*` / `agg_*` tables first when the metric already exists in SQL.
- Use `analytics_league_benchmarks` rather than `mc` alone when the task needs league-average baselines such as PER- or Win Shares-style approximations.

## Related notes
- [[wiki/topics/analytics-skill-guide|Analytics Skill Guide]]
- [[wiki/topics/chat-surface|Chat Surface]]
- [[wiki/topics/query-patterns|Query Patterns]]
- [[wiki/topics/analytics-skill-source-summary|Analytics Skill Source Summary]]

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| metric helper exists as a standalone skill script | `chat/skills/nba-data-analytics/scripts/metric_calculator.py` | canonical implementation |
| documented `mc.*` API surface | `chat/skills/nba-data-analytics/SKILL.md` | skill-level contract and example function list |
| script directory is injected into sandbox and imported as `mc` | `chat/server/_preamble.py` | runtime preamble used for Python execution |
| Copilot backend exposes `mc (metric_calculator)` in `run_python` | `chat/server/copilot_backend.py` | backend tool description |
| MCP sandbox advertises `mc` as a built-in helper | `chat/mcp_servers/sandbox.py` | tool help text |
| `scripts/metric_calculator.py` is expected as part of the skill surface | `tests/unit/chat/test_agent.py` | existence and SKILL.md coverage tests |
| formula behavior, null coercion, zero guards, and JSON-safe `None` behavior | `tests/unit/chat/test_metric_calculator.py` | behavioral evidence for each public function |
