"""Tests for web search and web fetch tools.

langchain_core is not installed in the main venv, so we stub the ``@tool``
decorator before importing the tool modules.  The web_fetch / web_search
functions are then exercised as plain callables.
"""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Stub langchain_core.tools.tool so the @tool-decorated modules can import.
# Must be set up before any test imports the tool modules.
# ---------------------------------------------------------------------------
_FAKE_LC = ModuleType("langchain_core")
_FAKE_LC_TOOLS = ModuleType("langchain_core.tools")


def _noop_tool(fn=None, **_kwargs):
    """Identity decorator standing in for langchain_core.tools.tool."""
    if fn is not None:
        return fn
    return lambda f: f


_FAKE_LC_TOOLS.tool = _noop_tool  # type: ignore[attr-defined]


@pytest.fixture(autouse=True)
def _patch_langchain():
    """Inject the langchain_core stub for every test in this module."""
    saved = {}
    for key in ("langchain_core", "langchain_core.tools"):
        saved[key] = sys.modules.get(key)
    sys.modules["langchain_core"] = _FAKE_LC
    sys.modules["langchain_core.tools"] = _FAKE_LC_TOOLS
    # Clear cached tool-module imports so they reimport with the stub
    sys.modules.pop("apps.chat.server.tools.web_fetch", None)
    sys.modules.pop("apps.chat.server.tools.web_search", None)
    yield
    # Tear-down: remove tool modules and restore langchain state
    sys.modules.pop("apps.chat.server.tools.web_fetch", None)
    sys.modules.pop("apps.chat.server.tools.web_search", None)
    for key, val in saved.items():
        if val is None:
            sys.modules.pop(key, None)
        else:
            sys.modules[key] = val


# ── URL safety tests (pure logic, no network) ─────────────────────────────


class TestIsSafeUrl:
    """Directly test _is_safe_url validation logic."""

    def test_blocks_file_scheme(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        err = _is_safe_url("file:///etc/passwd")
        assert err is not None
        assert "Only http" in err

    def test_blocks_ftp_scheme(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        err = _is_safe_url("ftp://example.com/file")
        assert err is not None
        assert "Only http" in err

    def test_blocks_loopback_ipv4(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        err = _is_safe_url("http://127.0.0.1:5432/")
        assert err is not None
        assert "private" in err.lower()

    def test_blocks_metadata_endpoint(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        err = _is_safe_url("http://169.254.169.254/latest/meta-data/")
        assert err is not None
        assert "private" in err.lower()

    def test_blocks_10_network(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("http://10.0.0.1/") is not None

    def test_blocks_172_16_network(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("http://172.16.0.1/") is not None

    def test_blocks_192_168_network(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("http://192.168.1.1/") is not None

    def test_blocks_carrier_grade_nat(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("http://100.64.0.1/") is not None

    def test_blocks_ipv4_mapped_ipv6(self):
        """IPv4-mapped IPv6 addresses like ::ffff:127.0.0.1 must be blocked."""
        import socket
        from unittest.mock import patch

        from apps.chat.server.tools.web_fetch import _is_safe_url

        fake_result = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("::ffff:127.0.0.1", 80, 0, 0))]
        with patch("apps.chat.server.tools.web_fetch.socket.getaddrinfo", return_value=fake_result):
            err = _is_safe_url("http://evil.example.com/")
        assert err is not None
        assert "private" in err.lower()

    def test_blocks_ipv6_unique_local(self):
        """IPv6 unique-local addresses (fd00::1) must be blocked."""
        import socket
        from unittest.mock import patch

        from apps.chat.server.tools.web_fetch import _is_safe_url

        fake_result = [(socket.AF_INET6, socket.SOCK_STREAM, 6, "", ("fd00::1", 80, 0, 0))]
        with patch("apps.chat.server.tools.web_fetch.socket.getaddrinfo", return_value=fake_result):
            err = _is_safe_url("http://evil.example.com/")
        assert err is not None
        assert "private" in err.lower()

    def test_allows_public_ip(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("http://8.8.8.8/") is None

    def test_allows_https(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        assert _is_safe_url("https://nba.com/stats") is None

    def test_blocks_no_hostname(self):
        from apps.chat.server.tools.web_fetch import _is_safe_url

        err = _is_safe_url("http:///path")
        assert err is not None
        assert "hostname" in err.lower()


# ── web_fetch as a plain function ──────────────────────────────────────────


class TestWebFetch:
    """Call web_fetch directly (stub removed the @tool decorator).

    httpx and trafilatura are imported inside the function body before the
    safety check runs, so we must stub them in sys.modules.
    """

    @pytest.fixture(autouse=True)
    def _stub_http_deps(self):
        httpx_mock = MagicMock()
        traf_mock = MagicMock()
        saved_httpx = sys.modules.get("httpx")
        saved_traf = sys.modules.get("trafilatura")
        sys.modules.setdefault("httpx", httpx_mock)
        sys.modules.setdefault("trafilatura", traf_mock)
        yield
        if saved_httpx is None:
            sys.modules.pop("httpx", None)
        else:
            sys.modules["httpx"] = saved_httpx
        if saved_traf is None:
            sys.modules.pop("trafilatura", None)
        else:
            sys.modules["trafilatura"] = saved_traf

    def test_blocks_private_url(self):
        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="http://127.0.0.1:8080/secret")
        assert "blocked" in result.lower()

    def test_blocks_file_url(self):
        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="file:///etc/passwd")
        assert "blocked" in result.lower()

    def test_blocks_metadata_ip(self):
        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="http://169.254.169.254/latest/meta-data/")
        assert "blocked" in result.lower()

    def test_redirect_loop_max_hops(self):
        """Verify 'Too many redirects' when redirect chain exceeds MAX_REDIRECTS."""
        import httpx as _real_httpx

        redirect_response = MagicMock()
        redirect_response.is_redirect = True
        redirect_response.headers = {"location": "https://example.com/loop"}

        httpx_mod = sys.modules["httpx"]
        httpx_mod.get = MagicMock(return_value=redirect_response)
        httpx_mod.HTTPError = (
            _real_httpx.HTTPError if hasattr(_real_httpx, "HTTPError") else Exception
        )

        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="https://example.com/start")
        assert result == "Too many redirects"

    def test_error_message_sanitized(self):
        """Verify internal error details are not leaked in the response."""
        httpx_mod = sys.modules["httpx"]

        class FakeHTTPError(Exception):
            pass

        httpx_mod.HTTPError = FakeHTTPError
        httpx_mod.get = MagicMock(
            side_effect=FakeHTTPError("Connection to 10.0.0.5:3306 refused"),
        )

        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="https://example.com/page")
        assert "FakeHTTPError" in result
        assert "10.0.0.5" not in result
        assert "refused" not in result

    def test_content_type_rejection(self):
        """Verify binary content types are rejected."""
        httpx_mod = sys.modules["httpx"]

        ok_response = MagicMock()
        ok_response.is_redirect = False
        ok_response.raise_for_status = MagicMock()
        ok_response.headers = {"content-type": "application/octet-stream"}

        httpx_mod.get = MagicMock(return_value=ok_response)
        httpx_mod.HTTPError = Exception

        from apps.chat.server.tools.web_fetch import web_fetch

        result = web_fetch(url="https://example.com/file.bin")
        assert "Cannot extract text" in result
        assert "application/octet-stream" in result


# ── web_search as a plain function ─────────────────────────────────────────


class TestWebSearch:
    """Call web_search directly with a mocked duckduckgo_search.DDGS."""

    def _setup_ddgs_mock(self, return_value):
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = return_value
        ddgs_mod = MagicMock()
        ddgs_mod.DDGS.return_value = mock_ddgs
        return ddgs_mod

    def test_returns_formatted_results(self):
        ddgs_mod = self._setup_ddgs_mock(
            [
                {
                    "title": "NBA Stats",
                    "href": "https://nba.com/stats",
                    "body": "Official NBA stats",
                },
            ]
        )
        sys.modules["duckduckgo_search"] = ddgs_mod
        try:
            sys.modules.pop("apps.chat.server.tools.web_search", None)
            from apps.chat.server.tools.web_search import web_search

            result = web_search(query="NBA scoring leaders")
            assert "NBA Stats" in result
            assert "nba.com/stats" in result
        finally:
            sys.modules.pop("duckduckgo_search", None)

    def test_handles_empty_results(self):
        ddgs_mod = self._setup_ddgs_mock([])
        sys.modules["duckduckgo_search"] = ddgs_mod
        try:
            sys.modules.pop("apps.chat.server.tools.web_search", None)
            from apps.chat.server.tools.web_search import web_search

            result = web_search(query="nonexistent query xyz")
            assert "No results" in result
        finally:
            sys.modules.pop("duckduckgo_search", None)
