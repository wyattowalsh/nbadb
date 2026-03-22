from __future__ import annotations

try:
    from .factory import create_chat_model
except ImportError:
    from apps.chat.server.providers.factory import create_chat_model

__all__ = ["create_chat_model"]
