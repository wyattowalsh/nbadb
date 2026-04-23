---
title: Player Archetypes
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-player-archetypes
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: Archetype clustering turns a wide feature space into interpretable player types, which is useful for scouting, roster construction, and similarity search.
---

## Source Record

- Notebook title: `Player Archetypes`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely uses dimensionality reduction and clustering to map players into data-driven role buckets. That matters because it demonstrates how the warehouse can support unsupervised learning and interpretable representation of complex player profiles.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "UMAP + GMM clustering — 8 data-driven player types"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
