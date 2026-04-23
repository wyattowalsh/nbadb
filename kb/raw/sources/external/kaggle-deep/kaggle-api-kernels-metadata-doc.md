---
title: Kaggle Kernel Metadata Contract
kind: raw-source
status: captured
source_url: https://raw.githubusercontent.com/Kaggle/kaggle-api/main/docs/kernels_metadata.md
captured_on: 2026-04-14
capture_type: webfetch-raw-markdown
why_it_matters:
  - Defines the `kernel-metadata.json` contract used to upload and run Kaggle notebooks or scripts.
  - Documents execution settings and source attachment fields needed to reproduce Kaggle notebook environments programmatically.
---

## Source Record

- Requested URL: `https://raw.githubusercontent.com/Kaggle/kaggle-api/main/docs/kernels_metadata.md`
- Fetch result: raw markdown document.
- Captured the kernel metadata field list and example payload.

## Why It Matters

This is the upstream contract for Kaggle notebook automation. It matters for workflows that publish notebooks, reproduce Kaggle execution settings, or map notebook dependencies to dataset, competition, kernel, and model source handles.

## Key Excerpts

> "To upload and run a kernel, a special `kernel-metadata.json` file must be specified."

> "You can also use the API command `kaggle kernels init -p /path/to/kernel` to have the API create this file for you for a new kernel."

> "If you wish to get the metadata for an existing kernel, you can use `kaggle kernels pull ... -m`."

> "`language`: The language your kernel is written in. Valid options are `python`, `r`, and `rmarkdown`."

> "`dataset_sources` ... `competition_sources` ... `kernel_sources` ... `model_sources`"

## Capture Notes

- The document gives the exact fields needed to recreate Kaggle execution settings such as privacy, GPU, and internet access.
- The source attachment arrays are important because they encode the upstream dependencies that a Kaggle notebook expects to see.
- The note about title-slug linkage is operationally important when renaming kernels.
