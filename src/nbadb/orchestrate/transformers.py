from __future__ import annotations

import importlib
import pkgutil
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from nbadb.transform.base import BaseTransformer


_TRANSFORM_PACKAGES = [
    "nbadb.transform.dimensions",
    "nbadb.transform.facts",
    "nbadb.transform.derived",
    "nbadb.transform.views",
]


def discover_all_transformers() -> list[BaseTransformer]:
    """Auto-discover and instantiate all transformer classes.

    Walks the four transform sub-packages and collects every
    concrete ``BaseTransformer`` subclass that defines an
    ``output_table``.
    """
    from nbadb.transform.base import BaseTransformer as BaseTF

    transformers_by_output: dict[str, BaseTransformer] = {}
    seen: set[type] = set()

    for package_name in _TRANSFORM_PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except ImportError:
            logger.warning(
                "cannot import transform package: {}",
                package_name,
            )
            continue

        for _, module_name, _ in pkgutil.walk_packages(package.__path__, prefix=f"{package_name}."):
            try:
                module = importlib.import_module(module_name)
            except ImportError as exc:
                logger.warning("cannot import {}: {}", module_name, exc)
                continue

            for attr in dir(module):
                cls = getattr(module, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, BaseTF)
                    and cls is not BaseTF
                    and hasattr(cls, "output_table")
                    and cls not in seen
                ):
                    output_table = cls.output_table
                    if not isinstance(output_table, str) or not output_table:
                        continue
                    candidate = cls()
                    existing = transformers_by_output.get(output_table)
                    if existing is None or (
                        existing.__class__.__module__.endswith("._registry")
                        and not cls.__module__.endswith("._registry")
                    ):
                        transformers_by_output[output_table] = candidate
                    seen.add(cls)

    transformers = list(transformers_by_output.values())
    logger.info(
        "discovered {} transformers across {} packages",
        len(transformers),
        len(_TRANSFORM_PACKAGES),
    )
    return transformers
