---
title: Play-by-Play Insights
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-play-by-play-insights
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: Play-by-play analysis is one of the clearest ways to demonstrate event-level richness in the warehouse, especially for win probability, runs, and clutch situations.
---

## Source Record

- Notebook title: `Play-by-Play Insights`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely showcases the finest-grained event data in nbadb by turning play-by-play logs into momentum, clutch, and win-probability analysis. That is important for anyone evaluating whether the dataset supports sequence-aware and in-game state modeling.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "Win probability, scoring runs, and clutch analysis"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
