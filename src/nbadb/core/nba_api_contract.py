from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import re
import subprocess
import textwrap
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, cast

from nbadb.core.field_docs import resolved_field_description
from nbadb.core.nba_api_provenance import verify_nba_api_provider

ContractSource = Literal[
    "expected_data",
    "source_ast",
    "load_response",
    "manual_override",
    "endpoint_analysis_docs",
]
Confidence = Literal["high", "medium", "low"]
ParserKind = Literal["legacy_result_sets", "custom_nested"]
ResponseContractMode = Literal["declared_result_sets", "unknown_dynamic_response"]
ObservedPacketMode = Literal[
    "declared_result_sets_only",
    "fail_closed_json_object_or_legacy_result_sets",
]
ProviderResultInventory = Literal[
    "named_result_sets",
    "endpoint_expected_data_empty_unknown",
]
EndpointDocStatus = Literal[
    "documented_empty_result_inventory",
    "endpoint_doc_absent",
]
PackageExportStatus = Literal["package_exported", "direct_import_only"]
ParameterDefaultAuthority = Literal[
    "provider_literal_or_required_v1",
    "provider_dynamic_default_expression_v1",
]
ParameterValueType = Literal["str", "int", "float", "bool", "NoneType"]

_DYNAMIC_DEFAULT_EXPRESSION_TYPES: dict[str, ParameterValueType] = {
    "GameDate.default": "str",
    "Season.default": "str",
    "SeasonAll.default": "str",
    "SeasonAll_Time.default": "str",
    "SeasonID.default": "str",
    "SeasonYear.default": "int",
}
_DYNAMIC_DEFAULT_CLASS_NAMES = frozenset(
    expression.partition(".")[0] for expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
)


class NbaApiContractDiscoveryError(RuntimeError):
    """Stable, secret-safe failure from exact provider contract discovery."""

    def __init__(self, stage: str, source: str, error_type: str) -> None:
        self.stage = stage
        self.source = source
        self.error_type = (
            error_type if re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", error_type) else "Exception"
        )
        super().__init__(
            "nba_api contract discovery failed: "
            f"stage={stage} source={json.dumps(source)} error_type={self.error_type}"
        )


@dataclass(frozen=True)
class NbaApiResultSetContract:
    runtime_class_name: str
    result_set_index: int
    result_set_name: str | None
    expected_columns: tuple[str, ...]
    source: ContractSource
    confidence: Confidence


@dataclass(frozen=True)
class NbaApiParameterDefaultContract:
    """Stable source authority for one provider constructor default.

    Dynamic provider defaults such as ``GameDate.default`` are evaluated when
    the provider module is imported.  Persisting that ambient value makes an
    otherwise exact release contract change with the calendar.  The contract
    therefore retains the source expression and its observed scalar type while
    deliberately omitting the evaluated value.  Request materialization must
    bind those parameters explicitly.
    """

    name: str
    value: str | int | float | bool | None
    value_type: ParameterValueType
    default_authority: ParameterDefaultAuthority
    default_expression: str


@dataclass(frozen=True)
class NbaApiResponseModeContract:
    """Typed parser admission for one exact stats endpoint contract.

    ``unknown_dynamic_response`` does not assert that any provider result set,
    name, header, row, or nested field exists.  It permits a later adapter to
    retain an exact JSON object and to recognize the generic legacy envelope
    only when that observed packet passes its independent fail-closed grammar.
    """

    runtime_class_name: str
    module_name: str
    endpoint_slug: str
    response_mode: ResponseContractMode
    provider_result_inventory: ProviderResultInventory
    observed_packet_mode: ObservedPacketMode
    endpoint_doc_status: EndpointDocStatus | None
    package_export_status: PackageExportStatus | None
    endpoint_contract_sha256: str

    def to_json(self) -> dict[str, str | None]:
        """Return the complete canonical response-mode authority payload."""

        return {
            "runtime_class_name": self.runtime_class_name,
            "module_name": self.module_name,
            "endpoint_slug": self.endpoint_slug,
            "response_mode": self.response_mode,
            "provider_result_inventory": self.provider_result_inventory,
            "observed_packet_mode": self.observed_packet_mode,
            "endpoint_doc_status": self.endpoint_doc_status,
            "package_export_status": self.package_export_status,
            "endpoint_contract_sha256": self.endpoint_contract_sha256,
        }

    @property
    def authority_sha256(self) -> str:
        """Bind the typed mode and its exact endpoint-contract identity."""

        encoded = json.dumps(
            self.to_json(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class NbaApiEndpointContract:
    runtime_class_name: str
    module_name: str
    endpoint_slug: str | None
    parameters: tuple[str, ...]
    required_parameters: tuple[str, ...]
    nullable_parameters: tuple[str, ...]
    result_sets: tuple[NbaApiResultSetContract, ...]
    deprecated: bool
    warnings: tuple[str, ...]
    parameter_patterns: tuple[tuple[str, str | None], ...] = ()
    endpoint_url: str | None = None
    valid_url: str | None = None
    last_validated_date: str | None = None
    source_path: str | None = None
    source_family: str | None = None
    status: str | None = None
    parameter_defaults: tuple[NbaApiParameterDefaultContract, ...] = ()
    parameter_query_names: tuple[tuple[str, str], ...] = ()
    request_method: str = "GET"
    parser_kind: ParserKind = "legacy_result_sets"

    @property
    def response_contract(self) -> NbaApiResponseModeContract:
        """Return the exact typed response-mode authority for this endpoint."""

        return endpoint_response_mode_contract(self)

    @property
    def response_mode(self) -> ResponseContractMode:
        """Expose the response-mode discriminator used by provider adapters."""

        return self.response_contract.response_mode


@dataclass(frozen=True)
class _UnknownDynamicResponsePin:
    endpoint_contract_sha256: str
    endpoint_doc_status: EndpointDocStatus
    package_export_status: PackageExportStatus


# The pinned release exposes exactly these four endpoint-level
# ``expected_data = {}`` declarations.  They are not equivalent to a named
# result-set declaration whose expected column list is empty.  Full endpoint
# contract digests bind parameters and parser identity as well as the explicit
# class/module/slug tuple below.
_EXACT_UNKNOWN_DYNAMIC_RESPONSE_PINS: dict[tuple[str, str, str], _UnknownDynamicResponsePin] = {
    (
        "VideoDetails",
        "nba_api.stats.endpoints.videodetails",
        "videodetails",
    ): _UnknownDynamicResponsePin(
        endpoint_contract_sha256=(
            "b50a6fdc8978b112fff011711af4ce944411c02be4840c2c1ad0c2f3d2065db0"
        ),
        endpoint_doc_status="documented_empty_result_inventory",
        package_export_status="package_exported",
    ),
    (
        "VideoDetailsAsset",
        "nba_api.stats.endpoints.videodetailsasset",
        "videodetailsasset",
    ): _UnknownDynamicResponsePin(
        endpoint_contract_sha256=(
            "e211f645130087ed25bc93454a8d75a3ac48ae7d85981f15b2fd1a52bbcde609"
        ),
        endpoint_doc_status="documented_empty_result_inventory",
        package_export_status="package_exported",
    ),
    (
        "VideoEvents",
        "nba_api.stats.endpoints.videoevents",
        "videoevents",
    ): _UnknownDynamicResponsePin(
        endpoint_contract_sha256=(
            "6635877fbe55e7e3d1ac42628299bd090cbfc0a3fa70d035c7fdab17785aab87"
        ),
        endpoint_doc_status="documented_empty_result_inventory",
        package_export_status="package_exported",
    ),
    (
        "VideoEventsAsset",
        "nba_api.stats.endpoints.videoeventsasset",
        "videoeventsasset",
    ): _UnknownDynamicResponsePin(
        endpoint_contract_sha256=(
            "983ff8abdba00ec041a13fac6da9b93ffac695693224e46f5c5152df3f0760d3"
        ),
        endpoint_doc_status="endpoint_doc_absent",
        package_export_status="direct_import_only",
    ),
}
_UNKNOWN_DYNAMIC_RUNTIME_CLASS_NAMES = frozenset(
    identity[0] for identity in _EXACT_UNKNOWN_DYNAMIC_RESPONSE_PINS
)
_UNKNOWN_DYNAMIC_MODULE_NAMES = frozenset(
    identity[1] for identity in _EXACT_UNKNOWN_DYNAMIC_RESPONSE_PINS
)
_UNKNOWN_DYNAMIC_ENDPOINT_SLUGS = frozenset(
    identity[2] for identity in _EXACT_UNKNOWN_DYNAMIC_RESPONSE_PINS
)


_AUX_PARAMETER_NAMES = {"proxy", "headers", "timeout", "get_request"}


def _discovery_error(
    stage: str,
    source: str,
    error: BaseException | str,
) -> NbaApiContractDiscoveryError:
    error_type = error if isinstance(error, str) else type(error).__name__
    return NbaApiContractDiscoveryError(stage, source, error_type)


def _read_discovery_text(path: Path, *, stage: str, source: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise _discovery_error(stage, source, exc) from exc


def _read_discovery_bytes(path: Path, *, stage: str, source: str) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise _discovery_error(stage, source, exc) from exc


def _runtime_source_path(runtime_cls: type, *, stage: str) -> tuple[Path, str]:
    source = f"{runtime_cls.__module__}.{runtime_cls.__name__}"
    try:
        raw_path = inspect.getsourcefile(runtime_cls)
    except TypeError as exc:
        raise _discovery_error(stage, source, exc) from exc
    if not raw_path:
        raise _discovery_error(stage, source, "FileNotFoundError")
    path = Path(raw_path)
    if not path.is_file():
        raise _discovery_error(stage, source, "FileNotFoundError")
    return path, source


def _import_discovery_module(module_name: str, *, stage: str) -> Any:
    try:
        return importlib.import_module(module_name)
    except Exception as exc:
        raise _discovery_error(stage, module_name, exc) from exc


def _package_module_inventory(package_name: str, *, stage: str) -> tuple[Any, tuple[str, ...]]:
    package = _import_discovery_module(package_name, stage=f"{stage}_package_import")
    package_path = getattr(package, "__path__", None)
    if package_path is None:
        raise _discovery_error(stage, package_name, "AttributeError")
    try:
        package_roots = tuple(Path(item) for item in package_path)
    except (TypeError, ValueError) as exc:
        raise _discovery_error(stage, package_name, exc) from exc
    if not package_roots:
        raise _discovery_error(stage, package_name, "InventoryMismatch")

    physical_names: set[str] = set()
    for package_root in package_roots:
        try:
            children = tuple(package_root.iterdir())
        except OSError as exc:
            raise _discovery_error(stage, package_name, exc) from exc
        for child in children:
            try:
                if child.is_file() and child.suffix == ".py" and child.name != "__init__.py":
                    physical_names.add(child.stem)
                elif child.is_dir() and child.joinpath("__init__.py").is_file():
                    physical_names.add(child.name)
            except OSError as exc:
                raise _discovery_error(stage, package_name, exc) from exc

    try:
        iterated_names = tuple(module.name for module in pkgutil.iter_modules(package_path))
    except Exception as exc:
        raise _discovery_error(stage, package_name, exc) from exc
    if (
        not physical_names
        or len(iterated_names) != len(set(iterated_names))
        or set(iterated_names) != physical_names
    ):
        raise _discovery_error(stage, package_name, "InventoryMismatch")

    declared_names = getattr(package, "__all__", None)
    if (
        not isinstance(declared_names, list | tuple)
        or not declared_names
        or any(not isinstance(name, str) or not name for name in declared_names)
        or not set(declared_names) <= physical_names
    ):
        raise _discovery_error(stage, package_name, "InventoryMismatch")
    return package, tuple(sorted(physical_names))


# Exact declaration/parser differences independently established from the
# immutable v1.11.4 parser fixtures.  They are contract data, not extractor
# index workarounds, and are consumed by both generation and runtime.
PINNED_PROVIDER_COLUMN_INSERTIONS: dict[tuple[str, str], tuple[tuple[int, str], ...]] = {
    ("playbyplayv3", "PlayByPlay"): ((22, "shotValue"),),
    ("boxscoreplayertrackv3", "TeamStats"): ((7, "speed"),),
}


def _validated_custom_parser_registry() -> dict[str, type]:
    _parsers = _import_discovery_module(
        "nba_api.stats.endpoints._parsers",
        stage="stats_parser_registry_import",
    )
    registry = getattr(_parsers, "_PARSER_REGISTRY", None)
    if not isinstance(registry, dict) or not registry:
        raise _discovery_error(
            "stats_parser_registry_inventory",
            "nba_api.stats.endpoints._parsers",
            "InventoryMismatch",
        )
    if any(
        not isinstance(slug, str)
        or not slug
        or not inspect.isclass(parser_cls)
        or not parser_cls.__module__.startswith("nba_api.stats.endpoints._parsers.")
        for slug, parser_cls in registry.items()
    ):
        raise _discovery_error(
            "stats_parser_registry_inventory",
            "nba_api.stats.endpoints._parsers",
            "InventoryMismatch",
        )
    return cast("dict[str, type]", registry)


@lru_cache(maxsize=1)
def custom_parser_endpoint_slugs() -> frozenset[str]:
    """Return the exact installed parser registry after provider verification."""

    return frozenset(_validated_custom_parser_registry())


def _normalise_expected_data(value: object) -> dict[str, list[str]] | None:
    if not isinstance(value, dict):
        return None

    expected_data: dict[str, list[str]] = {}
    for key, columns in value.items():
        if not isinstance(key, str) or not key or not isinstance(columns, list):
            return None
        if all(isinstance(column, str) and column for column in columns):
            expected_data[key] = [cast("str", column) for column in columns]
            continue
        if columns and all(isinstance(column, dict) for column in columns):
            structured_columns = list(structured_data_set_columns(columns))
            if not structured_columns:
                return None
            expected_data[key] = structured_columns
            continue
        return None
    return expected_data


def _literal_expected_data(node: ast.AST) -> dict[str, list[str]] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None
    return _normalise_expected_data(value)


def _import_binding(
    tree: ast.Module,
    *,
    local_name: str,
    module_name: str,
    symbol_name: str,
) -> bool:
    matches = [
        alias
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == module_name
        for alias in node.names
        if alias.name == symbol_name and (alias.asname or alias.name) == local_name
    ]
    return len(matches) == 1


def _imported_expected_data(
    tree: ast.Module,
    value: ast.AST,
    runtime_cls: type,
    runtime_expected: object,
    expected_data: dict[str, list[str]],
) -> dict[str, list[str]] | None:
    if not isinstance(value, ast.Name):
        return None
    endpoint_module = runtime_cls.__module__.rsplit(".", 1)[-1]
    authority_module_name = f"nba_api.stats.endpoints._expected_data.{endpoint_module}"
    if not _import_binding(
        tree,
        local_name=value.id,
        module_name=authority_module_name,
        symbol_name="_EXPECTED_DATA",
    ):
        return None

    runtime_module = _import_discovery_module(
        runtime_cls.__module__,
        stage="stats_expected_data_runtime_import",
    )
    authority_module = _import_discovery_module(
        authority_module_name,
        stage="stats_expected_data_authority_import",
    )
    if (
        getattr(runtime_module, value.id, None) is not runtime_expected
        or getattr(authority_module, "_EXPECTED_DATA", None) is not runtime_expected
    ):
        return None
    return expected_data


def _parser_expected_data(
    tree: ast.Module,
    value: ast.AST,
    runtime_cls: type,
    runtime_expected: object,
    expected_data: dict[str, list[str]],
) -> dict[str, list[str]] | None:
    if not isinstance(value, ast.Dict) or not value.keys or any(key is None for key in value.keys):
        return None

    runtime_module = _import_discovery_module(
        runtime_cls.__module__,
        stage="stats_parser_expected_data_runtime_import",
    )
    parser_module = _import_discovery_module(
        "nba_api.stats.endpoints._parsers",
        stage="stats_parser_expected_data_authority_import",
    )
    endpoint_slug = getattr(runtime_cls, "endpoint", None)
    registry = _validated_custom_parser_registry()
    registered_parser = registry.get(endpoint_slug) if isinstance(endpoint_slug, str) else None
    if registered_parser is None:
        return None

    resolved: dict[str, list[str]] = {}
    for key_node, columns_node in zip(value.keys, value.values, strict=True):
        if (
            not isinstance(key_node, ast.Constant)
            or not isinstance(key_node.value, str)
            or not key_node.value
            or not isinstance(columns_node, ast.Call)
            or not isinstance(columns_node.func, ast.Name)
            or columns_node.func.id != "list"
            or len(columns_node.args) != 1
            or columns_node.keywords
            or not isinstance(columns_node.args[0], ast.Attribute)
            or not isinstance(columns_node.args[0].value, ast.Name)
        ):
            return None
        parser_name = columns_node.args[0].value.id
        parser_field = columns_node.args[0].attr
        if not _import_binding(
            tree,
            local_name=parser_name,
            module_name="nba_api.stats.endpoints._parsers",
            symbol_name=parser_name,
        ):
            return None
        parser_cls = getattr(parser_module, parser_name, None)
        if (
            parser_cls is not registered_parser
            or getattr(runtime_module, parser_name, None) is not parser_cls
        ):
            return None
        parser_columns = getattr(parser_cls, parser_field, None)
        if (
            not isinstance(parser_columns, list | tuple)
            or not parser_columns
            or any(not isinstance(column, str) or not column for column in parser_columns)
        ):
            return None
        resolved[key_node.value] = list(parser_columns)

    if resolved != expected_data or _normalise_expected_data(runtime_expected) != expected_data:
        return None
    return resolved


def _load_response_result_set_names(class_node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "load_response":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Subscript):
                continue
            if not isinstance(child.value, ast.Name) or child.value.id != "data_sets":
                continue
            slice_node = child.slice
            if (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, str)
                and slice_node.value not in names
            ):
                names.append(slice_node.value)
    return names


def _source_contract(runtime_cls: type) -> tuple[dict[str, list[str]], tuple[str, ...]]:
    source_path, source = _runtime_source_path(runtime_cls, stage="stats_source_lookup")
    source_text = _read_discovery_text(
        source_path,
        stage="stats_source_read",
        source=source,
    )
    try:
        tree = ast.parse(source_text, filename=source)
    except SyntaxError as exc:
        raise _discovery_error("stats_source_parse", source, exc) from exc
    runtime_expected = getattr(runtime_cls, "expected_data", None)
    normalised_runtime_expected = _normalise_expected_data(runtime_expected)
    if normalised_runtime_expected is None:
        raise _discovery_error(
            "stats_expected_data_inventory",
            source,
            "InvalidContract",
        )

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != runtime_cls.__name__:
            continue
        expected_data: dict[str, list[str]] = {}
        for child in node.body:
            if not isinstance(child, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "expected_data"
                for target in child.targets
            ):
                continue
            literal_expected_data = _literal_expected_data(child.value)
            if literal_expected_data is not None:
                expected_data = literal_expected_data
            else:
                modeled_expected_data = _imported_expected_data(
                    tree,
                    child.value,
                    runtime_cls,
                    runtime_expected,
                    normalised_runtime_expected,
                )
                if modeled_expected_data is None:
                    modeled_expected_data = _parser_expected_data(
                        tree,
                        child.value,
                        runtime_cls,
                        runtime_expected,
                        normalised_runtime_expected,
                    )
                if modeled_expected_data is not None:
                    expected_data = modeled_expected_data
            if expected_data != normalised_runtime_expected:
                raise _discovery_error(
                    "stats_expected_data_inventory",
                    source,
                    "InvalidContract",
                )
            break
        else:
            raise _discovery_error(
                "stats_expected_data_inventory",
                source,
                "InvalidContract",
            )
        return expected_data, tuple(_load_response_result_set_names(node))
    raise _discovery_error("stats_source_inventory", source, "InvalidContract")


def _endpoint_parameters(
    runtime_cls: type,
) -> tuple[
    tuple[str, ...],
    tuple[str, ...],
    tuple[str, ...],
    tuple[NbaApiParameterDefaultContract, ...],
]:
    try:
        signature = inspect.signature(runtime_cls.__init__)
    except (TypeError, ValueError) as exc:
        source = f"{runtime_cls.__module__}.{runtime_cls.__name__}"
        raise _discovery_error("stats_signature_inventory", source, exc) from exc

    parameters: list[str] = []
    required: list[str] = []
    nullable: list[str] = []
    raw_defaults: list[tuple[str, str | int | float | bool | None]] = []
    for name, parameter in signature.parameters.items():
        if name == "self" or name in _AUX_PARAMETER_NAMES:
            continue
        parameters.append(name)
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        elif isinstance(parameter.default, str | int | float | bool) or parameter.default is None:
            raw_defaults.append((name, parameter.default))
        else:
            raise TypeError(
                f"unsupported nba_api default type for {runtime_cls.__name__}.{name}: "
                f"{type(parameter.default).__name__}"
            )
        if parameter.default is None or name.endswith("_nullable"):
            nullable.append(name)
    default_expressions = _constructor_default_expressions(runtime_cls, tuple(parameters))
    defaults = tuple(
        _parameter_default_contract(
            runtime_cls=runtime_cls,
            name=name,
            raw_default=raw_default,
            source_expression=default_expressions[name],
        )
        for name, raw_default in raw_defaults
    )
    return tuple(parameters), tuple(required), tuple(nullable), defaults


def _constructor_default_expressions(
    runtime_cls: type,
    expected_parameters: tuple[str, ...],
) -> dict[str, str | None]:
    """Read exact default expressions without persisting ambient evaluations."""

    source = f"{runtime_cls.__module__}.{runtime_cls.__name__}.__init__"
    try:
        function_source = textwrap.dedent(inspect.getsource(runtime_cls.__init__))
        tree = ast.parse(function_source, filename=source)
    except (IndentationError, OSError, SyntaxError, TypeError) as exc:
        raise _discovery_error("stats_parameter_default_source", source, exc) from exc
    functions = [
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "__init__"
    ]
    if len(functions) != 1:
        raise _discovery_error(
            "stats_parameter_default_inventory",
            source,
            "InventoryMismatch",
        )
    function = functions[0]
    positional = (*function.args.posonlyargs, *function.args.args)
    positional_names = tuple(argument.arg for argument in positional)
    keyword_names = tuple(argument.arg for argument in function.args.kwonlyargs)
    declared = tuple(
        name
        for name in (*positional_names, *keyword_names)
        if name != "self" and name not in _AUX_PARAMETER_NAMES
    )
    if declared != expected_parameters:
        raise _discovery_error(
            "stats_parameter_default_inventory",
            source,
            "InventoryMismatch",
        )

    defaults: dict[str, ast.expr | None] = dict.fromkeys(
        (*positional_names, *keyword_names),
        None,
    )
    positional_with_defaults = (
        positional[-len(function.args.defaults) :] if function.args.defaults else ()
    )
    for argument, default in zip(
        positional_with_defaults,
        function.args.defaults,
        strict=True,
    ):
        defaults[argument.arg] = default
    for argument, default in zip(
        function.args.kwonlyargs,
        function.args.kw_defaults,
        strict=True,
    ):
        defaults[argument.arg] = default
    return {
        name: ast.unparse(default) if (default := defaults[name]) is not None else None
        for name in expected_parameters
    }


def _parameter_default_contract(
    *,
    runtime_cls: type,
    name: str,
    raw_default: str | int | float | bool | None,
    source_expression: str | None,
) -> NbaApiParameterDefaultContract:
    value_type = type(raw_default).__name__
    if value_type not in {"str", "int", "float", "bool", "NoneType"}:
        raise _discovery_error(
            "stats_parameter_default_type",
            f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
            "InvalidContract",
        )
    if source_expression is None:
        raise _discovery_error(
            "stats_parameter_default_expression",
            f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
            "MissingContract",
        )
    if source_expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES:
        expected_type = _DYNAMIC_DEFAULT_EXPRESSION_TYPES[source_expression]
        if value_type != expected_type:
            raise _discovery_error(
                "stats_parameter_dynamic_default_type",
                f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
                "InvalidContract",
            )
        return NbaApiParameterDefaultContract(
            name=name,
            value=None,
            value_type=expected_type,
            default_authority="provider_dynamic_default_expression_v1",
            default_expression=source_expression,
        )
    expression_owner = source_expression.partition(".")[0] if source_expression else None
    if expression_owner in _DYNAMIC_DEFAULT_CLASS_NAMES:
        raise _discovery_error(
            "stats_parameter_dynamic_default_expression",
            f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
            "UnsupportedContract",
        )
    try:
        literal_value = ast.literal_eval(source_expression)
    except (MemoryError, SyntaxError, TypeError, ValueError):
        literal_value = inspect.Parameter.empty
    if literal_value is not inspect.Parameter.empty:
        if type(literal_value) is not type(raw_default) or literal_value != raw_default:
            raise _discovery_error(
                "stats_parameter_literal_default_value",
                f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
                "InvalidContract",
            )
    else:
        try:
            expression = ast.parse(source_expression, mode="eval").body
        except SyntaxError as exc:
            raise _discovery_error(
                "stats_parameter_default_expression",
                f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
                exc,
            ) from exc
        if not (
            isinstance(expression, ast.Attribute)
            and expression.attr == "default"
            and isinstance(expression.value, ast.Name)
        ):
            raise _discovery_error(
                "stats_parameter_default_expression",
                f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
                "UnsupportedContract",
            )
        provider_default_owner = runtime_cls.__init__.__globals__.get(expression.value.id)
        provider_default = getattr(provider_default_owner, "default", inspect.Parameter.empty)
        if type(provider_default) is not type(raw_default) or provider_default != raw_default:
            raise _discovery_error(
                "stats_parameter_provider_default_value",
                f"{runtime_cls.__module__}.{runtime_cls.__name__}.{name}",
                "InvalidContract",
            )
    return NbaApiParameterDefaultContract(
        name=name,
        value=raw_default,
        value_type=cast("ParameterValueType", value_type),
        default_authority="provider_literal_or_required_v1",
        default_expression=source_expression,
    )


def _endpoint_parameter_query_names(
    runtime_cls: type,
    parameters: tuple[str, ...],
) -> tuple[tuple[str, str], ...]:
    source_path, source = _runtime_source_path(
        runtime_cls,
        stage="stats_parameter_source_lookup",
    )
    source_text = _read_discovery_text(
        source_path,
        stage="stats_parameter_source_read",
        source=source,
    )
    try:
        tree = ast.parse(source_text, filename=source)
    except SyntaxError as exc:
        raise _discovery_error("stats_parameter_source_parse", source, exc) from exc
    class_node = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == runtime_cls.__name__
        ),
        None,
    )
    if class_node is None:
        raise _discovery_error("stats_parameter_source_inventory", source, "InvalidContract")
    mapping: dict[str, str] = {}
    for node in ast.walk(class_node):
        if (
            not isinstance(node, ast.Assign)
            or len(node.targets) != 1
            or not isinstance(node.targets[0], ast.Attribute)
            or not isinstance(node.targets[0].value, ast.Name)
            or node.targets[0].value.id != "self"
            or node.targets[0].attr != "parameters"
            or not isinstance(node.value, ast.Dict)
        ):
            continue
        for key_node, value_node in zip(node.value.keys, node.value.values, strict=True):
            if key_node is None:
                raise _discovery_error(
                    "stats_parameter_query_inventory",
                    source,
                    "InvalidContract",
                )
            try:
                query_name = ast.literal_eval(key_node)
            except (ValueError, TypeError, SyntaxError, MemoryError) as exc:
                raise _discovery_error("stats_parameter_query_inventory", source, exc) from exc
            if not isinstance(query_name, str) or not isinstance(value_node, ast.Name):
                raise _discovery_error(
                    "stats_parameter_query_inventory",
                    source,
                    "InvalidContract",
                )
            mapping[value_node.id] = query_name
    if set(mapping) != set(parameters):
        raise _discovery_error(
            "stats_parameter_query_inventory",
            source,
            "InventoryMismatch",
        )
    return tuple((parameter, mapping[parameter]) for parameter in parameters)


def build_endpoint_contract(runtime_cls: type) -> NbaApiEndpointContract:
    runtime_class_name = runtime_cls.__name__
    source: ContractSource = "expected_data"
    confidence: Confidence = "high"

    expected_data, load_response_names = _source_contract(runtime_cls)
    warnings: list[str] = []
    if load_response_names and expected_data:
        missing_from_expected = [name for name in load_response_names if name not in expected_data]
        if missing_from_expected:
            warnings.append(
                "load_response_result_sets_missing_expected_data:" + ",".join(missing_from_expected)
            )

    endpoint_slug = getattr(runtime_cls, "endpoint", None)
    if isinstance(endpoint_slug, str):
        for result_name, columns in expected_data.items():
            insertions = PINNED_PROVIDER_COLUMN_INSERTIONS.get((endpoint_slug, result_name), ())
            for insertion_index, column in insertions:
                columns.insert(insertion_index, column)
            if insertions:
                warnings.append(f"pinned_provider_column_overlay:{result_name}")

    result_sets = tuple(
        NbaApiResultSetContract(
            runtime_class_name=runtime_class_name,
            result_set_index=index,
            result_set_name=name,
            expected_columns=tuple(columns),
            source=source,
            confidence=confidence,
        )
        for index, (name, columns) in enumerate(expected_data.items())
    )
    parameters, required_parameters, nullable_parameters, parameter_defaults = _endpoint_parameters(
        runtime_cls
    )
    parameter_query_names = _endpoint_parameter_query_names(runtime_cls, parameters)
    doc = inspect.getdoc(runtime_cls) or ""
    contract = NbaApiEndpointContract(
        runtime_class_name=runtime_class_name,
        module_name=runtime_cls.__module__,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        required_parameters=required_parameters,
        nullable_parameters=nullable_parameters,
        result_sets=result_sets,
        deprecated="deprecated" in doc.lower(),
        warnings=tuple(warnings),
        parameter_defaults=parameter_defaults,
        parameter_query_names=parameter_query_names,
        request_method="GET",
        parser_kind=(
            "custom_nested"
            if endpoint_slug in custom_parser_endpoint_slugs()
            else "legacy_result_sets"
        ),
    )
    response_contract = endpoint_response_mode_contract(contract)
    if response_contract.response_mode == "unknown_dynamic_response":
        _validate_unknown_dynamic_runtime_export(runtime_cls, response_contract)
    return contract


_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```(?P<language>[a-zA-Z0-9_-]*)\s*(?P<body>.*?)\s*```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"^\[(?P<label>[^\]]+)\](?:\((?P<url>[^)]+)\))?$")
_LAST_VALIDATED_RE = re.compile(r"Last validated (?P<date>\d{4}-\d{2}-\d{2})")
_MARKDOWN_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_DATA_SET_HEADING_RE = re.compile(
    r"^####\s+(?P<label>.+?)(?:\s+`(?P<method_name>[^`]+)`)?\s*$",
    re.MULTILINE,
)
_STATIC_FUNCTION_RE = re.compile(
    r"^##\s+`(?P<function_name>[^`]+)`\((?P<parameters>[^)]*)\)",
    re.MULTILINE,
)
_STATIC_DICT_KEY_RE = re.compile(r"^\s*['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:", re.MULTILINE)
_BRONZE_IDENTIFIER_RE = re.compile(r"[^a-zA-Z0-9]+")


def _endpoint_docs_dir(root: Path) -> Path:
    if (root / "docs" / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "docs" / "nba_api" / "stats" / "endpoints"
    if (root / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "nba_api" / "stats" / "endpoints"
    return root


def _live_endpoint_docs_dir(root: Path) -> Path | None:
    if (root / "docs" / "nba_api" / "live" / "endpoints").is_dir():
        return root / "docs" / "nba_api" / "live" / "endpoints"
    if (root / "nba_api" / "live" / "endpoints").is_dir():
        return root / "nba_api" / "live" / "endpoints"
    if len(root.parts) >= 3 and root.parts[-3:] == ("nba_api", "live", "endpoints"):
        return root
    if len(root.parts) >= 2 and root.parts[-2:] == ("live", "endpoints"):
        return root
    return None


def _endpoint_output_docs_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "endpoints_output",
        root / "nba_api" / "stats" / "endpoints_output",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _endpoint_response_fixtures_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "endpoints" / "responses",
        root / "nba_api" / "stats" / "endpoints" / "responses",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _stats_static_docs_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "static",
        root / "nba_api" / "stats" / "static",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _parameter_library_doc_path(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "library" / "parameters.md",
        root / "nba_api" / "stats" / "library" / "parameters.md",
    ):
        if candidate.is_file():
            return candidate
    return None


def _tools_dir(root: Path) -> Path | None:
    for candidate in (root / "tools", root.parent / "tools"):
        if candidate.is_dir():
            return candidate
    return None


def _json_loads_lenient(raw_json: str) -> dict[str, Any] | None:
    candidate = raw_json
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        # Some upstream markdown historically contains regex strings such as
        # "^(\d{4}-\d{2})$". Treat those as intended JSON string backslashes
        # rather than dropping the whole contract.
        for _attempt in range(4):
            escaped = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r"\\\\", candidate)
            if escaped == candidate:
                return None
            candidate = escaped
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            break
        else:
            return None
    return payload if isinstance(payload, dict) else None


def _json_payload_candidates(markdown: str) -> list[str]:
    candidates = [match.group(1) for match in _JSON_BLOCK_RE.finditer(markdown)]
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "## JSON":
            continue
        block: list[str] = []
        started = False
        for candidate_line in lines[index + 1 :]:
            stripped = candidate_line.strip()
            if stripped.startswith("```"):
                break
            if stripped.startswith("#") and started:
                break
            if not started and not stripped:
                continue
            if candidate_line.startswith("    "):
                started = True
                block.append(candidate_line[4:])
                continue
            if candidate_line.startswith("\t"):
                started = True
                block.append(candidate_line[1:])
                continue
            if not started and stripped.startswith(("{", "[")):
                started = True
                block.append(candidate_line)
                continue
            if started and not stripped:
                block.append("")
                continue
            if started:
                break
        if block:
            candidate = "\n".join(block).strip()
            if candidate:
                candidates.append(candidate)
    return candidates


def _endpoint_analysis_payload(markdown: str) -> dict[str, Any] | None:
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is None:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("data_sets"), dict):
            return payload
    return None


def _markdown_url(markdown: str, label: str) -> str | None:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"##### {label}":
            continue
        for candidate_line in lines[index + 1 :]:
            candidate = candidate_line.strip()
            if not candidate:
                continue
            if candidate.startswith("##### "):
                break
            if not candidate.startswith(">"):
                continue
            candidate = candidate.lstrip(">").strip()
            match = _MARKDOWN_LINK_RE.match(candidate)
            if match is not None:
                return match.group("url") or match.group("label")
            return candidate.strip("<>")
    return None


def _last_validated_date(markdown: str, payload: dict[str, Any]) -> str | None:
    value = payload.get("last_validated_date")
    if isinstance(value, str) and value:
        return value
    match = _LAST_VALIDATED_RE.search(markdown)
    return match.group("date") if match else None


def _markdown_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title or None
    return None


def _dedupe_columns(columns: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    counts: dict[str, int] = {}
    for raw_column in columns:
        column = raw_column.strip()
        if not column:
            continue
        count = counts.get(column, 0) + 1
        counts[column] = count
        deduped.append(column if count == 1 else f"{column}_{count}")
    return tuple(deduped)


def structured_data_set_columns(data_set: list[Any]) -> tuple[str, ...]:
    """Flatten an exact ``nba_api`` structured-header declaration.

    The pinned shot-location endpoints describe a pandas-style multi-level
    header as declarative ``columnsToSkip``/``columnSpan`` records.  Runtime
    extraction and contract generation must share this implementation so
    tuple ``repr`` strings can never become column names.
    """
    columns_item = next(
        (
            item
            for item in data_set
            if isinstance(item, dict)
            and _normalise_metadata_key(str(item.get("name") or "")) == "columns"
        ),
        None,
    )
    if not isinstance(columns_item, dict) or not isinstance(columns_item.get("columnNames"), list):
        return ()

    base_columns = [str(column) for column in columns_item["columnNames"] if str(column).strip()]
    if not base_columns:
        return ()

    grouping_items = [
        item
        for item in data_set
        if isinstance(item, dict)
        and _normalise_metadata_key(str(item.get("name") or "")) != "columns"
        and isinstance(item.get("columnNames"), list)
        and isinstance(item.get("columnSpan"), int)
        and item["columnSpan"] > 0
    ]
    if not grouping_items:
        return _dedupe_columns(base_columns)

    # nba_api's generated shot-location docs encode repeated metrics in the
    # `columns` row and category labels in the preceding grouped header row.
    primary_group = grouping_items[0]
    skip_count = int(primary_group.get("columnsToSkip") or 0)
    group_labels = [
        _bronze_identifier(str(label))
        for label in primary_group.get("columnNames", [])
        if _bronze_identifier(str(label))
    ]
    metric_span = int(primary_group["columnSpan"])
    output_columns = [column for column in base_columns[:skip_count] if column.strip()]
    metric_columns = base_columns[skip_count:]

    cursor = 0
    for group_label in group_labels:
        for _offset in range(metric_span):
            if cursor >= len(metric_columns):
                break
            metric = _bronze_identifier(metric_columns[cursor])
            cursor += 1
            if not metric:
                continue
            output_columns.append(f"{group_label}_{metric}")

    if cursor < len(metric_columns):
        output_columns.extend(metric_columns[cursor:])
    return _dedupe_columns(output_columns)


def _data_set_expected_columns(data_set: list[Any]) -> tuple[str, ...]:
    string_columns = [column for column in data_set if isinstance(column, str)]
    if string_columns:
        return _dedupe_columns(string_columns)
    if any(isinstance(column, dict) for column in data_set):
        return structured_data_set_columns(data_set)
    return ()


def _contract_from_endpoint_analysis_doc(
    path: Path,
    payload: dict[str, Any],
    markdown: str = "",
    source_family: str = "stats",
    source_path: str | None = None,
) -> NbaApiEndpointContract | None:
    endpoint = payload.get("endpoint")
    data_sets = payload.get("data_sets")
    if not isinstance(endpoint, str) or not endpoint:
        endpoint = _markdown_title(markdown) or path.stem
    if not isinstance(data_sets, dict):
        return None

    parameter_patterns_payload = payload.get("parameter_patterns")
    result_sets: list[NbaApiResultSetContract] = []
    warnings: list[str] = []
    for name, columns in data_sets.items():
        if not isinstance(name, str) or not isinstance(columns, list):
            continue
        expected_columns = _data_set_expected_columns(columns)
        if not expected_columns:
            warnings.append(f"zero_column_result_set:{name}")
        result_sets.append(
            NbaApiResultSetContract(
                runtime_class_name=endpoint,
                result_set_index=len(result_sets),
                result_set_name=name,
                expected_columns=expected_columns,
                source="endpoint_analysis_docs",
                confidence="high",
            )
        )

    return NbaApiEndpointContract(
        runtime_class_name=endpoint,
        module_name=f"nba_api.docs.nba_api.stats.endpoints.{path.stem}",
        endpoint_slug=path.stem,
        parameters=tuple(str(value) for value in payload.get("parameters", []) if str(value)),
        required_parameters=tuple(
            str(value) for value in payload.get("required_parameters", []) if str(value)
        ),
        nullable_parameters=tuple(
            str(value) for value in payload.get("nullable_parameters", []) if str(value)
        ),
        result_sets=tuple(result_sets),
        deprecated=str(payload.get("status", "")).lower() == "deprecated",
        warnings=tuple(warnings),
        parameter_patterns=tuple(
            sorted(
                (str(key), str(value) if value is not None else None)
                for key, value in (
                    parameter_patterns_payload.items()
                    if isinstance(parameter_patterns_payload, dict)
                    else ()
                )
            )
        ),
        endpoint_url=_markdown_url(markdown, "Endpoint URL"),
        valid_url=_markdown_url(markdown, "Valid URL"),
        last_validated_date=_last_validated_date(markdown, payload),
        source_path=source_path or str(path),
        source_family=source_family,
        status=str(payload.get("status")) if payload.get("status") is not None else None,
    )


def _contract_from_live_endpoint_doc(
    path: Path,
    markdown: str,
    source_path: str | None = None,
) -> NbaApiEndpointContract | None:
    title = None
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    if not title:
        return None

    warnings: list[str] = []
    payload = None
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            break
    if payload is None:
        warnings.append("live_doc_json_payload_missing_or_invalid")

    return NbaApiEndpointContract(
        runtime_class_name=title,
        module_name=f"nba_api.docs.nba_api.live.endpoints.{path.stem}",
        endpoint_slug=path.stem,
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=tuple(warnings),
        endpoint_url=_markdown_url(markdown, "Endpoint URL"),
        last_validated_date=_last_validated_date(markdown, payload or {}),
        source_path=source_path or str(path),
        source_family="live",
        status="success" if payload is not None else None,
    )


def _source_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.relpath(path, root)


def _discover_endpoint_analysis_doc_contracts_with_warnings(
    docs_root: Path | str | None,
) -> tuple[dict[str, NbaApiEndpointContract], list[dict[str, str]]]:
    if docs_root is None:
        return {}, []

    root = Path(docs_root)
    docs_dir = _endpoint_docs_dir(root)
    if not docs_dir.is_dir():
        return {}, [
            {
                "source_path": _source_path(root, docs_dir),
                "reason": "stats_endpoint_docs_dir_missing",
            }
        ]

    contracts: dict[str, NbaApiEndpointContract] = {}
    warnings: list[dict[str, str]] = []
    try:
        doc_paths = tuple(sorted(docs_dir.glob("*.md")))
    except OSError as exc:
        raise _discovery_error(
            "stats_docs_inventory",
            _source_path(root, docs_dir),
            exc,
        ) from exc
    for path in doc_paths:
        source_path = _source_path(root, path)
        markdown = _read_discovery_text(
            path,
            stage="stats_docs_read",
            source=source_path,
        )
        payload = _endpoint_analysis_payload(markdown)
        if payload is None:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": "json_payload_missing_or_invalid",
                }
            )
            continue
        contract = _contract_from_endpoint_analysis_doc(
            path,
            payload,
            markdown,
            source_path=source_path,
        )
        if contract is None:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": "contract_payload_missing_required_shape",
                }
            )
            continue
        contracts[contract.runtime_class_name] = contract
    return contracts, warnings


def discover_endpoint_analysis_doc_contracts(
    docs_root: Path | str | None,
) -> dict[str, NbaApiEndpointContract]:
    contracts, _warnings = _discover_endpoint_analysis_doc_contracts_with_warnings(docs_root)
    return contracts


def discover_live_endpoint_doc_contracts(
    docs_root: Path | str | None,
) -> dict[str, NbaApiEndpointContract]:
    if docs_root is None:
        return {}

    root = Path(docs_root)
    docs_dir = _live_endpoint_docs_dir(root)
    if docs_dir is None or not docs_dir.is_dir():
        return {}

    contracts: dict[str, NbaApiEndpointContract] = {}
    try:
        doc_paths = tuple(sorted(docs_dir.glob("*.md")))
    except OSError as exc:
        raise _discovery_error(
            "live_docs_inventory",
            _source_path(root, docs_dir),
            exc,
        ) from exc
    for path in doc_paths:
        source_path = _source_path(root, path)
        markdown = _read_discovery_text(
            path,
            stage="live_docs_read",
            source=source_path,
        )
        contract = _contract_from_live_endpoint_doc(path, markdown, source_path=source_path)
        if contract is None:
            raise _discovery_error("live_docs_contract", source_path, "InvalidContract")
        contracts[contract.runtime_class_name] = contract
    return contracts


def _git_sha(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise _discovery_error("upstream_git_inventory", "git:HEAD", exc) from exc
    sha = result.stdout.strip()
    return sha or None


def _relative_paths(root: Path, directory: Path | None, pattern: str) -> list[str]:
    if directory is None or not directory.is_dir():
        return []
    try:
        paths = tuple(directory.rglob(pattern))
    except OSError as exc:
        raise _discovery_error(
            "source_file_inventory",
            _source_path(root, directory),
            exc,
        ) from exc
    return sorted(os.path.relpath(path, root) for path in paths if path.is_file())


def _source_file_digests(root: Path, relative_paths: list[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        raw = _read_discovery_bytes(
            path,
            stage="source_file_digest_read",
            source=relative_path,
        )
        digests[relative_path] = hashlib.sha256(raw).hexdigest()
    return digests


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(
        _read_discovery_bytes(
            path,
            stage="source_file_digest_read",
            source=path.name,
        )
    ).hexdigest()


def _clean_markdown_cell(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = cleaned.replace("_**", "").replace("**_", "")
    cleaned = cleaned.strip("`*_ ")
    return cleaned


def _normalise_metadata_key(value: str) -> str:
    cleaned = _clean_markdown_cell(value).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    in_code = False
    for char in stripped:
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells)


def _markdown_tables(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    tables: list[dict[str, Any]] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            index += 1
            continue
        headers = _split_markdown_row(lines[index])
        separator = _split_markdown_row(lines[index + 1])
        if not _is_markdown_separator(separator):
            index += 1
            continue

        header_keys = [_normalise_metadata_key(header) for header in headers]
        rows: list[dict[str, str]] = []
        row_index = index + 2
        while row_index < len(lines) and "|" in lines[row_index]:
            if lines[row_index].lstrip().startswith("#"):
                break
            cells = _split_markdown_row(lines[row_index])
            if not any(cell.strip() for cell in cells):
                break
            if len(cells) < len(header_keys):
                cells = [*cells, *([""] * (len(header_keys) - len(cells)))]
            if len(cells) > len(header_keys):
                cells = [*cells[: len(header_keys) - 1], " | ".join(cells[len(header_keys) - 1 :])]
            rows.append(
                {
                    header_keys[cell_index]: _clean_markdown_cell(cell)
                    for cell_index, cell in enumerate(cells[: len(header_keys)])
                    if header_keys[cell_index]
                }
            )
            row_index += 1

        tables.append(
            {
                "headers": [_clean_markdown_cell(header) for header in headers],
                "header_keys": header_keys,
                "rows": rows,
                "start_line": index + 1,
            }
        )
        index = row_index
    return tables


def _markdown_parameter_rows(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in _markdown_tables(markdown):
        header_keys = set(table["header_keys"])
        if not ({"api_parameter_name", "python_parameter_variable"} <= header_keys) and not (
            "parameter" in header_keys or "parameter_name" in header_keys
        ):
            continue
        for row in table["rows"]:
            rows.append(
                {
                    "api_parameter_name": row.get("api_parameter_name")
                    or row.get("parameter")
                    or row.get("parameter_name"),
                    "python_parameter_variable": row.get("python_parameter_variable"),
                    "pattern": row.get("pattern"),
                    "required": (row.get("required") or "").upper() == "Y",
                    "nullable": (row.get("nullable") or "").upper() == "Y",
                    "source_line": table["start_line"],
                }
            )
    return rows


def _markdown_data_set_headings(markdown: str) -> dict[str, dict[str, str | None]]:
    headings: dict[str, dict[str, str | None]] = {}
    for match in _DATA_SET_HEADING_RE.finditer(markdown):
        label = _clean_markdown_cell(match.group("label"))
        if not label or label.lower().startswith("class "):
            continue
        headings[label] = {
            "result_set_name": label,
            "method_name": match.group("method_name"),
        }
    return headings


def _markdown_data_set_field_lists(markdown: str) -> dict[str, list[str]]:
    matches = list(_DATA_SET_HEADING_RE.finditer(markdown))
    fields_by_dataset: dict[str, list[str]] = {}
    heading_matches = list(_MARKDOWN_HEADING_RE.finditer(markdown))
    for index, match in enumerate(matches):
        label = _clean_markdown_cell(match.group("label"))
        if not label:
            continue
        start = match.end()
        end_candidates = [
            heading.start()
            for heading in heading_matches
            if heading.start() > start and len(heading.group("level")) <= 2
        ]
        if index + 1 < len(matches):
            end_candidates.append(matches[index + 1].start())
        end = min(end_candidates) if end_candidates else len(markdown)
        section = markdown[start:end]
        columns: list[str] = []
        for code_block in _CODE_BLOCK_RE.finditer(section):
            body = code_block.group("body")
            columns.extend(re.findall(r'"([^"]+)"(?:\[\])?', body))
        if columns:
            fields_by_dataset[label] = list(dict.fromkeys(columns))
    return fields_by_dataset


def _first_json_payload(markdown: str) -> dict[str, Any] | None:
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            return payload
    return None


def _first_json_payload_with_warning(markdown: str) -> tuple[dict[str, Any] | None, str | None]:
    candidates = _json_payload_candidates(markdown)
    if not candidates:
        return None, "live_doc_json_payload_missing"
    for candidate in candidates:
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            return payload, None
    return None, "live_doc_json_payload_invalid"


def _parse_stats_endpoint_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    payload = _endpoint_analysis_payload(markdown)
    if payload is None:
        return None
    contract = _contract_from_endpoint_analysis_doc(
        path,
        payload,
        markdown,
        source_path=_source_path(root, path),
    )
    if contract is None:
        return None

    heading_metadata = _markdown_data_set_headings(markdown)
    result_sets: list[dict[str, Any]] = []
    for result_set in contract.result_sets:
        result_set_name = result_set.result_set_name or f"result_set_{result_set.result_set_index}"
        heading = heading_metadata.get(result_set_name, {})
        columns: list[dict[str, Any]] = []
        for ordinal, column in enumerate(result_set.expected_columns):
            description, description_source = resolved_field_description(
                None,
                column,
                endpoint=contract.runtime_class_name,
                result_set=result_set_name,
            )
            columns.append(
                {
                    "name": column,
                    "ordinal": ordinal,
                    "description": description,
                    "description_source": description_source,
                    "source": "endpoint_analysis_data_sets",
                }
            )
        result_sets.append(
            {
                "result_set_name": result_set_name,
                "result_set_index": result_set.result_set_index,
                "method_name": heading.get("method_name"),
                "column_count": len(result_set.expected_columns),
                "columns": columns,
            }
        )

    return {
        "endpoint": contract.runtime_class_name,
        "endpoint_slug": contract.endpoint_slug,
        "source_path": contract.source_path,
        "source_sha256": hashlib.sha256(
            _read_discovery_bytes(
                path,
                stage="stats_docs_digest_read",
                source=_source_path(root, path),
            )
        ).hexdigest(),
        "endpoint_url": contract.endpoint_url,
        "valid_url": contract.valid_url,
        "last_validated_date": contract.last_validated_date,
        "status": contract.status,
        "parameters": _markdown_parameter_rows(markdown),
        "parameter_patterns": dict(contract.parameter_patterns),
        "result_sets": result_sets,
    }


def _parse_live_endpoint_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    title = _markdown_title(markdown)
    if not title:
        return None

    about_fields: list[dict[str, Any]] = []
    for table in _markdown_tables(markdown):
        header_keys = set(table["header_keys"])
        if "key" not in header_keys or not ({"description", "class"} & header_keys):
            continue
        for row in table["rows"]:
            key = row.get("key")
            if not key:
                continue
            about_fields.append(
                {
                    "key": key,
                    "class": row.get("class"),
                    "type": _normalise_live_documented_type(row.get("type") or row.get("class")),
                    "sample": row.get("sample") or row.get("example"),
                    "description": row.get("description"),
                    "always_present": (row.get("alwayspresent") or row.get("always_present")),
                    "source_line": table["start_line"],
                }
            )

    payload, payload_warning = _first_json_payload_with_warning(markdown)
    return {
        "endpoint": title,
        "endpoint_slug": path.stem,
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(
            _read_discovery_bytes(
                path,
                stage="live_docs_digest_read",
                source=_source_path(root, path),
            )
        ).hexdigest(),
        "endpoint_url": _markdown_url(markdown, "Endpoint URL"),
        "valid_url": _markdown_url(markdown, "Valid URL"),
        "last_validated_date": _last_validated_date(markdown, payload or {}),
        "parameters": _markdown_parameter_rows(markdown),
        "about_fields": about_fields,
        "json_payload_keys": sorted(payload) if isinstance(payload, dict) else [],
        "warnings": (
            [{"source_path": _source_path(root, path), "reason": payload_warning}]
            if payload_warning
            else []
        ),
    }


def _normalise_live_documented_type(raw: str | None) -> str | list[str] | None:
    if not raw:
        return None
    aliases = {
        "bool": "boolean",
        "boolean": "boolean",
        "dict": "object",
        "float": "number",
        "int": "integer",
        "integer": "integer",
        "list": "array",
        "nonetype": "null",
        "str": "string",
        "string": "string",
    }
    normalized: list[str] = []
    for part in re.split(r"\s*(?:/|\|)\s*", raw):
        cleaned = re.sub(r"[^A-Za-z]", "", part).lower()
        if cleaned.startswith("class"):
            cleaned = cleaned.removeprefix("class")
        value = aliases.get(cleaned, cleaned or None)
        if value is not None and value not in normalized:
            normalized.append(value)
    if not normalized:
        return None
    return normalized[0] if len(normalized) == 1 else normalized


def _runtime_parameter_rows(runtime_cls: type) -> list[dict[str, Any]]:
    try:
        signature = inspect.signature(runtime_cls)
    except (TypeError, ValueError) as exc:
        source = f"{runtime_cls.__module__}.{runtime_cls.__name__}"
        raise _discovery_error("live_runtime_signature_inventory", source, exc) from exc

    rows: list[dict[str, Any]] = []
    for parameter in signature.parameters.values():
        if parameter.name in _AUX_PARAMETER_NAMES:
            continue
        rows.append(
            {
                "api_parameter_name": parameter.name,
                "python_parameter_variable": parameter.name,
                "pattern": None,
                "required": parameter.default is inspect.Parameter.empty,
                "nullable": parameter.default is None,
                "source_line": None,
                "source": "runtime_signature",
            }
        )
    return rows


def _sample_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _live_json_path(path: tuple[str, ...], field_name: str | None = None) -> str:
    parts = [*path]
    if field_name is not None:
        parts.append(field_name)
    return "$" + ("." + ".".join(parts) if parts else "")


def _live_result_set_name(path: tuple[str, ...]) -> str:
    return _bronze_identifier(*path) or "root"


def _live_shape_field(
    field_name: str, value: Any, path: tuple[str, ...], ordinal: int
) -> dict[str, Any]:
    return {
        "key": field_name,
        "name": field_name,
        "ordinal": ordinal,
        "json_path": _live_json_path(path, field_name),
        "sample_type": _sample_value_type(value),
        "description": None,
        "nullable": True,
        "source": "nba_api_live_expected_data",
        "source_field": True,
    }


def _flatten_live_expected_data_node(
    node: Any,
    *,
    path: tuple[str, ...],
    tables: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    data_grain: str,
) -> None:
    if isinstance(node, dict):
        field_items = [(key, value) for key, value in node.items() if isinstance(key, str)]
        if field_items:
            fields = [
                _live_shape_field(key, value, path, ordinal)
                for ordinal, (key, value) in enumerate(field_items)
            ]
            tables.append(
                {
                    "result_set_name": _live_result_set_name(path),
                    "method_name": _live_result_set_name(path),
                    "json_path": _live_json_path(path),
                    "data_grain": data_grain,
                    "fields": fields,
                    "field_count": len(fields),
                    "source": "runtime_live_expected_data",
                }
            )
        for key, value in node.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, dict | list)
                or (isinstance(value, list) and not value)
            ):
                continue
            _flatten_live_expected_data_node(
                value,
                path=(*path, key),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array"
                if isinstance(value, list)
                else "nba_api_live_json_object",
            )
        if not field_items:
            skipped.append(
                {
                    "json_path": _live_json_path(path),
                    "reason": "empty_object",
                    "source": "runtime_live_expected_data",
                }
            )
        return

    if isinstance(node, list):
        if not node:
            skipped.append(
                {
                    "json_path": _live_json_path(path),
                    "reason": "empty_array",
                    "source": "runtime_live_expected_data",
                }
            )
            return
        exemplars = [item for item in node if item is not None]
        exemplar = exemplars[0] if exemplars else node[0]
        if isinstance(exemplar, dict):
            for item in exemplars:
                if not isinstance(item, dict):
                    skipped.append(
                        {
                            "json_path": _live_json_path(path),
                            "reason": "mixed_array_item_type",
                            "sample_type": _sample_value_type(item),
                            "source": "runtime_live_expected_data",
                        }
                    )
                    continue
                _flatten_live_expected_data_node(
                    item,
                    path=path,
                    tables=tables,
                    skipped=skipped,
                    data_grain="nba_api_live_json_array",
                )
            return
        if isinstance(exemplar, list):
            _flatten_live_expected_data_node(
                exemplar,
                path=(*path, "item"),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array",
            )
            return
        tables.append(
            {
                "result_set_name": _live_result_set_name(path),
                "method_name": _live_result_set_name(path),
                "json_path": _live_json_path(path),
                "data_grain": "nba_api_live_json_array",
                "fields": [
                    {
                        **_live_shape_field("value", exemplar, path, 0),
                        "source_field": False,
                        "source": "nbadb_nested_scalar_projection",
                    }
                ],
                "field_count": 1,
                "source": "runtime_live_expected_data",
            }
        )
        return

    skipped.append(
        {
            "json_path": _live_json_path(path),
            "reason": "scalar_root",
            "sample_type": _sample_value_type(node),
            "source": "runtime_live_expected_data",
        }
    )


def _flatten_live_expected_data(
    expected_data: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if isinstance(expected_data, dict):
        for key, value in expected_data.items():
            if not isinstance(key, str):
                continue
            _flatten_live_expected_data_node(
                value,
                path=(key,),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array"
                if isinstance(value, list)
                else "nba_api_live_json_object",
            )
    else:
        _flatten_live_expected_data_node(
            expected_data,
            path=("root",),
            tables=tables,
            skipped=skipped,
            data_grain="nba_api_live_json_object",
        )

    deduped_tables: dict[str, dict[str, Any]] = {}
    for table in tables:
        if table["field_count"] <= 0:
            skipped.append(
                {
                    "json_path": table.get("json_path"),
                    "reason": "zero_column_table_suppressed",
                    "result_set_name": table.get("result_set_name"),
                    "source": "runtime_live_expected_data",
                }
            )
            continue
        name = table["result_set_name"]
        existing = deduped_tables.get(name)
        if existing is None:
            deduped_tables[name] = table
            continue
        existing_names = {field["key"] for field in existing["fields"]}
        for field in table["fields"]:
            if field["key"] in existing_names:
                continue
            field = dict(field)
            field["ordinal"] = len(existing["fields"])
            existing["fields"].append(field)
            existing_names.add(field["key"])
        existing["field_count"] = len(existing["fields"])
    return list(deduped_tables.values()), skipped


def _discover_live_runtime_endpoint_classes() -> dict[str, type]:
    endpoints, module_names = _package_module_inventory(
        "nba_api.live.nba.endpoints",
        stage="live_runtime_module_inventory",
    )
    classes: dict[str, type] = {}
    for module_name in module_names:
        module_path = f"{endpoints.__name__}.{module_name}"
        module = _import_discovery_module(module_path, stage="live_runtime_module_import")
        if module_name.startswith("_"):
            continue
        module_classes = [
            (name, obj)
            for name, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and not name.startswith("_") and name != "DataSet"
        ]
        if len(module_classes) != 1:
            raise _discovery_error(
                "live_runtime_class_inventory",
                module_path,
                "InventoryMismatch",
            )
        for name, obj in module_classes:
            if obj.__module__ != module.__name__:
                continue
            if name.startswith("_") or name == "DataSet":
                continue
            if not hasattr(obj, "expected_data"):
                raise _discovery_error(
                    "live_runtime_class_inventory",
                    f"{module_path}.{name}",
                    "InvalidContract",
                )
            if name in classes:
                raise _discovery_error(
                    "live_runtime_class_inventory",
                    f"{module_path}.{name}",
                    "InventoryMismatch",
                )
            classes[name] = obj
    expected_count = sum(not name.startswith("_") for name in module_names)
    if len(classes) != expected_count:
        raise _discovery_error(
            "live_runtime_class_inventory",
            endpoints.__name__,
            "PartialDiscovery",
        )
    return classes


def _live_runtime_metadata_from_class(
    runtime_cls: type,
    supplement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint_slug = runtime_cls.__module__.rsplit(".", 1)[-1]
    expected_data = getattr(runtime_cls, "expected_data", {})
    data_sets, skipped_shapes = _flatten_live_expected_data(expected_data)
    data_sets_by_path = {
        str(data_set.get("json_path")): data_set
        for data_set in data_sets
        if data_set.get("json_path")
    }
    for data_set in data_sets:
        for field in data_set.get("fields", []):
            nested_data_set = data_sets_by_path.get(str(field.get("json_path")))
            if nested_data_set is None or nested_data_set is data_set:
                continue
            field["nested_result_set_name"] = nested_data_set["result_set_name"]
            field["runtime_sample_type"] = (
                "array" if nested_data_set["data_grain"] == "nba_api_live_json_array" else "object"
            )
            field["sample_type"] = field["runtime_sample_type"]
    source_file, source_path = _runtime_source_path(
        runtime_cls,
        stage="live_runtime_source_lookup",
    )
    source_sha256 = hashlib.sha256(
        _read_discovery_bytes(
            source_file,
            stage="live_runtime_source_read",
            source=source_path,
        )
    ).hexdigest()
    supplement = supplement or {}
    about_fields_by_key = {
        _normalise_metadata_key(str(field.get("key"))): field
        for field in supplement.get("about_fields", [])
        if isinstance(field, dict) and field.get("key")
    }
    docs_field_target = next(
        (
            data_set
            for data_set in data_sets
            if runtime_cls.__name__ == "PlayByPlay"
            and data_set.get("result_set_name") == "game_actions"
        ),
        None,
    )
    nested_fields: dict[str, dict[str, Any]] = {}
    if docs_field_target is not None:
        parent_path = str(docs_field_target["json_path"]).rstrip(".")
        for data_set in data_sets:
            child_path = str(data_set.get("json_path") or "")
            prefix = f"{parent_path}."
            if child_path.startswith(prefix) and "." not in child_path[len(prefix) :]:
                nested_fields[_normalise_metadata_key(child_path[len(prefix) :])] = data_set
    field_scope = [docs_field_target] if docs_field_target is not None else data_sets
    known_field_keys = {
        _normalise_metadata_key(str(field.get("key") or ""))
        for data_set in field_scope
        for field in data_set.get("fields", [])
    }
    missing_doc_fields = [
        field
        for field in supplement.get("about_fields", [])
        if isinstance(field, dict)
        and field.get("key")
        and _normalise_metadata_key(str(field["key"])) not in known_field_keys
    ]
    if missing_doc_fields:
        if docs_field_target is None:
            raise ValueError(
                f"live docs expose fields without an owned dataset: {runtime_cls.__name__}"
            )
        for about_field in missing_doc_fields:
            key = str(about_field["key"])
            nested_data_set = nested_fields.get(_normalise_metadata_key(key))
            docs_field_target["fields"].append(
                {
                    "key": key,
                    "name": key,
                    "ordinal": len(docs_field_target["fields"]),
                    "json_path": f"{docs_field_target['json_path']}.{key}",
                    "sample_type": (
                        "array"
                        if nested_data_set is not None
                        and nested_data_set.get("data_grain") == "nba_api_live_json_array"
                        else (about_field.get("type") or "unknown")
                    ),
                    "runtime_sample_type": ("array" if nested_data_set is not None else None),
                    "description": about_field.get("description"),
                    "description_source": "live_docs_about_fields",
                    "nullable": True,
                    "key_presence": (
                        "required"
                        if str(about_field.get("always_present") or "").lower() in {"true", "yes"}
                        else "optional"
                    ),
                    "source": (
                        "nba_api_live_expected_data+live_docs_about_fields"
                        if nested_data_set is not None
                        else "live_docs_about_fields"
                    ),
                    "source_field": True,
                    "nested_result_set_name": (
                        nested_data_set.get("result_set_name")
                        if nested_data_set is not None
                        else None
                    ),
                    "confidence": "high",
                    "drift_status": (
                        "runtime_and_docs"
                        if nested_data_set is not None
                        else "docs_optional_not_in_runtime_expected_data"
                    ),
                }
            )
        docs_field_target["field_count"] = len(docs_field_target["fields"])

    for data_set in data_sets:
        result_set_name = data_set.get("result_set_name")
        for field in data_set.get("fields", []):
            key = str(field.get("key") or field.get("name") or "")
            about_field = (
                about_fields_by_key.get(_normalise_metadata_key(key))
                if field.get("source_field", True)
                else None
            )
            explicit_description = (
                about_field.get("description") if isinstance(about_field, dict) else None
            )
            description, description_source = resolved_field_description(
                explicit_description,
                key,
                endpoint=runtime_cls.__name__,
                result_set=str(result_set_name) if result_set_name else None,
                json_path=field.get("json_path"),
            )
            field["description"] = description
            field["description_source"] = (
                "live_docs_about_fields" if description_source == "metadata" else description_source
            )
            documented_type = about_field.get("type") if isinstance(about_field, dict) else None
            field.setdefault(
                "runtime_sample_type",
                (
                    field.get("sample_type")
                    if field.get("source")
                    in {
                        "nba_api_live_expected_data",
                        "nba_api_live_expected_data+live_docs_about_fields",
                        "nbadb_nested_scalar_projection",
                    }
                    else None
                ),
            )
            field["documented_type"] = documented_type
            field.setdefault(
                "key_presence",
                (
                    "required"
                    if isinstance(about_field, dict)
                    and str(about_field.get("always_present") or "").lower() in {"true", "yes"}
                    else "optional_or_undocumented"
                ),
            )
            if field.get("sample_type") in {None, "null", "unknown"} and documented_type:
                field["sample_type"] = documented_type
            field.setdefault("confidence", "high")
            field.setdefault(
                "drift_status",
                (
                    "runtime_nested_scalar_projection"
                    if not field.get("source_field", True)
                    else ("runtime_and_docs" if about_field is not None else "runtime_only")
                ),
            )
    return {
        "endpoint": runtime_cls.__name__,
        "endpoint_slug": endpoint_slug,
        "runtime_module": runtime_cls.__module__,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source": "runtime_live_expected_data",
        "endpoint_url": supplement.get("endpoint_url")
        or getattr(runtime_cls, "endpoint_url", None),
        "valid_url": supplement.get("valid_url"),
        "last_validated_date": supplement.get("last_validated_date"),
        "parameters": _runtime_parameter_rows(runtime_cls),
        "data_sets": data_sets,
        "skipped_shapes": skipped_shapes,
        "expected_data_root_keys": sorted(expected_data) if isinstance(expected_data, dict) else [],
        "docs_supplement": {
            key: supplement.get(key)
            for key in (
                "source_path",
                "source_sha256",
                "json_payload_keys",
                "about_fields",
                "parameters",
            )
            if supplement.get(key) not in (None, [], {})
        },
    }


def discover_runtime_live_endpoint_contracts(
    supplements_by_slug: dict[str, dict[str, Any]] | None = None,
) -> dict[str, NbaApiEndpointContract]:
    supplements_by_slug = supplements_by_slug or {}
    contracts: dict[str, NbaApiEndpointContract] = {}
    for name, runtime_cls in sorted(_discover_live_runtime_endpoint_classes().items()):
        metadata = _live_runtime_metadata_from_class(
            runtime_cls,
            supplements_by_slug.get(runtime_cls.__module__.rsplit(".", 1)[-1]),
        )
        result_sets = [
            NbaApiResultSetContract(
                runtime_class_name=name,
                result_set_index=index,
                result_set_name=data_set["result_set_name"],
                expected_columns=tuple(field["key"] for field in data_set["fields"]),
                source="expected_data",
                confidence="high",
            )
            for index, data_set in enumerate(metadata["data_sets"])
        ]
        contracts[name] = NbaApiEndpointContract(
            runtime_class_name=name,
            module_name=runtime_cls.__module__,
            endpoint_slug=metadata["endpoint_slug"],
            parameters=tuple(row["python_parameter_variable"] for row in metadata["parameters"]),
            required_parameters=tuple(
                row["python_parameter_variable"]
                for row in metadata["parameters"]
                if row["required"]
            ),
            nullable_parameters=tuple(
                row["python_parameter_variable"]
                for row in metadata["parameters"]
                if row["nullable"]
            ),
            result_sets=tuple(result_sets),
            deprecated=False,
            warnings=(),
            endpoint_url=metadata["endpoint_url"],
            valid_url=metadata["valid_url"],
            last_validated_date=metadata["last_validated_date"],
            source_path=metadata["source_path"],
            source_family="live",
            status="success",
        )
    return contracts


def _static_doc_sections(markdown: str) -> list[dict[str, Any]]:
    matches = list(_STATIC_FUNCTION_RE.finditer(markdown))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        description_lines = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ]
        sections.append(
            {
                "function_name": match.group("function_name"),
                "parameters": [
                    _clean_markdown_cell(parameter)
                    for parameter in match.group("parameters").split(",")
                    if parameter.strip()
                ],
                "description": " ".join(description_lines).strip() or None,
            }
        )
    return sections


def _parse_static_doc_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    title = _markdown_title(markdown) or path.stem
    dictionary_shapes: list[dict[str, Any]] = []
    for code_block in _CODE_BLOCK_RE.finditer(markdown):
        if code_block.group("language").lower() != "python":
            continue
        keys = list(dict.fromkeys(_STATIC_DICT_KEY_RE.findall(code_block.group("body"))))
        if keys:
            dictionary_shapes.append({"keys": keys, "key_count": len(keys)})

    return {
        "module": title.removesuffix(".py"),
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(
            _read_discovery_bytes(
                path,
                stage="static_docs_digest_read",
                source=_source_path(root, path),
            )
        ).hexdigest(),
        "functions": _static_doc_sections(markdown),
        "dictionary_shapes": dictionary_shapes,
    }


def _markdown_h2_sections(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    sections: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        match = _MARKDOWN_HEADING_RE.match(line)
        if match is not None and len(match.group("level")) == 2:
            if current_title is not None:
                sections.append({"title": current_title, "body": "\n".join(current_lines)})
            current_title = _clean_markdown_cell(match.group("title"))
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append({"title": current_title, "body": "\n".join(current_lines)})
    return sections


def _parse_parameter_library(root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "source_path": None,
            "source_sha256": None,
            "parameters": [],
            "missing": True,
        }

    source_path = _source_path(root, path)
    markdown = _read_discovery_text(
        path,
        stage="parameter_docs_read",
        source=source_path,
    )
    parameters: list[dict[str, Any]] = []
    for section in _markdown_h2_sections(markdown):
        body = section["body"]
        no_available_info = "No available information." in body
        classes = re.findall(r"####\s+[Cc]lass\s+`([^`]+)`", body)
        patterns = [
            _clean_markdown_cell(match.group(1))
            for match in re.finditer(r"^\s*-\s+(.+?)\s*$", body, re.MULTILINE)
        ]
        values: list[dict[str, Any]] = []
        for table in _markdown_tables(body):
            if {"variable_name", "value"} <= set(table["header_keys"]):
                values.extend(
                    {
                        "variable_name": row.get("variable_name", ""),
                        "value": row.get("value", ""),
                        "is_default": "default" in (row.get("variable_name", "").lower()),
                    }
                    for row in table["rows"]
                )
        parameters.append(
            {
                "parameter_name": section["title"],
                "classes": classes,
                "patterns": patterns,
                "values": values,
                "no_available_information": no_available_info,
            }
        )

    return {
        "source_path": source_path,
        "source_sha256": hashlib.sha256(
            _read_discovery_bytes(
                path,
                stage="parameter_docs_digest_read",
                source=source_path,
            )
        ).hexdigest(),
        "parameters": parameters,
        "missing": False,
    }


def _infer_sample_type(values: list[str]) -> str:
    cleaned = [value for value in values if value not in ("", "null", "None", "nan", "-")]
    if not cleaned:
        return "unknown"
    if all(re.fullmatch(r"-?\d+", value) for value in cleaned):
        return "integer"
    if all(re.fullmatch(r"-?(?:\d+\.\d+|\d+)", value) for value in cleaned):
        return "number"
    return "string"


def _parse_endpoint_output_sample(root: Path, path: Path, markdown: str) -> dict[str, Any]:
    tables = _markdown_tables(markdown)
    columns: list[dict[str, Any]] = []
    sample_rows: list[dict[str, str]] = []
    if tables:
        first_table = tables[0]
        sample_rows = first_table["rows"][:5]
        for header_key, header in zip(
            first_table["header_keys"], first_table["headers"], strict=False
        ):
            columns.append(
                {
                    "name": header,
                    "sample_type": _infer_sample_type(
                        [row.get(header_key, "") for row in first_table["rows"]]
                    ),
                }
            )
    return {
        "endpoint_slug": path.name.removesuffix("_output.md"),
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(
            _read_discovery_bytes(
                path,
                stage="endpoint_output_digest_read",
                source=_source_path(root, path),
            )
        ).hexdigest(),
        "columns": columns,
        "sample_rows": sample_rows,
        "sample_row_count": len(sample_rows),
    }


def _ast_key_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_key_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _ast_sequence_names(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.List | ast.Tuple | ast.Set):
        raise ValueError("tools sequence inventory is not literal")
    names: list[str] = []
    for element in node.elts:
        name = _ast_key_name(element)
        if name is None:
            raise ValueError("tools sequence inventory contains a non-literal value")
        names.append(name)
    return names


def _ast_mapping_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        raise ValueError("tools mapping inventory is not literal")
    keys: list[str] = []
    for key in node.keys:
        if key is None:
            raise ValueError("tools mapping inventory contains an expansion")
        name = _ast_key_name(key)
        if name is None:
            raise ValueError("tools mapping inventory contains a non-literal key")
        keys.append(name)
    return keys


def _parse_tools_metadata(root: Path, tools_dir: Path | None) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    endpoint_list: list[str] = []
    parameter_variation_keys: list[str] = []
    parameter_map_keys: list[str] = []
    warnings: list[dict[str, str]] = []

    if tools_dir is None or not tools_dir.is_dir():
        return {
            "files": [],
            "endpoint_list": [],
            "parameter_variation_keys": [],
            "parameter_map_keys": [],
            "warnings": [{"source_path": "tools", "reason": "tools_dir_missing"}],
        }

    try:
        tool_paths = tuple(sorted(tools_dir.rglob("*.py")))
    except OSError as exc:
        raise _discovery_error(
            "tools_source_inventory",
            _source_path(root, tools_dir),
            exc,
        ) from exc
    for path in tool_paths:
        source_path = _source_path(root, path)
        source_text = _read_discovery_text(
            path,
            stage="tools_source_read",
            source=source_path,
        )
        try:
            tree = ast.parse(source_text, filename=source_path)
        except SyntaxError as exc:
            raise _discovery_error("tools_source_parse", source_path, exc) from exc
        assignments: dict[str, list[str]] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            for name in names:
                try:
                    if name == "endpoint_list":
                        values = _ast_sequence_names(node.value)
                        assignments[name] = values
                        endpoint_list.extend(values)
                    elif name == "parameter_variations":
                        values = _ast_mapping_keys(node.value)
                        assignments[name] = values
                        parameter_variation_keys.extend(values)
                    elif name == "parameter_map":
                        values = _ast_mapping_keys(node.value)
                        assignments[name] = values
                        parameter_map_keys.extend(values)
                except ValueError as exc:
                    raise _discovery_error(
                        "tools_assignment_inventory",
                        source_path,
                        "InvalidContract",
                    ) from exc
        files.append(
            {
                "source_path": source_path,
                "source_sha256": hashlib.sha256(
                    _read_discovery_bytes(
                        path,
                        stage="tools_source_digest_read",
                        source=source_path,
                    )
                ).hexdigest(),
                "assignments": assignments,
            }
        )

    return {
        "files": files,
        "endpoint_list": sorted(set(endpoint_list)),
        "parameter_variation_keys": sorted(set(parameter_variation_keys)),
        "parameter_map_keys": sorted(set(parameter_map_keys)),
        "warnings": warnings,
    }


def _endpoint_reconciliation_key(value: object) -> str:
    return _normalise_metadata_key(str(value))


_KNOWN_ZERO_COLUMN_RESULT_SETS: dict[tuple[str, str], tuple[str, str]] = {
    (
        "DefenseHub",
        "DefenseHubStat10",
    ): (
        "known_upstream_empty_result_set",
        "nba_api docs expose this conditional DefenseHub result set with no columns.",
    ),
    (
        "ScoreboardV2",
        "WinProbability",
    ): (
        "deprecated_upstream_empty_result_set",
        "nba_api v1.11.4 release notes deprecate ScoreboardV2; this conditional "
        "result set is documented without columns.",
    ),
}


def _known_zero_column_classification(
    endpoint_name: str,
    result_set_name: str,
) -> tuple[str, str, bool]:
    classification = _KNOWN_ZERO_COLUMN_RESULT_SETS.get((endpoint_name, result_set_name))
    if classification is None:
        return (
            "unclassified_zero_column_result_set",
            "No local evidence classifies this upstream zero-column result set.",
            True,
        )
    reason, detail = classification
    return reason, detail, False


def _reconciliation_row(
    *,
    endpoint: str,
    status: str,
    source: str,
    classification: str,
    reason: str,
    blocking: bool = False,
    matched_docs_endpoint: str | None = None,
    matched_tools_endpoint: str | None = None,
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "status": status,
        "source": source,
        "classification": classification,
        "classification_reason": reason,
        "blocking": blocking,
        "matched_docs_endpoint": matched_docs_endpoint,
        "matched_tools_endpoint": matched_tools_endpoint,
    }


def _reconcile_tools_metadata(
    tools_metadata: dict[str, Any],
    stats_endpoint_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    docs_by_key = {
        _endpoint_reconciliation_key(endpoint.get("endpoint")): str(endpoint.get("endpoint"))
        for endpoint in stats_endpoint_metadata
        if endpoint.get("endpoint")
    }
    tools_by_key = {
        _endpoint_reconciliation_key(endpoint): str(endpoint)
        for endpoint in tools_metadata.get("endpoint_list", [])
        if endpoint
    }
    docs_keys = set(docs_by_key)
    tools_keys = set(tools_by_key)
    tools_missing_docs = [tools_by_key[key] for key in sorted(tools_keys - docs_keys)]
    docs_missing_tools = [docs_by_key[key] for key in sorted(docs_keys - tools_keys)]
    rows = [
        _reconciliation_row(
            endpoint=tools_by_key[key],
            status="tools_endpoint_missing_docs",
            source="tools_endpoint_list",
            classification="tools_inventory_endpoint_without_parsed_doc",
            reason=(
                "tools/stats/library/mapping.py is an upstream endpoint inventory, "
                "but the current docs tree does not expose a parsed endpoint contract for this key."
            ),
            matched_tools_endpoint=tools_by_key[key],
        )
        for key in sorted(tools_keys - docs_keys)
    ]
    rows.extend(
        _reconciliation_row(
            endpoint=docs_by_key[key],
            status="docs_endpoint_missing_tools",
            source="stats_endpoint_docs",
            classification="docs_contract_without_tools_inventory_key",
            reason=(
                "The upstream docs tree exposes this endpoint contract, but the tools endpoint "
                "inventory does not list the same normalized key."
            ),
            matched_docs_endpoint=docs_by_key[key],
        )
        for key in sorted(docs_keys - tools_keys)
    )
    blocking_rows = [row for row in rows if row["blocking"]]
    return {
        "tools_endpoint_missing_docs": tools_missing_docs,
        "docs_endpoint_missing_tools": docs_missing_tools,
        "rows": rows,
        "tools_endpoint_missing_docs_count": len(tools_missing_docs),
        "docs_endpoint_missing_tools_count": len(docs_missing_tools),
        "classified_mismatch_count": len(rows) - len(blocking_rows),
        "blocking_mismatch_count": len(blocking_rows),
        "blocking_tools_endpoint_missing_docs_count": sum(
            1 for row in blocking_rows if row["status"] == "tools_endpoint_missing_docs"
        ),
        "blocking_docs_endpoint_missing_tools_count": sum(
            1 for row in blocking_rows if row["status"] == "docs_endpoint_missing_tools"
        ),
    }


def build_nba_api_metadata_ledger(docs_root: Path | str | None) -> dict[str, Any]:
    root = Path(docs_root) if docs_root is not None else None
    if root is None:
        ledger: dict[str, Any] = {
            "enabled": False,
            "schema_version": 1,
            "docs_root": None,
            "summary": {},
            "warnings": ["endpoint_analysis_docs_root_not_configured"],
        }
        digest_source = json.dumps(ledger, sort_keys=True, separators=(",", ":"))
        ledger["metadata_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        return ledger

    warnings: list[dict[str, str]] = []
    stats_dir = _endpoint_docs_dir(root)
    live_dir = _live_endpoint_docs_dir(root)
    static_dir = _stats_static_docs_dir(root)
    output_dir = _endpoint_output_docs_dir(root)
    parameter_doc = _parameter_library_doc_path(root)
    tools_dir = _tools_dir(root)

    stats_endpoint_metadata: list[dict[str, Any]] = []
    if stats_dir.is_dir():
        try:
            stats_paths = tuple(sorted(stats_dir.glob("*.md")))
        except OSError as exc:
            raise _discovery_error(
                "stats_metadata_inventory",
                _source_path(root, stats_dir),
                exc,
            ) from exc
        for path in stats_paths:
            source_path = _source_path(root, path)
            markdown = _read_discovery_text(
                path,
                stage="stats_metadata_read",
                source=source_path,
            )
            metadata = _parse_stats_endpoint_metadata(root, path, markdown)
            if metadata is None:
                warnings.append(
                    {
                        "source_path": source_path,
                        "reason": "stats_metadata_parse_failed",
                    }
                )
                continue
            stats_endpoint_metadata.append(metadata)
    else:
        warnings.append(
            {
                "source_path": _source_path(root, stats_dir),
                "reason": "stats_endpoint_docs_dir_missing",
            }
        )

    live_supplements_by_slug: dict[str, dict[str, Any]] = {}
    if live_dir is not None and live_dir.is_dir():
        try:
            live_paths = tuple(sorted(live_dir.glob("*.md")))
        except OSError as exc:
            raise _discovery_error(
                "live_metadata_inventory",
                _source_path(root, live_dir),
                exc,
            ) from exc
        for path in live_paths:
            source_path = _source_path(root, path)
            markdown = _read_discovery_text(
                path,
                stage="live_metadata_read",
                source=source_path,
            )
            supplement = _parse_live_endpoint_metadata(root, path, markdown)
            if supplement is None:
                warnings.append(
                    {
                        "source_path": source_path,
                        "reason": "live_metadata_parse_failed",
                    }
                )
                continue
            warnings.extend(supplement.get("warnings", []))
            live_supplements_by_slug[supplement["endpoint_slug"]] = supplement

    live_endpoint_metadata = [
        _live_runtime_metadata_from_class(
            runtime_cls,
            live_supplements_by_slug.get(runtime_cls.__module__.rsplit(".", 1)[-1]),
        )
        for _name, runtime_cls in sorted(_discover_live_runtime_endpoint_classes().items())
    ]

    static_doc_metadata: list[dict[str, Any]] = []
    if static_dir is not None and static_dir.is_dir():
        try:
            static_paths = tuple(sorted(static_dir.glob("*.md")))
        except OSError as exc:
            raise _discovery_error(
                "static_metadata_inventory",
                _source_path(root, static_dir),
                exc,
            ) from exc
        for path in static_paths:
            source_path = _source_path(root, path)
            markdown = _read_discovery_text(
                path,
                stage="static_metadata_read",
                source=source_path,
            )
            metadata = _parse_static_doc_metadata(root, path, markdown)
            if metadata is not None:
                static_doc_metadata.append(metadata)

    static_source_metadata: list[dict[str, Any]] = []
    source_package_roots = (root / "src", root)
    has_static_source = any(
        (package_root / "nba_api" / "stats" / "library" / "data.py").is_file()
        for package_root in source_package_roots
    )
    if has_static_source:
        from nbadb.core.nba_api_runtime_contract import pinned_static_contracts

        for dataset_id, contract in sorted(pinned_static_contracts().items()):
            source_path = next(
                (
                    package_root / contract.data_source_path
                    for package_root in source_package_roots
                    if (package_root / contract.data_source_path).is_file()
                ),
                None,
            )
            provider_source_path = next(
                (
                    package_root / contract.provider_source_path
                    for package_root in source_package_roots
                    if (package_root / contract.provider_source_path).is_file()
                ),
                None,
            )
            if source_path is None or provider_source_path is None:
                raise ValueError(f"exact static source is incomplete for {dataset_id}")
            if (
                _file_sha256(source_path) != contract.data_source_sha256
                or _file_sha256(provider_source_path) != contract.provider_source_sha256
            ):
                raise ValueError(
                    f"exact static source disagrees with the pinned contract for {dataset_id}"
                )
            static_source_metadata.append(
                {
                    "dataset_id": dataset_id,
                    "module": dataset_id.removeprefix("static_"),
                    "source_path": contract.data_source_path,
                    "source_sha256": contract.data_source_sha256,
                    "provider_source_path": contract.provider_source_path,
                    "provider_source_sha256": contract.provider_source_sha256,
                    "raw_fields": [field.to_json() for field in contract.raw_fields],
                    "projected_fields": list(contract.projected_fields),
                    "row_count": contract.row_count,
                    "raw_records_sha256": contract.raw_records_sha256,
                    "source_rows_sha256": contract.source_rows_sha256,
                    "contract_sha256": contract.contract_sha256,
                    "model_disposition": contract.model_disposition,
                    "disposition_reason": contract.disposition_reason,
                }
            )

    endpoint_output_samples: list[dict[str, Any]] = []
    if output_dir is not None and output_dir.is_dir():
        try:
            output_paths = tuple(sorted(output_dir.glob("*_output.md")))
        except OSError as exc:
            raise _discovery_error(
                "endpoint_output_inventory",
                _source_path(root, output_dir),
                exc,
            ) from exc
        for path in output_paths:
            source_path = _source_path(root, path)
            endpoint_output_samples.append(
                _parse_endpoint_output_sample(
                    root,
                    path,
                    _read_discovery_text(
                        path,
                        stage="endpoint_output_read",
                        source=source_path,
                    ),
                )
            )

    parameter_library = _parse_parameter_library(root, parameter_doc)
    parameter_contracts = {
        str(parameter["parameter_name"]): parameter for parameter in parameter_library["parameters"]
    }
    for endpoint in stats_endpoint_metadata:
        for parameter in endpoint["parameters"]:
            library_contract = parameter_contracts.get(str(parameter["api_parameter_name"]))
            if library_contract is None:
                parameter["constraint_status"] = "docs_tools_contract_drift_classified"
                parameter["constraint_evidence"] = {
                    "source_path": parameter_library.get("source_path"),
                    "confidence": "high",
                    "classification": "endpoint_docs_parameter_absent_from_parameter_library",
                    "effect": "parameter is retained but constrained only by endpoint docs",
                    "owner": "upstream_nba_api",
                    "revalidation_path": "regenerate_from_exact_pinned_nba_api_source",
                }
                parameter["parameter_classes"] = []
                parameter["patterns"] = [parameter["pattern"]] if parameter.get("pattern") else []
                parameter["allowed_values"] = []
                continue
            parameter["constraint_status"] = (
                "exact_parameter_library_contract"
                if not library_contract["no_available_information"]
                else "parameter_library_declares_no_available_information"
            )
            parameter["constraint_evidence"] = {
                "source_path": parameter_library.get("source_path"),
                "source_sha256": parameter_library.get("source_sha256"),
                "confidence": "high",
            }
            parameter["parameter_classes"] = library_contract["classes"]
            parameter["patterns"] = library_contract["patterns"]
            parameter["allowed_values"] = library_contract["values"]
    tools_metadata = _parse_tools_metadata(root, tools_dir)
    tools_reconciliation = _reconcile_tools_metadata(tools_metadata, stats_endpoint_metadata)
    warnings.extend(tools_metadata.get("warnings", []))

    stats_result_set_count = sum(
        len(endpoint["result_sets"]) for endpoint in stats_endpoint_metadata
    )
    stats_column_count = sum(
        result_set["column_count"]
        for endpoint in stats_endpoint_metadata
        for result_set in endpoint["result_sets"]
    )
    live_data_set_count = sum(len(endpoint["data_sets"]) for endpoint in live_endpoint_metadata)
    live_field_count = sum(
        data_set["field_count"]
        for endpoint in live_endpoint_metadata
        for data_set in endpoint["data_sets"]
    )
    live_skipped_shape_count = sum(
        len(endpoint.get("skipped_shapes", [])) for endpoint in live_endpoint_metadata
    )
    static_function_count = sum(len(doc["functions"]) for doc in static_doc_metadata)
    static_dictionary_shape_count = sum(
        len(doc["dictionary_shapes"]) for doc in static_doc_metadata
    )
    parameter_entries = parameter_library["parameters"]
    parameter_no_info_count = sum(
        1 for parameter in parameter_entries if parameter["no_available_information"]
    )

    ledger = {
        "enabled": True,
        "schema_version": 1,
        "docs_root": str(root),
        "stats_endpoint_metadata": stats_endpoint_metadata,
        "live_endpoint_metadata": live_endpoint_metadata,
        "static_doc_metadata": static_doc_metadata,
        "static_source_metadata": static_source_metadata,
        "parameter_library": parameter_library,
        "endpoint_output_samples": endpoint_output_samples,
        "tools_metadata": tools_metadata,
        "tools_reconciliation": tools_reconciliation,
        "summary": {
            "stats_endpoint_metadata_count": len(stats_endpoint_metadata),
            "stats_result_set_metadata_count": stats_result_set_count,
            "stats_column_metadata_count": stats_column_count,
            "stats_parameter_row_count": sum(
                len(endpoint["parameters"]) for endpoint in stats_endpoint_metadata
            ),
            "stats_parameter_constraint_classified_count": sum(
                len(endpoint["parameters"]) for endpoint in stats_endpoint_metadata
            ),
            "stats_parameter_constraint_unclassified_count": 0,
            "live_endpoint_metadata_count": len(live_endpoint_metadata),
            "live_data_set_metadata_count": live_data_set_count,
            "live_field_metadata_count": live_field_count,
            "live_skipped_shape_count": live_skipped_shape_count,
            "static_doc_metadata_count": len(static_doc_metadata),
            "static_function_doc_count": static_function_count,
            "static_dictionary_shape_count": static_dictionary_shape_count,
            "static_source_dataset_count": len(static_source_metadata),
            "static_source_modeled_dataset_count": sum(
                1
                for dataset in static_source_metadata
                if dataset["model_disposition"] == "defined_and_implemented"
            ),
            "static_source_field_count": sum(
                len(dataset["raw_fields"])
                for dataset in static_source_metadata
                if dataset["model_disposition"] == "defined_and_implemented"
            ),
            "parameter_library_entry_count": len(parameter_entries),
            "parameter_library_no_available_info_count": parameter_no_info_count,
            "endpoint_output_sample_count": len(endpoint_output_samples),
            "endpoint_output_sample_column_count": sum(
                len(sample["columns"]) for sample in endpoint_output_samples
            ),
            "tools_endpoint_list_count": len(tools_metadata["endpoint_list"]),
            "tools_parameter_variation_key_count": len(tools_metadata["parameter_variation_keys"]),
            "tools_parameter_map_key_count": len(tools_metadata["parameter_map_keys"]),
            "tools_endpoint_missing_docs_count": tools_reconciliation[
                "tools_endpoint_missing_docs_count"
            ],
            "docs_endpoint_missing_tools_count": tools_reconciliation[
                "docs_endpoint_missing_tools_count"
            ],
            "classified_tools_docs_mismatch_count": tools_reconciliation[
                "classified_mismatch_count"
            ],
            "blocking_tools_docs_mismatch_count": tools_reconciliation["blocking_mismatch_count"],
            "blocking_tools_endpoint_missing_docs_count": tools_reconciliation[
                "blocking_tools_endpoint_missing_docs_count"
            ],
            "blocking_docs_endpoint_missing_tools_count": tools_reconciliation[
                "blocking_docs_endpoint_missing_tools_count"
            ],
            "metadata_ingestion_warning_count": len(warnings),
        },
        "warnings": warnings,
    }
    digest_payload = {key: value for key, value in ledger.items() if key != "docs_root"}
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    ledger["metadata_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return ledger


def _bronze_identifier(*parts: str | None) -> str:
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned = _BRONZE_IDENTIFIER_RE.sub("_", part).strip("_").lower()
        if cleaned:
            tokens.append(cleaned)
    return "_".join(tokens)


def _bronze_columns_from_names(
    names: list[str],
    *,
    endpoint: str | None = None,
    result_set: str | None = None,
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for ordinal, name in enumerate(names):
        description, description_source = resolved_field_description(
            None,
            name,
            endpoint=endpoint,
            result_set=result_set,
        )
        columns.append(
            {
                "name": name,
                "ordinal": ordinal,
                "description": description,
                "description_source": description_source,
                "nullable": True,
                "source": "nba_api_expected_columns",
                "source_field": True,
            }
        )
    return columns


def build_nba_api_bronze_contracts_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    metadata_ledger = bundle.get("metadata_ledger", {})
    stats_metadata_by_endpoint = {
        endpoint["endpoint"]: endpoint
        for endpoint in metadata_ledger.get("stats_endpoint_metadata", [])
        if isinstance(endpoint, dict) and endpoint.get("endpoint")
    }
    tables: list[dict[str, Any]] = []
    skipped_zero_column_tables: list[dict[str, Any]] = []

    for endpoint in bundle.get("stats_contracts", []):
        endpoint_name = endpoint["runtime_class_name"]
        endpoint_slug = endpoint.get("endpoint_slug") or _bronze_identifier(endpoint_name)
        stats_metadata = stats_metadata_by_endpoint.get(endpoint_name, {})
        result_metadata_by_name = {
            result_set["result_set_name"]: result_set
            for result_set in stats_metadata.get("result_sets", [])
            if isinstance(result_set, dict)
        }
        for result_set in endpoint.get("result_sets", []):
            result_set_name = result_set.get("result_set_name") or "result_set"
            result_metadata = result_metadata_by_name.get(result_set_name, {})
            columns: list[dict[str, Any]] = []
            for column in result_metadata.get("columns", []):
                column_name = str(column.get("name") or "")
                description, description_source = resolved_field_description(
                    column.get("description"),
                    column_name,
                    endpoint=endpoint_name,
                    result_set=result_set_name,
                )
                columns.append(
                    {
                        **column,
                        "description": description,
                        "description_source": column.get("description_source")
                        or description_source,
                        "nullable": True,
                        "source": "nba_api_docs_tools_ingestion",
                        "source_field": True,
                    }
                )
            if not columns:
                columns = _bronze_columns_from_names(
                    result_set.get("expected_columns", []),
                    endpoint=endpoint_name,
                    result_set=result_set_name,
                )
            if not columns:
                classification, classification_reason, blocking = _known_zero_column_classification(
                    endpoint_name, result_set_name
                )
                skipped_zero_column_tables.append(
                    {
                        "source_family": "stats",
                        "endpoint": endpoint_name,
                        "endpoint_slug": endpoint_slug,
                        "result_set_name": result_set_name,
                        "source_path": endpoint.get("source_path"),
                        "reason": "zero_column_result_set_suppressed",
                        "classification": classification,
                        "classification_reason": classification_reason,
                        "blocking": blocking,
                    }
                )
                continue
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier("stats", endpoint_slug, result_set_name),
                    "source_family": "stats",
                    "endpoint": endpoint_name,
                    "endpoint_slug": endpoint_slug,
                    "result_set_name": result_set_name,
                    "source_dataset_method": result_metadata.get("method_name"),
                    "data_grain": "nba_api_result_set",
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": stats_metadata.get("parameters", endpoint.get("parameters", [])),
                    "source_path": endpoint.get("source_path"),
                    "endpoint_url": endpoint.get("endpoint_url"),
                    "valid_url": endpoint.get("valid_url"),
                }
            )

    for endpoint in metadata_ledger.get("live_endpoint_metadata", []):
        for data_set in endpoint.get("data_sets", []):
            fields = data_set.get("fields", [])
            columns = []
            for ordinal, field in enumerate(fields):
                if not field.get("key"):
                    continue
                column_name = str(field.get("name") or field["key"])
                description, description_source = resolved_field_description(
                    field.get("description"),
                    column_name,
                    endpoint=str(endpoint.get("endpoint") or ""),
                    result_set=str(data_set.get("result_set_name") or ""),
                    json_path=field.get("json_path"),
                )
                columns.append(
                    {
                        "name": column_name,
                        "ordinal": ordinal,
                        "description": description,
                        "description_source": field.get("description_source") or description_source,
                        "nullable": field.get("nullable", True),
                        "source": field.get("source", "nba_api_live_expected_data"),
                        "json_path": field.get("json_path"),
                        "sample_type": field.get("sample_type") or field.get("type"),
                        "source_field": field.get("source_field", True),
                    }
                )
            if not columns:
                continue
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier(
                        "live",
                        endpoint.get("endpoint_slug"),
                        data_set.get("result_set_name"),
                    ),
                    "source_family": "live",
                    "endpoint": endpoint.get("endpoint"),
                    "endpoint_slug": endpoint.get("endpoint_slug"),
                    "result_set_name": data_set.get("result_set_name"),
                    "source_dataset_method": data_set.get("method_name"),
                    "data_grain": data_set.get("data_grain", "nba_api_live_json_object"),
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": endpoint.get("parameters", []),
                    "source_path": endpoint.get("source_path"),
                    "endpoint_url": endpoint.get("endpoint_url"),
                    "valid_url": endpoint.get("valid_url"),
                    "json_path": data_set.get("json_path"),
                }
            )

    static_source_metadata = [
        dataset
        for dataset in metadata_ledger.get("static_source_metadata", [])
        if dataset.get("model_disposition") == "defined_and_implemented"
    ]
    if static_source_metadata:
        for dataset in static_source_metadata:
            keys = [field["name"] for field in dataset.get("raw_fields", [])]
            result_set_name = "shape_1"
            columns = _bronze_columns_from_names(
                keys,
                endpoint=str(dataset.get("module") or "static"),
                result_set=result_set_name,
            )
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier("static", dataset.get("module"), result_set_name),
                    "source_family": "static",
                    "endpoint": dataset.get("module"),
                    "endpoint_slug": dataset.get("module"),
                    "result_set_name": f"{dataset.get('module')}_{result_set_name}",
                    "source_dataset_method": None,
                    "data_grain": "nba_api_static_source_record",
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": [],
                    "source_path": dataset.get("source_path"),
                    "source_sha256": dataset.get("source_sha256"),
                    "source_rows_sha256": dataset.get("source_rows_sha256"),
                    "raw_records_sha256": dataset.get("raw_records_sha256"),
                    "static_contract_sha256": dataset.get("contract_sha256"),
                    "projected_fields": dataset.get("projected_fields", []),
                    "endpoint_url": None,
                    "valid_url": None,
                }
            )
    else:
        for static_doc in metadata_ledger.get("static_doc_metadata", []):
            for index, dictionary_shape in enumerate(static_doc.get("dictionary_shapes", [])):
                keys = dictionary_shape.get("keys", [])
                result_set_name = f"shape_{index + 1}"
                columns = _bronze_columns_from_names(
                    keys,
                    endpoint=str(static_doc.get("module") or "static"),
                    result_set=result_set_name,
                )
                tables.append(
                    {
                        "bronze_table": "bronze_"
                        + _bronze_identifier("static", static_doc.get("module"), result_set_name),
                        "source_family": "static",
                        "endpoint": static_doc.get("module"),
                        "endpoint_slug": static_doc.get("module"),
                        "result_set_name": f"{static_doc.get('module')}_{result_set_name}",
                        "source_dataset_method": None,
                        "data_grain": "nba_api_static_dictionary",
                        "columns": columns,
                        "column_count": len(columns),
                        "parameters": [],
                        "source_path": static_doc.get("source_path"),
                        "endpoint_url": None,
                        "valid_url": None,
                    }
                )

    contracts = {
        "enabled": bool(bundle.get("enabled")),
        "schema_version": 1,
        "source_bundle_digest": bundle.get("bundle_digest"),
        "source_metadata_digest": metadata_ledger.get("metadata_digest"),
        "tables": sorted(tables, key=lambda table: table["bronze_table"]),
        "summary": {
            "table_count": len(tables),
            "stats_table_count": sum(1 for table in tables if table["source_family"] == "stats"),
            "live_table_count": sum(1 for table in tables if table["source_family"] == "live"),
            "static_table_count": sum(1 for table in tables if table["source_family"] == "static"),
            "column_count": sum(table["column_count"] for table in tables),
            "canonical_source_field_count": sum(
                1
                for table in tables
                for column in table["columns"]
                if column.get("source_field", True)
            ),
            "zero_column_table_count": len(skipped_zero_column_tables),
        },
        "skipped_zero_column_tables": skipped_zero_column_tables,
    }
    blocking_zero_column_tables = [
        table for table in skipped_zero_column_tables if table.get("blocking")
    ]
    contracts["summary"]["classified_zero_column_table_count"] = len(
        skipped_zero_column_tables
    ) - len(blocking_zero_column_tables)
    contracts["summary"]["blocking_zero_column_table_count"] = len(blocking_zero_column_tables)
    described_column_count = 0
    description_source_counts: dict[str, int] = {}
    for table in contracts["tables"]:
        for column in table.get("columns", []):
            if column.get("description"):
                described_column_count += 1
            description_source = str(column.get("description_source") or "missing")
            description_source_counts[description_source] = (
                description_source_counts.get(description_source, 0) + 1
            )
    contracts["summary"]["described_column_count"] = described_column_count
    contracts["summary"]["missing_description_count"] = (
        contracts["summary"]["column_count"] - described_column_count
    )
    contracts["summary"]["description_source_counts"] = dict(
        sorted(description_source_counts.items())
    )
    digest_payload = {
        key: value for key, value in contracts.items() if key != "source_bundle_digest"
    }
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    contracts["bronze_contract_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return contracts


def build_nba_api_upstream_contract_bundle(
    docs_root: Path | str | None,
    *,
    project_root: Path | str | None = None,
) -> dict[str, Any]:
    root = Path(docs_root) if docs_root is not None else None
    provider_provenance = verify_nba_api_provider(
        root,
        project_root=Path(project_root) if project_root is not None else Path.cwd(),
    )
    if root is None:
        metadata_ledger = build_nba_api_metadata_ledger(None)
        bundle: dict[str, Any] = {
            "enabled": False,
            "schema_version": 1,
            "docs_root": None,
            "upstream_git_sha": None,
            "source_inventory": {},
            "stats_contracts": [],
            "live_contracts": [],
            "metadata_ledger": metadata_ledger,
            "warnings": ["endpoint_analysis_docs_root_not_configured"],
            "provider_provenance": provider_provenance,
        }
    else:
        stats_dir = _endpoint_docs_dir(root)
        live_dir = _live_endpoint_docs_dir(root)
        static_dir = _stats_static_docs_dir(root)
        output_dir = _endpoint_output_docs_dir(root)
        responses_dir = _endpoint_response_fixtures_dir(root)
        parameter_doc = _parameter_library_doc_path(root)
        tools_dir = _tools_dir(root)
        stats_contracts, malformed_stats_docs = (
            _discover_endpoint_analysis_doc_contracts_with_warnings(root)
        )
        metadata_ledger = build_nba_api_metadata_ledger(root)
        live_supplements_by_slug = {
            endpoint.get("endpoint_slug"): endpoint
            for endpoint in metadata_ledger.get("live_endpoint_metadata", [])
            if isinstance(endpoint, dict) and endpoint.get("endpoint_slug")
        }
        live_contracts = discover_runtime_live_endpoint_contracts(live_supplements_by_slug)
        stats_docs = _relative_paths(root, stats_dir, "*.md")
        live_docs = _relative_paths(root, live_dir, "*.md")
        static_docs = _relative_paths(root, static_dir, "*.md")
        output_docs = _relative_paths(root, output_dir, "*_output.md")
        response_fixtures = _relative_paths(root, responses_dir, "*.json")
        tools_files = _relative_paths(root, tools_dir, "*.py")
        parameter_docs = [_source_path(root, parameter_doc)] if parameter_doc is not None else []
        bundle = {
            "enabled": True,
            "schema_version": 1,
            "docs_root": str(root),
            "upstream_git_sha": _git_sha(root),
            "source_inventory": {
                "stats_endpoint_doc_count": len(stats_docs),
                "parsed_stats_contract_count": len(stats_contracts),
                "live_endpoint_doc_count": len(live_docs),
                "parsed_live_contract_count": len(live_contracts),
                "static_doc_count": len(static_docs),
                "parameter_library_doc_count": len(parameter_docs),
                "endpoint_output_doc_count": len(output_docs),
                "response_fixture_count": len(response_fixtures),
                "tools_python_file_count": len(tools_files),
                **metadata_ledger.get("summary", {}),
            },
            "source_files": {
                "stats_endpoint_docs": stats_docs,
                "live_endpoint_docs": live_docs,
                "static_docs": static_docs,
                "parameter_library_docs": parameter_docs,
                "endpoint_output_docs": output_docs,
                "response_fixtures": response_fixtures,
                "tools": tools_files,
            },
            "source_file_digests": {
                "stats_endpoint_docs": _source_file_digests(root, stats_docs),
                "live_endpoint_docs": _source_file_digests(root, live_docs),
                "static_docs": _source_file_digests(root, static_docs),
                "parameter_library_docs": _source_file_digests(root, parameter_docs),
                "endpoint_output_docs": _source_file_digests(root, output_docs),
                "response_fixtures": _source_file_digests(root, response_fixtures),
                "tools": _source_file_digests(root, tools_files),
            },
            "malformed_stats_docs": malformed_stats_docs,
            "stats_contracts": [
                contract_to_json(contract) for _name, contract in sorted(stats_contracts.items())
            ],
            "live_contracts": [
                contract_to_json(contract) for _name, contract in sorted(live_contracts.items())
            ],
            "metadata_ledger": metadata_ledger,
            "warnings": (["malformed_stats_docs_detected"] if malformed_stats_docs else []),
            "provider_provenance": provider_provenance,
        }

    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)
    bundle["bronze_contracts_summary"] = bronze_contracts["summary"]
    bundle["bronze_contract_digest"] = bronze_contracts["bronze_contract_digest"]
    digest_payload = {key: value for key, value in bundle.items() if key != "docs_root"}
    metadata_ledger_payload = digest_payload.get("metadata_ledger")
    if isinstance(metadata_ledger_payload, dict):
        digest_payload["metadata_ledger"] = {
            key: value for key, value in metadata_ledger_payload.items() if key != "docs_root"
        }
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    bundle["bundle_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return bundle


@lru_cache(maxsize=1)
def discover_runtime_endpoint_contracts() -> dict[str, NbaApiEndpointContract]:
    endpoints, module_names = _package_module_inventory(
        "nba_api.stats.endpoints",
        stage="stats_runtime_module_inventory",
    )
    contracts: dict[str, NbaApiEndpointContract] = {}
    for module_name in module_names:
        module_path = f"{endpoints.__name__}.{module_name}"
        module = _import_discovery_module(module_path, stage="stats_runtime_module_import")
        if module_name.startswith("_"):
            continue
        module_classes = [
            (name, obj)
            for name, obj in inspect.getmembers(module, inspect.isclass)
            if obj.__module__ == module.__name__ and not name.startswith("_") and name != "Endpoint"
        ]
        if len(module_classes) != 1:
            raise _discovery_error(
                "stats_runtime_class_inventory",
                module_path,
                "InventoryMismatch",
            )
        for name, obj in module_classes:
            if name in contracts:
                raise _discovery_error(
                    "stats_runtime_class_inventory",
                    f"{module_path}.{name}",
                    "InventoryMismatch",
                )
            try:
                contracts[name] = build_endpoint_contract(obj)
            except NbaApiContractDiscoveryError:
                raise
            except Exception as exc:
                raise _discovery_error(
                    "stats_runtime_contract_build",
                    f"{module_path}.{name}",
                    exc,
                ) from exc
    expected_count = sum(not name.startswith("_") for name in module_names)
    if len(contracts) != expected_count:
        raise _discovery_error(
            "stats_runtime_class_inventory",
            endpoints.__name__,
            "PartialDiscovery",
        )
    return contracts


def _parameter_default_to_json(
    default: NbaApiParameterDefaultContract,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": default.name,
        "value_type": default.value_type,
        "default_authority": default.default_authority,
        "default_expression": default.default_expression,
    }
    if default.default_authority == "provider_literal_or_required_v1":
        payload["value"] = default.value
    elif default.value is not None:
        raise ValueError("dynamic provider default cannot retain an evaluated value")
    return payload


def contract_to_json(contract: NbaApiEndpointContract) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_class_name": contract.runtime_class_name,
        "module_name": contract.module_name,
        "endpoint_slug": contract.endpoint_slug,
        "parameters": list(contract.parameters),
        "required_parameters": list(contract.required_parameters),
        "nullable_parameters": list(contract.nullable_parameters),
        "parameter_defaults": [
            _parameter_default_to_json(default) for default in contract.parameter_defaults
        ],
        "parameter_query_names": [
            {"name": name, "query_name": query_name}
            for name, query_name in contract.parameter_query_names
        ],
        "request_method": contract.request_method,
        "parser_kind": contract.parser_kind,
        "deprecated": contract.deprecated,
        "warnings": list(contract.warnings),
        "result_sets": [
            {
                "runtime_class_name": result_set.runtime_class_name,
                "result_set_index": result_set.result_set_index,
                "result_set_name": result_set.result_set_name,
                "expected_columns": list(result_set.expected_columns),
                "source": result_set.source,
                "confidence": result_set.confidence,
            }
            for result_set in contract.result_sets
        ],
    }
    optional_values: dict[str, Any] = {
        "parameter_patterns": dict(contract.parameter_patterns),
        "endpoint_url": contract.endpoint_url,
        "valid_url": contract.valid_url,
        "last_validated_date": contract.last_validated_date,
        "source_path": contract.source_path,
        "source_family": contract.source_family,
        "status": contract.status,
    }
    for key, value in optional_values.items():
        if value not in (None, {}, ()):
            payload[key] = value
    return payload


def _endpoint_contract_payload_sha256(contract: NbaApiEndpointContract) -> str:
    encoded = json.dumps(
        contract_to_json(contract),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def endpoint_response_mode_contract(
    contract: NbaApiEndpointContract,
) -> NbaApiResponseModeContract:
    """Classify exact endpoint result authority without inferring a shape.

    Endpoint-level ``expected_data = {}`` is admitted only for the four exact
    pinned Video endpoints.  Any mutation of their identity or complete
    endpoint contract fails closed.  A named result set with zero declared
    columns remains a normal declared result-set contract and never enters the
    unknown-response path.
    """

    endpoint_slug = contract.endpoint_slug
    if not isinstance(endpoint_slug, str) or not endpoint_slug:
        raise ValueError("nba_api response contract endpoint slug is absent")
    identity = (contract.runtime_class_name, contract.module_name, endpoint_slug)
    pin = _EXACT_UNKNOWN_DYNAMIC_RESPONSE_PINS.get(identity)
    contract_sha256 = _endpoint_contract_payload_sha256(contract)
    if pin is not None:
        if (
            contract_sha256 != pin.endpoint_contract_sha256
            or contract.parser_kind != "legacy_result_sets"
            or contract.result_sets
        ):
            raise ValueError("exact unknown dynamic response contract drifted")
        return NbaApiResponseModeContract(
            runtime_class_name=contract.runtime_class_name,
            module_name=contract.module_name,
            endpoint_slug=endpoint_slug,
            response_mode="unknown_dynamic_response",
            provider_result_inventory="endpoint_expected_data_empty_unknown",
            observed_packet_mode="fail_closed_json_object_or_legacy_result_sets",
            endpoint_doc_status=pin.endpoint_doc_status,
            package_export_status=pin.package_export_status,
            endpoint_contract_sha256=contract_sha256,
        )

    if (
        contract.runtime_class_name in _UNKNOWN_DYNAMIC_RUNTIME_CLASS_NAMES
        or contract.module_name in _UNKNOWN_DYNAMIC_MODULE_NAMES
        or endpoint_slug in _UNKNOWN_DYNAMIC_ENDPOINT_SLUGS
    ):
        raise ValueError("unknown dynamic response endpoint identity drifted")
    if not contract.result_sets:
        raise ValueError("zero-result endpoint lacks an exact unknown dynamic response pin")
    return NbaApiResponseModeContract(
        runtime_class_name=contract.runtime_class_name,
        module_name=contract.module_name,
        endpoint_slug=endpoint_slug,
        response_mode="declared_result_sets",
        provider_result_inventory="named_result_sets",
        observed_packet_mode="declared_result_sets_only",
        endpoint_doc_status=None,
        package_export_status=None,
        endpoint_contract_sha256=contract_sha256,
    )


def _validate_unknown_dynamic_runtime_export(
    runtime_cls: type,
    response_contract: NbaApiResponseModeContract,
) -> None:
    """Verify the exact installed package export status carried by the pin."""

    package_name = "nba_api.stats.endpoints"
    package = _import_discovery_module(
        package_name,
        stage="stats_unknown_response_export_import",
    )
    declared = getattr(package, "__all__", None)
    if not isinstance(declared, list | tuple) or any(
        not isinstance(name, str) for name in declared
    ):
        raise _discovery_error(
            "stats_unknown_response_export_inventory",
            package_name,
            "InventoryMismatch",
        )
    module_leaf = runtime_cls.__module__.rsplit(".", 1)[-1]
    module_exported = module_leaf in declared
    class_exported = getattr(package, runtime_cls.__name__, None) is runtime_cls
    if module_exported != class_exported:
        raise _discovery_error(
            "stats_unknown_response_export_inventory",
            runtime_cls.__name__,
            "InventoryMismatch",
        )
    actual_status: PackageExportStatus = (
        "package_exported" if module_exported else "direct_import_only"
    )
    if actual_status != response_contract.package_export_status:
        raise _discovery_error(
            "stats_unknown_response_export_inventory",
            runtime_cls.__name__,
            "InventoryMismatch",
        )


def contract_from_json(payload: object) -> NbaApiEndpointContract:
    """Load one exact generated endpoint contract into the owned DTO."""

    if not isinstance(payload, dict):
        raise ValueError("nba_api endpoint contract must be an object")
    value = cast("dict[str, Any]", payload)
    required_keys = {
        "runtime_class_name",
        "module_name",
        "endpoint_slug",
        "parameters",
        "required_parameters",
        "nullable_parameters",
        "parameter_defaults",
        "parameter_query_names",
        "request_method",
        "parser_kind",
        "deprecated",
        "warnings",
        "result_sets",
    }
    optional_keys = {
        "parameter_patterns",
        "endpoint_url",
        "valid_url",
        "last_validated_date",
        "source_path",
        "source_family",
        "status",
    }
    if not required_keys <= set(value) or not set(value) <= required_keys | optional_keys:
        raise ValueError("nba_api endpoint contract fields do not match the schema")

    def _strings(field: str) -> tuple[str, ...]:
        raw = value[field]
        if not isinstance(raw, list) or any(not isinstance(item, str) for item in raw):
            raise ValueError(f"nba_api endpoint contract {field} must be strings")
        return tuple(raw)

    runtime_class_name = value["runtime_class_name"]
    module_name = value["module_name"]
    endpoint_slug = value["endpoint_slug"]
    if not isinstance(runtime_class_name, str) or not isinstance(module_name, str):
        raise ValueError("nba_api endpoint contract identity is invalid")
    if endpoint_slug is not None and not isinstance(endpoint_slug, str):
        raise ValueError("nba_api endpoint contract slug is invalid")
    if not isinstance(value["deprecated"], bool):
        raise ValueError("nba_api endpoint contract deprecated flag is invalid")

    raw_defaults = value["parameter_defaults"]
    if not isinstance(raw_defaults, list):
        raise ValueError("nba_api endpoint contract parameter defaults are invalid")
    defaults: list[NbaApiParameterDefaultContract] = []
    for raw_default in raw_defaults:
        if not isinstance(raw_default, dict):
            raise ValueError("nba_api endpoint contract parameter default is invalid")
        authority = raw_default.get("default_authority")
        expected_fields = (
            {"name", "value_type", "default_authority", "default_expression"}
            if authority == "provider_dynamic_default_expression_v1"
            else {
                "name",
                "value",
                "value_type",
                "default_authority",
                "default_expression",
            }
        )
        if set(raw_default) != expected_fields:
            raise ValueError("nba_api endpoint contract parameter default is invalid")
        name = raw_default["name"]
        default = raw_default.get("value")
        value_type = raw_default["value_type"]
        default_authority = raw_default["default_authority"]
        default_expression = raw_default["default_expression"]
        if not isinstance(name, str) or not (
            default is None or isinstance(default, str | int | float | bool)
        ):
            raise ValueError("nba_api endpoint contract parameter default is invalid")
        if value_type not in {"str", "int", "float", "bool", "NoneType"}:
            raise ValueError("nba_api endpoint contract parameter default type is invalid")
        if default_authority == "provider_dynamic_default_expression_v1":
            if (
                not isinstance(default_expression, str)
                or _DYNAMIC_DEFAULT_EXPRESSION_TYPES.get(default_expression) != value_type
            ):
                raise ValueError("nba_api endpoint dynamic default authority is invalid")
        elif default_authority == "provider_literal_or_required_v1":
            if (
                not isinstance(default_expression, str)
                or default_expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
                or default_expression.partition(".")[0] in _DYNAMIC_DEFAULT_CLASS_NAMES
                or value_type != type(default).__name__
            ):
                raise ValueError("nba_api endpoint literal default authority is invalid")
        else:
            raise ValueError("nba_api endpoint parameter default authority is invalid")
        defaults.append(
            NbaApiParameterDefaultContract(
                name=name,
                value=default,
                value_type=cast("ParameterValueType", value_type),
                default_authority=cast("ParameterDefaultAuthority", default_authority),
                default_expression=cast("str", default_expression),
            )
        )

    raw_query_names = value["parameter_query_names"]
    if not isinstance(raw_query_names, list):
        raise ValueError("nba_api endpoint parameter query names are invalid")
    query_names: list[tuple[str, str]] = []
    for raw_query_name in raw_query_names:
        if not isinstance(raw_query_name, dict) or set(raw_query_name) != {
            "name",
            "query_name",
        }:
            raise ValueError("nba_api endpoint parameter query name is invalid")
        name = raw_query_name["name"]
        query_name = raw_query_name["query_name"]
        if not isinstance(name, str) or not isinstance(query_name, str):
            raise ValueError("nba_api endpoint parameter query name is invalid")
        query_names.append((name, query_name))
    if value["request_method"] != "GET":
        raise ValueError("nba_api endpoint request method is invalid")
    if value["parser_kind"] not in {"legacy_result_sets", "custom_nested"}:
        raise ValueError("nba_api endpoint parser kind is invalid")

    raw_result_sets = value["result_sets"]
    if not isinstance(raw_result_sets, list):
        raise ValueError("nba_api endpoint result-set contracts must be a list")
    result_sets: list[NbaApiResultSetContract] = []
    for raw_result_set in raw_result_sets:
        if not isinstance(raw_result_set, dict) or set(raw_result_set) != {
            "runtime_class_name",
            "result_set_index",
            "result_set_name",
            "expected_columns",
            "source",
            "confidence",
        }:
            raise ValueError("nba_api endpoint result-set contract is invalid")
        index = raw_result_set["result_set_index"]
        name = raw_result_set["result_set_name"]
        columns = raw_result_set["expected_columns"]
        source = raw_result_set["source"]
        confidence = raw_result_set["confidence"]
        if (
            raw_result_set["runtime_class_name"] != runtime_class_name
            or isinstance(index, bool)
            or not isinstance(index, int)
            or index < 0
            or (name is not None and not isinstance(name, str))
            or not isinstance(columns, list)
            or any(not isinstance(column, str) for column in columns)
            or source
            not in {
                "expected_data",
                "source_ast",
                "load_response",
                "manual_override",
                "endpoint_analysis_docs",
            }
            or confidence not in {"high", "medium", "low"}
        ):
            raise ValueError("nba_api endpoint result-set contract is invalid")
        result_sets.append(
            NbaApiResultSetContract(
                runtime_class_name=runtime_class_name,
                result_set_index=index,
                result_set_name=name,
                expected_columns=tuple(columns),
                source=cast("ContractSource", source),
                confidence=cast("Confidence", confidence),
            )
        )
    if tuple(result_set.result_set_index for result_set in result_sets) != tuple(
        range(len(result_sets))
    ):
        raise ValueError("nba_api endpoint result-set ordinals are not contiguous")

    raw_patterns = value.get("parameter_patterns", {})
    if not isinstance(raw_patterns, dict) or any(
        not isinstance(name, str) or (pattern is not None and not isinstance(pattern, str))
        for name, pattern in raw_patterns.items()
    ):
        raise ValueError("nba_api endpoint parameter patterns are invalid")
    parameter_patterns = tuple(
        sorted(
            (cast("str", name), cast("str | None", pattern))
            for name, pattern in raw_patterns.items()
        )
    )
    optional_strings: dict[str, str | None] = {}
    for field in (
        "endpoint_url",
        "valid_url",
        "last_validated_date",
        "source_path",
        "source_family",
        "status",
    ):
        raw = value.get(field)
        if raw is not None and not isinstance(raw, str):
            raise ValueError(f"nba_api endpoint contract {field} is invalid")
        optional_strings[field] = raw

    parameters = _strings("parameters")
    if tuple(name for name, _query_name in query_names) != parameters or len(
        {query_name for _name, query_name in query_names}
    ) != len(query_names):
        raise ValueError("nba_api endpoint parameter query mapping is invalid")
    default_names = tuple(default.name for default in defaults)
    required_parameters = _strings("required_parameters")
    nullable_parameters = _strings("nullable_parameters")
    if (
        len(default_names) != len(set(default_names))
        or not set(default_names) <= set(parameters)
        or not set(required_parameters) <= set(parameters)
        or not set(nullable_parameters) <= set(parameters)
        or set(default_names) & set(required_parameters)
        or set(default_names) | set(required_parameters) != set(parameters)
    ):
        raise ValueError("nba_api endpoint parameter/default inventory is inconsistent")

    contract = NbaApiEndpointContract(
        runtime_class_name=runtime_class_name,
        module_name=module_name,
        endpoint_slug=endpoint_slug,
        parameters=parameters,
        required_parameters=required_parameters,
        nullable_parameters=nullable_parameters,
        parameter_defaults=tuple(defaults),
        parameter_query_names=tuple(query_names),
        request_method="GET",
        parser_kind=cast("ParserKind", value["parser_kind"]),
        result_sets=tuple(result_sets),
        deprecated=value["deprecated"],
        warnings=_strings("warnings"),
        parameter_patterns=parameter_patterns,
        endpoint_url=optional_strings["endpoint_url"],
        valid_url=optional_strings["valid_url"],
        last_validated_date=optional_strings["last_validated_date"],
        source_path=optional_strings["source_path"],
        source_family=optional_strings["source_family"],
        status=optional_strings["status"],
    )
    if contract.source_family is None:
        endpoint_response_mode_contract(contract)
    return contract
