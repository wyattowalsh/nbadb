"""Typed helpers for extractor class fixtures."""

from __future__ import annotations

from nbadb.extract.base import BaseExtractor

__all__ = ["extractor_type"]


def extractor_type(cls: type) -> type[BaseExtractor]:
    if not isinstance(cls, type) or not issubclass(cls, BaseExtractor):
        raise TypeError(f"{cls!r} is not a BaseExtractor class")
    return cls
