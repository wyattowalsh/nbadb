---
title: "nbadb PyPI Package Page"
kind: raw-source
status: captured
source_url: "https://pypi.org/project/nbadb/"
captured_on: "2026-04-14"
capture_type: package-page-fallback-stub
why_it_matters: "PyPI is the public Python package distribution surface for nbadb: it is where users verify installability, package versioning, Python compatibility, and the existence of a packaged CLI outside the repository itself."
---

## Source Record

- Source: intended public PyPI project page for `nbadb`, with direct fetch attempts blocked by a client challenge
- Scope captured: failure-aware stub covering the target distribution URL, observed blocker text, and fallback evidence from repository packaging metadata
- Capture date: `2026-04-14`

## Why It Matters

PyPI is the package-install surface for nbadb. Even when the repository and docs explain the project well, PyPI is where downstream users confirm that `nbadb` is actually packaged for Python installation and discover the public metadata that backs `pip install nbadb` or `uv add nbadb`.

## Key Excerpts

> Direct fetch blocker from the PyPI page: "Client Challenge" and "JavaScript is disabled in your browser. Please enable JavaScript to proceed."

> `[project] name = "nbadb"` and `version = "4.0.0"`

> `[project.urls]` publishes the surrounding public release surfaces: `Homepage = "https://github.com/wyattowalsh/nbadb"`, `Documentation = "https://nbadb.w4w.dev"`, `Repository = "https://github.com/wyattowalsh/nbadb"`, and `"Kaggle Dataset" = "https://www.kaggle.com/datasets/wyattowalsh/basketball"`

> README install guidance: `pip install nbadb    # or: uv add nbadb`

## Capture Notes

- Direct fetch of `https://pypi.org/project/nbadb/` failed across multiple fetch methods because PyPI returned a JavaScript/client-challenge gate rather than readable project content.
- Fallback evidence from `pyproject.toml` confirms that `nbadb` is packaged as a Python distribution with declared version, Python requirement, console script, and public project URLs.
- README evidence confirms PyPI is an intended public install path even though the live project page could not be captured in this pass.
