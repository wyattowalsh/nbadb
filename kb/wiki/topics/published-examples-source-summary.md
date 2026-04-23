---
title: Published Examples Source Summary
tags:
  - kb
  - topics
  - kaggle
  - examples
aliases:
  - Published Notebook Examples
kind: source-summary
status: active
updated: 2026-04-22
source_count: 10
---

# Published Examples Source Summary

The README lists ten published Kaggle notebooks, but not the warehouse surfaces each one most naturally pulls from.

This note is a companion summary for KB navigation use. It is not a notebook-code audit.

## Source summary by published notebook
| Notebook | URL | README framing | Current warehouse surfaces that best align |
| --- | --- | --- | --- |
| NBA Aging Curves | `https://www.kaggle.com/code/wyattowalsh/nba-aging-curves` | Peak, prime, and decline | `agg_player_season`, `agg_player_career`, `analytics_player_season_complete`, `dim_player` |
| Defense Decoded | `https://www.kaggle.com/code/wyattowalsh/nba-defense-decoded` | Tracking + hustle + synergy PCA | `fact_player_game_tracking`, `fact_player_game_hustle`, `fact_synergy`, `analytics_player_game_complete` |
| Draft Combine Analysis | `https://www.kaggle.com/code/wyattowalsh/nba-draft-combine-analysis` | What measurements predict | `fact_draft`, `fact_draft_combine_detail`, `analytics_draft_value`, `agg_player_career` |
| Game Prediction | `https://www.kaggle.com/code/wyattowalsh/nba-game-prediction` | Ensemble model for outcomes | `analytics_game_summary`, `fact_game_result`, `fact_standings` |
| MVP Predictor | `https://www.kaggle.com/code/wyattowalsh/nba-mvp-predictor` | Explainable MVP prediction | `agg_player_season`, `analytics_player_season_complete` |
| Play-by-Play Insights | `https://www.kaggle.com/code/wyattowalsh/nba-play-by-play-insights` | Win probability and scoring runs | `fact_play_by_play`, `fact_win_probability`, `analytics_clutch_performance` |
| Player Archetypes | `https://www.kaggle.com/code/wyattowalsh/nba-player-archetypes` | UMAP + GMM clustering | `agg_player_season`, `analytics_player_season_complete` |
| Player Dashboard | `https://www.kaggle.com/code/wyattowalsh/nba-player-dashboard` | Interactive explorer | `analytics_player_season_complete`, `analytics_player_game_complete`, `analytics_player_impact` |
| Player Similarity | `https://www.kaggle.com/code/wyattowalsh/nba-player-similarity` | Statistical twin search | `agg_player_season`, `agg_player_career`, `analytics_player_season_complete` |
| Shot Chart Analysis | `https://www.kaggle.com/code/wyattowalsh/nba-shot-chart-analysis` | Geography of scoring | `fact_shot_chart`, `fact_shot_chart_league_averages`, `agg_shot_zones`, `analytics_shooting_efficiency` |

## Practical KB use
Use this note when:
- deciding which warehouse surfaces to mention in docs or demos
- tracing a published example back to likely source tables
- identifying gaps between example-visible tables and the broader warehouse surface

## Provenance
| Claim or section | Raw or canonical material | Notes |
|------------------|---------------------------|-------|
| notebook names, URLs, and one-line descriptions | `README.md` | canonical published examples list |
| notebook capture stubs | `raw/sources/external/published-examples/` | second-wave raw mirror |
| player season and career aggregates | `src/nbadb/transform/derived/` | warehouse surface confirmation |
| analytics convenience surfaces | `src/nbadb/transform/views/` | example-aligned views |
| shot, draft, tracking, and play-by-play facts | `src/nbadb/transform/facts/` | fact-level support |
