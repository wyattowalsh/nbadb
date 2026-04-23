---
title: Game Prediction
kind: raw-source
status: fetch-limited
source_url: https://www.kaggle.com/code/wyattowalsh/nba-game-prediction
captured_on: 2026-04-14
capture_type: metadata-stub
why_it_matters: Game-outcome prediction is a practical benchmark for feature quality, historical coverage, and modeling readiness across team and schedule data.
---

## Source Record

- Notebook title: `Game Prediction`
- Platform: Kaggle notebook
- Owner signal: `wyattowalsh` in the source URL; the public profile page resolves as `Wyatt Walsh | Kaggle`
- Repo listing: published in the repo README under `Kaggle Notebooks`
- Direct capture status: automated fetches did not return the notebook body; Kaggle served a generic page shell or anti-bot challenge instead

## Why It Matters

This notebook likely shows a predictive pipeline for game outcomes using the nbadb warehouse. That makes it relevant as an end-to-end example of turning historical team, player, and context features into a supervised modeling task.

## Key Excerpts

> "Ten analysis notebooks are published on Kaggle, all powered by this dataset."

> "Stacking ensemble model for game outcomes"

## Capture Notes

- `curl` returned Kaggle's generic shell HTML rather than notebook-specific content.
- `trafilatura` failed to download the notebook page.
- `exa` hit reCAPTCHA or returned `CRAWL_NOT_FOUND` for this Kaggle route.
- This note is a failure-aware stub built from the repo README plus public Kaggle profile metadata.
