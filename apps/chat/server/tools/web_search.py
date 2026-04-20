from __future__ import annotations

from langchain_core.tools import tool


@tool
def web_search(query: str) -> str:
    """Search the web using DuckDuckGo.

    Returns top 5 results with titles, URLs, and snippets.
    """
    from duckduckgo_search import DDGS

    results = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=5):
            results.append(f"**{r['title']}**\n{r['href']}\n{r['body']}\n")
    return "\n---\n".join(results) if results else "No results found."
