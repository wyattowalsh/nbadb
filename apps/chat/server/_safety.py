from __future__ import annotations

try:
    from nbadb.agent.safety import MAX_RESULT_ROWS, QUERY_TIMEOUT_SECONDS, ReadOnlyGuard
except ImportError as e:
    raise ImportError(
        "nbadb must be importable for the chat safety module — "
        "run from the repo root or set PYTHONPATH to include src/"
    ) from e

__all__ = ["ReadOnlyGuard", "MAX_RESULT_ROWS", "QUERY_TIMEOUT_SECONDS"]
