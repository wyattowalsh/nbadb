---
title: MVP Predictor
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-mvp-predictor
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: Award-voting prediction is a high-visibility modeling use case that tests how well the dataset captures elite performance, team context, and narrative-adjacent signals.
---

## Source Record

- Notebook title: `MVP Predictor`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely frames the warehouse as a source for explainable award-prediction features rather than only descriptive analytics. That matters because it demonstrates how nbadb can support interpretable ML questions tied to league awards and elite-player evaluation.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "Explainable ML for MVP voting prediction"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
