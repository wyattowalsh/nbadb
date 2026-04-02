"""Optional tracing integration for LangSmith and LangFuse."""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from server.config import ChatSettings

logger = logging.getLogger(__name__)


def setup_tracing(settings: ChatSettings) -> list[Any]:
    """Configure tracing and return callback handlers for the agent.

    Returns a list of LangChain-compatible callback handlers.
    Empty list means no external tracing (Chainlit Step tracing still active).
    """
    match settings.tracing_provider:
        case "none":
            # Ensure LangSmith env vars are cleared if previously set
            os.environ.pop("LANGCHAIN_TRACING_V2", None)
            os.environ.pop("LANGCHAIN_PROJECT", None)
            return []

        case "langsmith":
            # LangSmith auto-instruments via env vars — no extra dep needed.
            # LangGraph traces are sent automatically when these are set.
            api_key = os.environ.get("LANGCHAIN_API_KEY", "")
            if not api_key:
                logger.warning(
                    "tracing_provider=langsmith but LANGCHAIN_API_KEY "
                    "is not set — traces will not be sent"
                )
            os.environ["LANGCHAIN_TRACING_V2"] = "true"
            os.environ.setdefault("LANGCHAIN_PROJECT", "nbadb-chat")
            return []

        case "langfuse":
            try:
                from langfuse.callback import (  # type: ignore[import-untyped]
                    CallbackHandler,
                )
            except ImportError:
                logger.warning(
                    "tracing_provider=langfuse but langfuse is not "
                    "installed — run: uv add 'nbadb-chat[tracing]'"
                )
                return []

            public_key = (
                settings.langfuse_public_key.get_secret_value()
                if settings.langfuse_public_key
                else os.environ.get("LANGFUSE_PUBLIC_KEY", "")
            )
            secret_key = (
                settings.langfuse_secret_key.get_secret_value()
                if settings.langfuse_secret_key
                else os.environ.get("LANGFUSE_SECRET_KEY", "")
            )
            host = settings.langfuse_host or os.environ.get(
                "LANGFUSE_HOST", "https://cloud.langfuse.com"
            )

            if not public_key or not secret_key:
                logger.warning(
                    "tracing_provider=langfuse but keys are not set — "
                    "set langfuse_public_key/langfuse_secret_key in config "
                    "or LANGFUSE_PUBLIC_KEY/LANGFUSE_SECRET_KEY env vars"
                )
                return []

            return [
                CallbackHandler(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
            ]

        case _:
            os.environ.pop("LANGCHAIN_TRACING_V2", None)
            os.environ.pop("LANGCHAIN_PROJECT", None)
            return []
