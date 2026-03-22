from __future__ import annotations

from langchain_core.tools import tool


@tool
def web_fetch(url: str) -> str:
    """Fetch and extract text content from a web page URL.

    Max 10000 characters.
    """
    import httpx
    from trafilatura import extract

    try:
        response = httpx.get(url, timeout=15.0, follow_redirects=True)
        response.raise_for_status()
        text = extract(response.text) or response.text[:10000]
        return text[:10000]
    except httpx.HTTPError as exc:
        return f"Failed to fetch URL: {type(exc).__name__}: {exc}"
