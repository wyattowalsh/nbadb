from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nbadb.extract.base import BaseExtractor


class EndpointRegistry:
    def __init__(self) -> None:
        self._extractors: dict[str, type[BaseExtractor]] = {}

    def register(self, extractor_cls: type[BaseExtractor]) -> type[BaseExtractor]:
        self._extractors[extractor_cls.endpoint_name] = extractor_cls
        return extractor_cls

    def get(self, name: str) -> type[BaseExtractor]:
        if name not in self._extractors:
            raise KeyError(f"Unknown endpoint: {name}")
        return self._extractors[name]

    def get_by_category(self, category: str) -> list[type[BaseExtractor]]:
        return [cls for cls in self._extractors.values() if cls.category == category]

    def get_all(self) -> list[type[BaseExtractor]]:
        return list(self._extractors.values())

    def discover(self, package_name: str = "nbadb.extract.stats") -> None:
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning(f"Cannot import {package_name}")
            return
        for _, module_name, _ in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            try:
                importlib.import_module(module_name)
            except ImportError as e:
                logger.warning(f"Cannot import {module_name}: {e}")

    @property
    def count(self) -> int:
        return len(self._extractors)


registry = EndpointRegistry()
