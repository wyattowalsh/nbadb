# NBA Database Schema Guide

This file is a placeholder. Run `nbadb docs-autogen` to generate the full schema
reference, or use the `list_tables` and `describe_table` MCP tools at runtime
to explore the schema interactively.

## Quick Reference

### Dimension Tables (dim_*)
Player, team, season, arena, coach, draft, college, country, position, game type

### Fact Tables (fact_*)
Box scores (traditional, advanced, hustle, misc, scoring, usage, four factors),
player tracking (speed, distance, touches, passes, rebounds, shots),
shot charts, matchups, lineups, synergy, rotations, win probability

### Aggregated Tables (agg_*)
Player season, team season, on/off splits, clutch stats

### Analytics Views (analytics_*)
Player game complete, team season summary
