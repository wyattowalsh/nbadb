---
title: Chainlit on_chat_start Hook
kind: raw-source
status: captured
source_url: https://docs.chainlit.io/api-reference/lifecycle-hooks/on-chat-start
captured_on: 2026-04-14
capture_type: webfetch-markdown
why_it_matters: Documents the lifecycle hook that runs when a user's websocket session starts, which is central to bootstrapping a Chainlit chat experience.
---

## Source Record

- Source URL: `https://docs.chainlit.io/api-reference/lifecycle-hooks/on-chat-start`
- Fetch method: `webfetch` in markdown mode
- Capture date: `2026-04-14`

## Why It Matters

`on_chat_start` is the initialization hook for a Chainlit conversation session. It is the natural place to ask for initial user input, seed session state, send a welcome message, or verify the app's chat flow is wired correctly when a websocket connection opens.

## Key Excerpts

> "Hook to react to the user websocket connection event."

> "@on_chat_start"

> "res = await AskUserMessage(content=\"What is your name?\", timeout=30).send()"

> "await Message(content=f\"Your name is: {res['output']}.\nChainlit installation is working!\nYou can now start building your own chainlit apps!\").send()"

## Capture Notes

- The example uses `AskUserMessage` inside the hook, then responds with a follow-up `Message`.
- The page is concise and focused on the event boundary itself rather than broader session-state patterns.
- The wording makes clear this hook is tied to websocket connection start, not a per-message callback.
