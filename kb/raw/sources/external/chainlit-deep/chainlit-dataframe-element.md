---
title: Chainlit Dataframe Element
kind: raw-source
status: captured
source_url: https://docs.chainlit.io/api-reference/elements/dataframe
captured_on: 2026-04-14
capture_type: webfetch-markdown
why_it_matters: Documents how Chainlit sends pandas DataFrames into the chat UI, which is directly relevant for tabular analytics and inspection workflows.
---

## Source Record

- Source URL: `https://docs.chainlit.io/api-reference/elements/dataframe`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page covers the `Dataframe` element for showing tabular results in the chat interface. It is useful for assistants that need to return inspectable data slices, summaries, or paginated tables without leaving the conversation flow.

## Key Excerpts

> "The `Dataframe` class is designed to send a pandas dataframe to the chatbot user interface."

> "Choices are `side`, `inline`, or `page`."

> "The pandas dataframe instance."

> "elements = [cl.Dataframe(data=df, display=\"inline\", name=\"Dataframe\")]"

## Capture Notes

- The documented payload type is `pd.DataFrame`.
- The example intentionally uses more than 10 rows to exercise UI pagination.
- Like other Chainlit elements, the dataframe is attached to a `Message` and sent as part of the chat response.
