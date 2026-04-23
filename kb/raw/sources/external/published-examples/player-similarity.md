---
title: Player Similarity
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-player-similarity
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: Similarity search is a practical downstream use case for normalized player features and is especially useful for scouting, analogs, and historical comparison.
---

## Source Record

- Notebook title: `Player Similarity`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely shows how the warehouse can be transformed into nearest-neighbor or similarity-style player comparisons. That matters because it is a common analyst and fan workflow that depends on broad, well-aligned player features.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "Find any player's statistical twin"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
