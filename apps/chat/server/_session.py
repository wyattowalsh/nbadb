"""Session ID utilities shared across chat app entry points."""

from __future__ import annotations

import re

_SESSION_ID_RE = re.compile(r"[^a-zA-Z0-9_-]")


def sanitize_session_id(raw: str) -> str:
    """Strip unsafe characters from session ID to prevent path traversal."""
    return _SESSION_ID_RE.sub("", raw)[:128] or "default"
