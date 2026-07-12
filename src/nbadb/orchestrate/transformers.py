from __future__ import annotations

import importlib
import pkgutil
from collections import Counter
from typing import TYPE_CHECKING

from loguru import logger

if TYPE_CHECKING:
    from collections.abc import Collection

    from nbadb.transform.base import BaseTransformer


_TRANSFORM_PACKAGES = (
    "nbadb.transform.dimensions",
    "nbadb.transform.facts",
    "nbadb.transform.derived",
    "nbadb.transform.views",
    "nbadb.transform.live",
)
_LIVE_SCHEMA_MODULE = "nbadb.schemas.star.live"


class TransformerDiscoveryError(RuntimeError):
    """Transformer discovery could not prove the complete output universe."""


def _format_output_names(names: Collection[str], *, limit: int = 10) -> str:
    ordered = sorted(names)
    rendered = ", ".join(ordered[:limit])
    if len(ordered) > limit:
        rendered = f"{rendered}, ... (+{len(ordered) - limit} more)"
    return rendered


def expected_transform_output_tables(*, include_live: bool = True) -> frozenset[str]:
    """Return the schema-backed transform output universe for this runtime."""
    try:
        from nbadb.schemas.registry import _star_schema_registry

        schema_registry = _star_schema_registry()
    except Exception as exc:
        raise TransformerDiscoveryError(
            "cannot load the star-schema registry needed to verify transformer discovery: "
            f"{type(exc).__name__}: {exc}"
        ) from exc

    expected = {
        table_name
        for table_name, schema_cls in schema_registry.items()
        if include_live
        or not (
            schema_cls.__module__ == _LIVE_SCHEMA_MODULE
            or schema_cls.__module__.startswith(f"{_LIVE_SCHEMA_MODULE}.")
        )
    }
    if not expected:
        scope = "full" if include_live else "historical"
        raise TransformerDiscoveryError(
            f"the schema-backed {scope} transform output universe is empty"
        )
    return frozenset(expected)


def require_complete_transformer_universe(
    transformers: Collection[BaseTransformer],
    *,
    include_live: bool = True,
) -> None:
    """Raise unless *transformers* exactly matches the schema-backed universe."""
    outputs: list[str] = []
    for transformer in transformers:
        output_table = getattr(transformer, "output_table", None)
        if not isinstance(output_table, str) or not output_table:
            raise TransformerDiscoveryError(
                "discovered transformer has no valid output_table: "
                f"{type(transformer).__module__}.{type(transformer).__qualname__}"
            )
        outputs.append(output_table)

    expected = expected_transform_output_tables(include_live=include_live)
    actual = set(outputs)
    duplicates = {name for name, count in Counter(outputs).items() if count > 1}
    missing = expected - actual
    unexpected = actual - expected
    if not duplicates and not missing and not unexpected:
        return

    scope = "full" if include_live else "historical"
    details = [
        f"discovered={len(outputs)}",
        f"unique={len(actual)}",
        f"expected={len(expected)}",
    ]
    if missing:
        details.append(f"missing=[{_format_output_names(missing)}]")
    if unexpected:
        details.append(f"unexpected=[{_format_output_names(unexpected)}]")
    if duplicates:
        details.append(f"duplicates=[{_format_output_names(duplicates)}]")
    raise TransformerDiscoveryError(
        f"incomplete {scope} transformer discovery: " + "; ".join(details)
    )


def discover_all_transformers(*, include_live: bool = True) -> list[BaseTransformer]:
    """Auto-discover and instantiate all transformer classes.

    Walks the configured transform packages and collects every
    concrete ``BaseTransformer`` subclass that defines an
    ``output_table``.
    """
    from nbadb.transform.base import BaseTransformer as BaseTF

    transformers_by_output: dict[str, BaseTransformer] = {}
    seen: set[type] = set()

    for package_name in _TRANSFORM_PACKAGES:
        try:
            package = importlib.import_module(package_name)
        except Exception as exc:
            raise TransformerDiscoveryError(
                f"cannot import transform package {package_name}: {type(exc).__name__}: {exc}"
            ) from exc

        def _walk_error(module_name: str, *, current_package: str = package_name) -> None:
            raise TransformerDiscoveryError(
                f"cannot import transform subpackage while walking {current_package}: {module_name}"
            )

        try:
            modules = pkgutil.walk_packages(
                package.__path__,
                prefix=f"{package_name}.",
                onerror=_walk_error,
            )
            module_names = [module_name for _, module_name, _ in modules]
        except TransformerDiscoveryError:
            raise
        except Exception as exc:
            raise TransformerDiscoveryError(
                f"cannot enumerate transform package {package_name}: {type(exc).__name__}: {exc}"
            ) from exc

        for module_name in module_names:
            try:
                module = importlib.import_module(module_name)
            except Exception as exc:
                raise TransformerDiscoveryError(
                    f"cannot import transform module {module_name}: {type(exc).__name__}: {exc}"
                ) from exc

            for attr in dir(module):
                cls = getattr(module, attr)
                if (
                    isinstance(cls, type)
                    and issubclass(cls, BaseTF)
                    and cls is not BaseTF
                    and hasattr(cls, "output_table")
                    and cls not in seen
                ):
                    if not include_live and getattr(cls, "is_live_snapshot", False):
                        continue
                    output_table = cls.output_table
                    if not isinstance(output_table, str) or not output_table:
                        continue
                    try:
                        candidate = cls()
                    except Exception as exc:
                        raise TransformerDiscoveryError(
                            f"cannot instantiate transformer {cls.__module__}.{cls.__qualname__}: "
                            f"{type(exc).__name__}: {exc}"
                        ) from exc
                    existing = transformers_by_output.get(output_table)
                    if existing is None or (
                        existing.__class__.__module__.endswith("._registry")
                        and not cls.__module__.endswith("._registry")
                    ):
                        transformers_by_output[output_table] = candidate
                    seen.add(cls)

    transformers = [transformers_by_output[name] for name in sorted(transformers_by_output)]
    require_complete_transformer_universe(transformers, include_live=include_live)
    logger.info(
        "discovered {} transformers across {} packages",
        len(transformers),
        len(_TRANSFORM_PACKAGES),
    )
    return transformers


def discover_live_transformers() -> list[BaseTransformer]:
    return [
        transformer
        for transformer in discover_all_transformers(include_live=True)
        if getattr(transformer, "is_live_snapshot", False)
    ]
