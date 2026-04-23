---
title: Player Dashboard
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-player-dashboard
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: A player dashboard demonstrates whether the dataset is usable for exploratory analysis and interactive metric comparison, not just static exports or model training.
---

## Source Record

- Notebook title: `Player Dashboard`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely acts as an interactive surface over the dataset rather than a narrow one-off analysis. That makes it a useful reference for discoverability, metric breadth, and how easily the warehouse can feed analyst-facing exploratory tools.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "Interactive explorer with 50+ metrics"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
