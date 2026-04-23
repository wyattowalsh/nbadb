---
title: Kaggle Dataset Metadata Contract
kind: raw-source
status: captured
source_url: https://raw.githubusercontent.com/Kaggle/kaggle-api/main/docs/datasets_metadata.md
captured_on: 2026-04-14
capture_type: webfetch-raw-markdown
why_it_matters:
  - Defines the `dataset-metadata.json` contract required for dataset create, version, and metadata-update flows.
  - Provides the exact field names, constraints, licenses, data types, and update-frequency enums needed for reliable automation.
---

## Source Record

- Requested URL: `https://raw.githubusercontent.com/Kaggle/kaggle-api/main/docs/datasets_metadata.md`
- Fetch result: raw markdown document.
- Captured the dataset metadata schema and supported values.

## Why It Matters

This is the clearest upstream specification for packaging Kaggle dataset uploads. It matters directly for any tool that emits Kaggle-compatible metadata or validates whether local dataset bundles are ready to create or version through Kaggle.

## Key Excerpts

> "The Kaggle API follows the Data Package specification for specifying metadata when creating new Datasets and Dataset versions."

> "Next to your files, you have to put a special `dataset-metadata.json` file in your upload folder."

> "You can also use the API command `kaggle datasets init -p /path/to/dataset` to have the API create this file for you."

> "`licenses`: Must have exactly one entry that specifies the license."

> "`expectedUpdateFrequency`: How often you expect to update your dataset with new versions."

## Capture Notes

- The document is especially valuable because it separates supported fields by command: `datasets create`, `datasets version`, and `datasets metadata --update`.
- It includes a practical warning that `resources.schema.fields` currently need to include all fields in order for matching to work correctly.
- The enumerated license names, data types, and update frequencies are useful for schema-level validation in downstream tools.
