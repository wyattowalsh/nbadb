---
title: Chainlit Plotly Element
kind: raw-source
status: captured
source_url: https://docs.chainlit.io/api-reference/elements/plotly
captured_on: 2026-04-14
capture_type: webfetch-markdown
why_it_matters: Documents how Chainlit renders interactive Plotly figures inside the chat UI, including the supported display modes and the required figure argument.
---

## Source Record

- Source URL: `https://docs.chainlit.io/api-reference/elements/plotly`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

This page defines the `Plotly` UI element for embedding charts in a Chainlit conversation. It matters for any assistant that needs to render interactive analytics, drill-down visuals, or exploratory data views directly in the chat surface.

## Key Excerpts

> "The `Plotly` class allows you to display a Plotly chart in the chatbot UI."

> "The advantage of the `Plotly` element over the `Pyplot` element is that it's interactive"

> "Choices are `side`, `inline`, or `page`."

> "The `plotly.graph_objects.Figure` instance that you want to display."

## Capture Notes

- The page documents four practical parameters: `name`, `display`, `size`, and `figure`.
- `size` only applies when `display=\"inline\"`.
- The example attaches a `cl.Plotly(...)` element to a `cl.Message(...)` before sending it.
