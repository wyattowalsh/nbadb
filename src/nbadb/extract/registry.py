from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass

from loguru import logger

from nbadb.extract.base import BaseExtractor


class EndpointRegistryAuthorityError(RuntimeError):
    """Raised when a frozen endpoint-registry authority is invalid or drifts."""


@dataclass(frozen=True, slots=True)
class EndpointRegistryBinding:
    """Exact class and import identity bound to one endpoint name."""

    endpoint_name: str
    extractor_cls: type[BaseExtractor]
    module: str
    qualname: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.endpoint_name, str)
            or not self.endpoint_name
            or not isinstance(self.extractor_cls, type)
            or getattr(self.extractor_cls, "endpoint_name", None) != self.endpoint_name
            or not isinstance(self.module, str)
            or not self.module
            or self.extractor_cls.__module__ != self.module
            or not isinstance(self.qualname, str)
            or not self.qualname
            or self.extractor_cls.__qualname__ != self.qualname
        ):
            raise EndpointRegistryAuthorityError("endpoint registry binding is invalid")


@dataclass(frozen=True, slots=True)
class EndpointRegistryAuthority:
    """Frozen exact-class authority for a scoped or complete registry inventory."""

    bindings: tuple[EndpointRegistryBinding, ...]
    complete_inventory: bool

    def __post_init__(self) -> None:
        if type(self.bindings) is not tuple or not self.bindings:
            raise EndpointRegistryAuthorityError(
                "endpoint registry authority must bind at least one endpoint"
            )
        if type(self.complete_inventory) is not bool:
            raise EndpointRegistryAuthorityError("complete_inventory must be a boolean")
        if not all(isinstance(binding, EndpointRegistryBinding) for binding in self.bindings):
            raise EndpointRegistryAuthorityError("endpoint registry authority binding is invalid")
        names = tuple(binding.endpoint_name for binding in self.bindings)
        if names != tuple(sorted(names)) or len(names) != len(set(names)):
            raise EndpointRegistryAuthorityError(
                "endpoint registry authority bindings must be sorted and unique"
            )

    @property
    def endpoint_names(self) -> tuple[str, ...]:
        """Return the exact endpoint-name inventory bound by this authority."""

        return tuple(binding.endpoint_name for binding in self.bindings)

    def require_current(
        self,
        registry: EndpointRegistry,
        *,
        required_endpoint_name: str | None = None,
    ) -> None:
        """Fail closed unless the registry still matches every bound class identity."""

        if not isinstance(registry, EndpointRegistry):
            raise EndpointRegistryAuthorityError("endpoint registry is invalid")
        if required_endpoint_name is not None and (
            not isinstance(required_endpoint_name, str)
            or not required_endpoint_name
            or required_endpoint_name not in self.endpoint_names
        ):
            raise EndpointRegistryAuthorityError(
                "requested endpoint is absent from registry authority"
            )
        current_names = tuple(sorted(registry._extractors))
        if self.complete_inventory and current_names != self.endpoint_names:
            raise EndpointRegistryAuthorityError("complete endpoint registry inventory changed")
        for binding in self.bindings:
            current = registry._extractors.get(binding.endpoint_name)
            if current is None:
                raise EndpointRegistryAuthorityError(
                    f"bound endpoint was removed: {binding.endpoint_name}"
                )
            if (
                current is not binding.extractor_cls
                or getattr(current, "endpoint_name", None) != binding.endpoint_name
                or current.__module__ != binding.module
                or current.__qualname__ != binding.qualname
            ):
                raise EndpointRegistryAuthorityError(
                    f"bound endpoint class changed: {binding.endpoint_name}"
                )


class EndpointRegistry:
    def __init__(self) -> None:
        self._extractors: dict[str, type[BaseExtractor]] = {}

    def register[ExtractorT: BaseExtractor](
        self,
        extractor_cls: type[ExtractorT],
    ) -> type[ExtractorT]:
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

    def capture_authority(
        self,
        required_endpoint_names: tuple[str, ...] | None = None,
    ) -> EndpointRegistryAuthority:
        """Capture a scoped authority, or the complete inventory when names are omitted."""

        complete_inventory = required_endpoint_names is None
        if required_endpoint_names is None:
            names = tuple(sorted(self._extractors))
        else:
            if (
                type(required_endpoint_names) is not tuple
                or not required_endpoint_names
                or any(not isinstance(name, str) or not name for name in required_endpoint_names)
                or len(required_endpoint_names) != len(set(required_endpoint_names))
            ):
                raise EndpointRegistryAuthorityError(
                    "required endpoint names must be a nonempty unique tuple"
                )
            names = tuple(sorted(required_endpoint_names))
        if not names:
            raise EndpointRegistryAuthorityError(
                "endpoint registry authority must bind at least one endpoint"
            )
        missing = tuple(name for name in names if name not in self._extractors)
        if missing:
            raise EndpointRegistryAuthorityError(
                f"required endpoint is absent from registry: {missing[0]}"
            )
        return EndpointRegistryAuthority(
            bindings=tuple(
                EndpointRegistryBinding(
                    endpoint_name=name,
                    extractor_cls=self._extractors[name],
                    module=self._extractors[name].__module__,
                    qualname=self._extractors[name].__qualname__,
                )
                for name in names
            ),
            complete_inventory=complete_inventory,
        )

    def discover(
        self,
        package_name: str | tuple[str, ...] = (
            "nbadb.extract.stats",
            "nbadb.extract.static",
            "nbadb.extract.live",
        ),
    ) -> None:
        package_names = (package_name,) if isinstance(package_name, str) else package_name
        for current_package in package_names:
            try:
                package = importlib.import_module(current_package)
            except ImportError:
                logger.warning(f"Cannot import {current_package}")
                continue
            for _, module_name, _ in pkgutil.walk_packages(
                package.__path__,
                prefix=f"{current_package}.",
            ):
                try:
                    importlib.import_module(module_name)
                except ImportError as e:
                    logger.warning(f"Cannot import {module_name}: {e}")

    @property
    def count(self) -> int:
        return len(self._extractors)


registry = EndpointRegistry()
