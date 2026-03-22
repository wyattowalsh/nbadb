from __future__ import annotations

import socket
from ipaddress import ip_address, ip_network
from urllib.parse import urlparse

from langchain_core.tools import tool

_BLOCKED_NETWORKS = [
    ip_network("10.0.0.0/8"),
    ip_network("172.16.0.0/12"),
    ip_network("192.168.0.0/16"),
    ip_network("169.254.0.0/16"),
    ip_network("127.0.0.0/8"),
    ip_network("100.64.0.0/10"),
    ip_network("::1/128"),
]


def _is_safe_url(url: str) -> str | None:
    """Validate URL is not targeting internal/private networks. Returns error or None."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return f"Only http/https URLs are allowed, got: {parsed.scheme}"
    host = parsed.hostname
    if not host:
        return "No hostname in URL"
    # Check direct IP
    try:
        addr = ip_address(host)
        if any(addr in net for net in _BLOCKED_NETWORKS):
            return "Access to private/internal networks is not allowed"
    except ValueError:
        # Hostname — resolve and check all addresses
        try:
            for _, _, _, _, sockaddr in socket.getaddrinfo(host, None):
                addr = ip_address(sockaddr[0])
                if any(addr in net for net in _BLOCKED_NETWORKS):
                    return f"Host {host} resolves to private address"
        except socket.gaierror:
            return f"Could not resolve hostname: {host}"
    return None


@tool
def web_fetch(url: str) -> str:
    """Fetch and extract text content from a web page URL.

    Only public http/https URLs are allowed. Max 10000 characters.
    """
    import httpx
    from trafilatura import extract

    error = _is_safe_url(url)
    if error:
        return f"URL blocked: {error}"

    try:
        response = httpx.get(
            url,
            timeout=15.0,
            follow_redirects=False,
            headers={"User-Agent": "nbadb-chat/1.0"},
        )
        # Check redirect target for SSRF bypass
        if response.is_redirect:
            location = response.headers.get("location", "")
            redirect_error = _is_safe_url(location)
            if redirect_error:
                return f"Redirect blocked: {redirect_error}"
            response = httpx.get(
                location,
                timeout=15.0,
                follow_redirects=False,
                headers={"User-Agent": "nbadb-chat/1.0"},
            )
        response.raise_for_status()
        text = extract(response.text) or response.text[:10000]
        return text[:10000]
    except httpx.HTTPError as exc:
        return f"Failed to fetch URL: {type(exc).__name__}: {exc}"
