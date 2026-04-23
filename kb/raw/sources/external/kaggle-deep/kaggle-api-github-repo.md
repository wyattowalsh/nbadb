---
title: Kaggle API GitHub Repository (redirects to kaggle-cli)
kind: raw-source
status: captured
source_url: https://github.com/Kaggle/kaggle-api
captured_on: 2026-04-14
capture_type: webfetch-github-page
why_it_matters:
  - Confirms the maintained Kaggle command-line surface now lives in the `Kaggle/kaggle-cli` repository.
  - Summarizes the official CLI feature set for competitions, datasets, models, and kernels.
---

## Source Record

- Requested URL: `https://github.com/Kaggle/kaggle-api`
- Fetch result: GitHub resolved this page to `Kaggle/kaggle-cli`.
- Repository summary captured from the rendered GitHub repository page.

## Why It Matters

This is the operational source for Kaggle's official CLI behavior. It is the most relevant upstream reference for automation that creates, versions, downloads, or submits Kaggle resources from outside the Kaggle notebook environment.

## Key Excerpts

> "The official CLI to interact with Kaggle."

> "List competitions, download competition data, submit to a competition."

> "List, create, update, download or delete datasets."

> "List, create, update, download or delete models & model variations."

> "List, update & run, download code & output or delete kernels (notebooks)."

> "Install the `kaggle` package with pip: `pip install kaggle`"

## Capture Notes

- The user-provided `kaggle-api` URL appears to be an older entry point; GitHub now serves the official CLI repo as `Kaggle/kaggle-cli`.
- The repo page is useful for high-level capability mapping, but the raw docs files are more precise for metadata contract details.
- The GitHub page also exposed useful maintenance context, including active docs, tests, and a recent release (`2.0.1` shown on the page at capture time).
