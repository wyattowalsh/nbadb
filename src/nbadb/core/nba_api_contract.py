from __future__ import annotations

import ast
import importlib
import inspect
import json
import pkgutil
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

ContractSource = Literal[
    "expected_data",
    "source_ast",
    "load_response",
    "manual_override",
    "endpoint_analysis_docs",
]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class NbaApiResultSetContract:
    runtime_class_name: str
    result_set_index: int
    result_set_name: str | None
    expected_columns: tuple[str, ...]
    source: ContractSource
    confidence: Confidence


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


_AUX_PARAMETER_NAMES = {"proxy", "headers", "timeout", "get_request"}


def _literal_expected_data(node: ast.AST) -> dict[str, list[str]] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None
    if not isinstance(value, dict):
        return None

    expected_data: dict[str, list[str]] = {}
    for key, columns in value.items():
        if not isinstance(key, str) or not isinstance(columns, list):
            continue
        expected_data[key] = [column for column in columns if isinstance(column, str)]
    return expected_data


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
    try:
        source_path = Path(inspect.getsourcefile(runtime_cls) or "")
    except TypeError:
        return {}, ()
    if not source_path.is_file():
        return {}, ()

    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}, ()

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
            expected_data = _literal_expected_data(child.value) or {}
            break
        return expected_data, tuple(_load_response_result_set_names(node))
    return {}, ()


def _endpoint_parameters(
    runtime_cls: type,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    try:
        signature = inspect.signature(runtime_cls.__init__)
    except (TypeError, ValueError):
        return (), (), ()

    parameters: list[str] = []
    required: list[str] = []
    nullable: list[str] = []
    for name, parameter in signature.parameters.items():
        if name == "self" or name in _AUX_PARAMETER_NAMES:
            continue
        parameters.append(name)
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        if parameter.default is None or name.endswith("_nullable"):
            nullable.append(name)
    return tuple(parameters), tuple(required), tuple(nullable)


def build_endpoint_contract(runtime_cls: type) -> NbaApiEndpointContract:
    runtime_class_name = runtime_cls.__name__
    runtime_expected = getattr(runtime_cls, "expected_data", None)
    expected_data: dict[str, list[str]] = {}
    source: ContractSource = "expected_data"
    confidence: Confidence = "high"

    if isinstance(runtime_expected, dict):
        for key, columns in runtime_expected.items():
            if isinstance(key, str) and isinstance(columns, list):
                expected_data[key] = [column for column in columns if isinstance(column, str)]

    source_expected, load_response_names = _source_contract(runtime_cls)
    warnings: list[str] = []
    if not expected_data and source_expected:
        expected_data = source_expected
        source = "source_ast"
        confidence = "medium"
    if load_response_names and expected_data:
        missing_from_expected = [name for name in load_response_names if name not in expected_data]
        if missing_from_expected:
            warnings.append(
                "load_response_result_sets_missing_expected_data:" + ",".join(missing_from_expected)
            )

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
    parameters, required_parameters, nullable_parameters = _endpoint_parameters(runtime_cls)
    doc = inspect.getdoc(runtime_cls) or ""
    return NbaApiEndpointContract(
        runtime_class_name=runtime_class_name,
        module_name=runtime_cls.__module__,
        endpoint_slug=getattr(runtime_cls, "endpoint", None),
        parameters=parameters,
        required_parameters=required_parameters,
        nullable_parameters=nullable_parameters,
        result_sets=result_sets,
        deprecated="deprecated" in doc.lower(),
        warnings=tuple(warnings),
    )


_JSON_BLOCK_RE = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _endpoint_docs_dir(root: Path) -> Path:
    if (root / "docs" / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "docs" / "nba_api" / "stats" / "endpoints"
    if (root / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "nba_api" / "stats" / "endpoints"
    return root


def _endpoint_analysis_payload(markdown: str) -> dict[str, Any] | None:
    for match in _JSON_BLOCK_RE.finditer(markdown):
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("data_sets"), dict):
            return payload
    return None


def _contract_from_endpoint_analysis_doc(
    path: Path,
    payload: dict[str, Any],
) -> NbaApiEndpointContract | None:
    endpoint = payload.get("endpoint")
    data_sets = payload.get("data_sets")
    if not isinstance(endpoint, str) or not isinstance(data_sets, dict):
        return None

    result_sets: list[NbaApiResultSetContract] = []
    for index, (name, columns) in enumerate(data_sets.items()):
        if not isinstance(name, str) or not isinstance(columns, list):
            continue
        result_sets.append(
            NbaApiResultSetContract(
                runtime_class_name=endpoint,
                result_set_index=index,
                result_set_name=name,
                expected_columns=tuple(column for column in columns if isinstance(column, str)),
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
        warnings=(),
    )


def discover_endpoint_analysis_doc_contracts(
    docs_root: Path | str | None,
) -> dict[str, NbaApiEndpointContract]:
    if docs_root is None:
        return {}

    root = Path(docs_root)
    docs_dir = _endpoint_docs_dir(root)
    if not docs_dir.is_dir():
        return {}

    contracts: dict[str, NbaApiEndpointContract] = {}
    for path in sorted(docs_dir.glob("*.md")):
        try:
            payload = _endpoint_analysis_payload(path.read_text(encoding="utf-8"))
        except OSError:
            continue
        if payload is None:
            continue
        contract = _contract_from_endpoint_analysis_doc(path, payload)
        if contract is not None:
            contracts[contract.runtime_class_name] = contract
    return contracts


@lru_cache(maxsize=1)
def discover_runtime_endpoint_contracts() -> dict[str, NbaApiEndpointContract]:
    try:
        from nba_api.stats import endpoints
    except Exception:
        return {}

    contracts: dict[str, NbaApiEndpointContract] = {}
    package_path = getattr(endpoints, "__path__", None)
    if package_path is None:
        return contracts

    for module_info in pkgutil.iter_modules(package_path):
        try:
            module = importlib.import_module(f"{endpoints.__name__}.{module_info.name}")
        except Exception:
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if name.startswith("_") or name == "Endpoint":
                continue
            contracts[name] = build_endpoint_contract(obj)
    return contracts


def contract_to_json(contract: NbaApiEndpointContract) -> dict[str, Any]:
    return {
        "runtime_class_name": contract.runtime_class_name,
        "module_name": contract.module_name,
        "endpoint_slug": contract.endpoint_slug,
        "parameters": list(contract.parameters),
        "required_parameters": list(contract.required_parameters),
        "nullable_parameters": list(contract.nullable_parameters),
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
