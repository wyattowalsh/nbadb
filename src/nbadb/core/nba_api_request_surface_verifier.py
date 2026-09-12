"""Independent, no-network verifier for NBA API request closure receipts.

This module deliberately does not use the request surface's discovery,
materialization, or conservation helpers.  It reads the installed ``nba_api``
source as syntax, checks that source against the two canonical pin receipts,
and then recomputes route and closure identities with a separate serializer.
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from importlib import metadata, resources
from pathlib import Path, PurePosixPath
from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote, urlencode

from nbadb.core.nba_api_competition_verifier import (
    NbaApiCompetitionVerificationError,
    verify_pinned_competition_authority,
)
from nbadb.core.nba_api_request_surface import (
    IndependentClosureProof,
    NbaApiRequestSurfaceError,
    RequestClosureReceipt,
    build_pinned_request_surface_payload,
    build_request_surface_authority,
)
from nbadb.core.nba_api_surface_inventory import build_distribution_record_authority
from nbadb.core.nba_api_terminal_state_verifier import (
    IndependentTerminalRequestBinding,
    IndependentTerminalStateProof,
    IndependentTypedUpstreamUnavailableEvidence,
    NbaApiTerminalStateVerificationError,
    build_independent_terminal_state_payload,
    reproduce_terminal_request_binding,
    reproduce_typed_upstream_unavailable_evidence,
    verify_pinned_terminal_state_authority,
)

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_PINNED_VERSION = "1.11.4"
_VERIFIER_ID = "nbadb_independent_package_ast_v1"
_PRIMARY_VERIFIER_ID = "nbadb_request_surface_primary_v2"
_RUNTIME_RESOURCE = "nba_api_runtime_contract_v1_11_4.json"
_REQUEST_RESOURCE = "nba_api_request_surface_v1_11_4.json"
_REQUEST_SCHEMA_VERSION = 3
_REQUEST_DERIVATION_POLICY_VERSION = 6
_TERMINAL_POLICY_SHA256 = "7226e797a685755311b7b9073f905d7288150e3412d52d95423ef0093548388d"
_RELEASE_TERMINAL_REQUEST_STATES = (
    "success_nonempty",
    "success_empty",
    "upstream_unavailable",
)
_INCOMPLETE_REQUEST_STATES = (
    "contract_blocked",
    "transient_failed",
    "response_contract_failed",
    "unattempted",
    "unclassified",
)
_WIRE_REQUEST_STATES = (
    *_RELEASE_TERMINAL_REQUEST_STATES,
    *_INCOMPLETE_REQUEST_STATES,
)
_TERMINAL_EVIDENCE_KINDS = {
    "success_nonempty": "receipt_bound_provider_response",
    "success_empty": "receipt_bound_provider_response",
    "upstream_unavailable": "typed_upstream_unavailable_evidence",
    "contract_blocked": "implementation_or_modeled_contract_gap",
    "transient_failed": "transport_timeout_retry_vpn_or_infrastructure_failure",
    "response_contract_failed": "parser_or_response_contract_failure",
    "unattempted": "budget_cap_policy_or_scheduling_exhaustion",
    "unclassified": "classification_unknown",
}
_PAGINATION_EVIDENCE_FIELDS = {
    "pagination_ordinal",
    "pagination_terminal",
    "pagination_termination_reason",
}
_TERMINAL_REQUIRED_FIELDS = {
    "success_nonempty": {
        "decoded_results_receipt_sha256",
        "http_status",
        "persistence_receipt_sha256",
        "response_body_sha256",
        "result_occurrence",
        "row_count",
    },
    "success_empty": {
        "decoded_results_receipt_sha256",
        "http_status",
        "persistence_receipt_sha256",
        "response_body_sha256",
        "result_occurrence",
        "row_count",
    },
    "upstream_unavailable": set(),
    "contract_blocked": {"contract_evidence_sha256", "reason_code"},
    "transient_failed": {"attempt_count", "failure_class"},
    "response_contract_failed": {"failure_class", "response_body_sha256"},
    "unattempted": {"reason_code"},
    "unclassified": {"classification_input_sha256"},
}
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_SAFE_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}", flags=re.ASCII)
_AUXILIARY_PARAMETERS = frozenset({"proxy", "headers", "timeout", "get_request"})
_PERSON_IDENTIFIER_RE = re.compile(r"^person[12]_id$")
_METRIC_FILTER_RE = re.compile(r"^(?:gt|lt|eq|wrs|btr)_")
_BOUNDED_NUMERIC_PARAMETERS = frozenset(
    {
        "counter",
        "day_offset",
        "end_period",
        "end_period_nullable",
        "end_range",
        "end_range_nullable",
        "group_quantity",
        "last_n_games",
        "last_n_games_nullable",
        "min_games_nullable",
        "minutes_min",
        "month",
        "month_nullable",
        "number_of_games",
        "overall_pick_nullable",
        "period",
        "period_nullable",
        "point_diff",
        "point_diff_nullable",
        "range_type",
        "range_type_nullable",
        "round_num_nullable",
        "round_pick_nullable",
        "start_period",
        "start_period_nullable",
        "start_range",
        "start_range_nullable",
        "topx",
        "topx_nullable",
    }
)
_DYNAMIC_DEFAULT_EXPRESSION_TYPES = {
    "GameDate.default": "str",
    "Season.default": "str",
    "SeasonAll.default": "str",
    "SeasonAll_Time.default": "str",
    "SeasonID.default": "str",
    "SeasonYear.default": "int",
}
_EXPECTED_DYNAMIC_DEFAULT_EXPRESSION_COUNTS = {
    "GameDate.default": 2,
    "Season.default": 77,
    "SeasonAll.default": 1,
    "SeasonAll_Time.default": 1,
    "SeasonID.default": 2,
    "SeasonYear.default": 7,
}
_DYNAMIC_DEFAULT_CLASS_NAMES = frozenset(
    expression.partition(".")[0] for expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
)


def _normalized_source_default(
    family: str,
    endpoint_id: str,
    parameter: Mapping[str, object],
) -> dict[str, object]:
    payload = dict(parameter)
    expression = payload.get("default_expression")
    authority = payload.get("default_authority")
    is_dynamic = expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES
    if is_dynamic != (authority == "provider_dynamic_default_expression_v1"):
        raise NbaApiRequestSurfaceError(
            f"{family} {endpoint_id} default authority differs from source expression"
        )
    if is_dynamic and (
        payload.get("has_default") is not True
        or payload.get("default") is not None
        or payload.get("nullable") is not False
    ):
        raise NbaApiRequestSurfaceError(
            f"{family} {endpoint_id} dynamic default is not stably normalized"
        )
    if not is_dynamic and (
        authority != "provider_literal_or_required_v1" or expression is not None
    ):
        raise NbaApiRequestSurfaceError(
            f"{family} {endpoint_id} literal default retained foreign expression authority"
        )
    return payload


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise NbaApiRequestSurfaceError("independent verifier received noncanonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiRequestSurfaceError(f"{field} is not a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiRequestSurfaceError(
                f"independent authority contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiRequestSurfaceError(
        f"independent authority contains non-finite JSON constant: {value}"
    )


def _load_resource(name: str) -> dict[str, Any]:
    raw = resources.files("nbadb.contracts").joinpath(name).read_bytes()
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiRequestSurfaceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiRequestSurfaceError("independent authority cannot be decoded") from exc
    if not isinstance(payload, dict) or raw != _canonical_bytes(payload) + b"\n":
        raise NbaApiRequestSurfaceError("independent authority is not canonical JSON")
    body = dict(payload)
    recorded = body.pop("payload_sha256", None)
    if _require_digest(recorded, "authority payload_sha256") != _digest(body):
        raise NbaApiRequestSurfaceError("independent authority payload digest is fabricated")
    return cast("dict[str, Any]", payload)


def _literal_assignment(
    nodes: Iterable[ast.stmt],
    name: str,
    *,
    source_root: Path,
) -> object:
    for node in nodes:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            return ast.literal_eval(node.value)
        except (ValueError, TypeError):
            if isinstance(node.value, ast.Name):
                return _imported_literal(nodes, node.value.id, source_root=source_root)
            break
    raise NbaApiRequestSurfaceError(f"installed source lacks literal assignment {name}")


def _imported_literal(
    nodes: Iterable[ast.stmt],
    name: str,
    *,
    source_root: Path,
) -> object:
    for node in nodes:
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        for alias in node.names:
            if (alias.asname or alias.name) != name:
                continue
            path = source_root.joinpath(*node.module.split(".")).with_suffix(".py")
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            return _literal_assignment(tree.body, alias.name, source_root=source_root)
    raise NbaApiRequestSurfaceError(f"installed source cannot resolve imported literal {name}")


def _class_assignment(
    class_node: ast.ClassDef,
    name: str,
    *,
    module_nodes: Iterable[ast.stmt],
    source_root: Path,
) -> object:
    for node in class_node.body:
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            continue
        try:
            return ast.literal_eval(node.value)
        except (ValueError, TypeError):
            if isinstance(node.value, ast.Name):
                return _imported_literal(module_nodes, node.value.id, source_root=source_root)
            break
    raise NbaApiRequestSurfaceError(f"installed endpoint {class_node.name} lacks literal {name}")


def _constructor_parameters(class_node: ast.ClassDef) -> tuple[str, ...]:
    init = next(
        (
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ),
        None,
    )
    if init is None or init.args.vararg is not None or init.args.kwarg is not None:
        raise NbaApiRequestSurfaceError(
            f"installed endpoint {class_node.name} has an unsupported constructor"
        )
    names = tuple(
        argument.arg
        for argument in (*init.args.posonlyargs, *init.args.args, *init.args.kwonlyargs)
    )
    if not names or names[0] != "self":
        raise NbaApiRequestSurfaceError(
            f"installed endpoint {class_node.name} constructor lacks self"
        )
    return tuple(name for name in names[1:] if name not in _AUXILIARY_PARAMETERS)


def _wire_parameters(class_node: ast.ClassDef) -> tuple[tuple[str, str], ...]:
    for node in ast.walk(class_node):
        if not isinstance(node, ast.Assign) or not any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "parameters"
            for target in node.targets
        ):
            continue
        if not isinstance(node.value, ast.Dict):
            break
        result: list[tuple[str, str]] = []
        for key_node, value_node in zip(node.value.keys, node.value.values, strict=True):
            if key_node is None:
                raise NbaApiRequestSurfaceError("wire parameter mapping uses dictionary unpacking")
            try:
                key = ast.literal_eval(key_node)
            except (ValueError, TypeError) as exc:
                raise NbaApiRequestSurfaceError("wire parameter name is not literal") from exc
            if not isinstance(key, str) or not isinstance(value_node, ast.Name):
                raise NbaApiRequestSurfaceError("wire parameter mapping is not static")
            result.append((value_node.id, key))
        return tuple(result)
    raise NbaApiRequestSurfaceError(
        f"installed endpoint {class_node.name} lacks a static wire parameter mapping"
    )


def _live_source_field_paths(value: object, path: str = "$") -> tuple[str, ...]:
    paths: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise NbaApiRequestSurfaceError("live expected-data key is not a string")
            child_path = f"{path}.{key}"
            paths.add(child_path)
            paths.update(_live_source_field_paths(item, child_path))
    elif isinstance(value, list):
        for item in value:
            paths.update(_live_source_field_paths(item, path))
    return tuple(sorted(item for item in paths if item.count(".") > 1))


def _endpoint_class(tree: ast.Module, expected_name: str) -> ast.ClassDef:
    matches = [
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == expected_name
    ]
    if len(matches) != 1:
        raise NbaApiRequestSurfaceError(
            f"installed endpoint source does not define exactly one {expected_name}"
        )
    return matches[0]


def _verify_distribution_sources(
    distribution: metadata.Distribution,
) -> tuple[tuple[dict[str, object], ...], dict[str, object]]:
    try:
        record = build_distribution_record_authority(distribution)
    except ValueError as exc:
        raise NbaApiRequestSurfaceError("installed nba_api RECORD authority is invalid") from exc
    inventory: list[dict[str, object]] = [
        {
            "path": entry.path,
            "sha256": entry.sha256,
            "size": entry.size,
        }
        for entry in record.entries
        if entry.path.startswith("nba_api/") and entry.path.endswith(".py")
    ]
    if not inventory:
        raise NbaApiRequestSurfaceError("installed nba_api distribution has no Python sources")
    return tuple(inventory), record.to_dict()


def _bronze_identifier(value: str) -> str:
    normalized = re.sub(r"[^0-9A-Za-z]+", "_", value).strip("_").lower()
    return re.sub(r"_+", "_", normalized)


def _structured_headers(value: object) -> tuple[str, ...]:
    """Independently flatten the provider's structured shot-location header."""

    if (
        not isinstance(value, list)
        or not value
        or any(not isinstance(item, dict) for item in value)
    ):
        return ()
    rows = cast("list[dict[str, object]]", value)
    columns = next(
        (
            item
            for item in rows
            if _bronze_identifier(str(item.get("name") or "")) == "columns"
            and isinstance(item.get("columnNames"), list)
        ),
        None,
    )
    groups = [
        item
        for item in rows
        if _bronze_identifier(str(item.get("name") or "")) != "columns"
        and isinstance(item.get("columnNames"), list)
        and isinstance(item.get("columnSpan"), int)
        and not isinstance(item.get("columnSpan"), bool)
        and cast("int", item["columnSpan"]) > 0
    ]
    if columns is None or len(groups) != 1:
        raise NbaApiRequestSurfaceError("structured provider headers are ambiguous")
    base = [str(item) for item in cast("list[object]", columns["columnNames"])]
    group = groups[0]
    skip = group.get("columnsToSkip", 0)
    if isinstance(skip, bool) or not isinstance(skip, int) or skip < 0 or skip > len(base):
        raise NbaApiRequestSurfaceError("structured provider header skip count is invalid")
    labels = [_bronze_identifier(str(item)) for item in cast("list[object]", group["columnNames"])]
    span = cast("int", group["columnSpan"])
    metrics = base[skip:]
    if any(not item for item in labels) or len(labels) * span != len(metrics):
        raise NbaApiRequestSurfaceError("structured provider header span is incomplete")
    result = base[:skip] + [
        f"{label}_{_bronze_identifier(metrics[index * span + offset])}"
        for index, label in enumerate(labels)
        for offset in range(span)
    ]
    if any(not item for item in result) or len(result) != len(set(result)):
        raise NbaApiRequestSurfaceError("structured provider headers are invalid")
    return tuple(result)


def _sequence_expression(
    node: ast.AST,
    assignments: Mapping[str, ast.AST],
) -> tuple[str, ...]:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return (node.value,)
    if isinstance(node, ast.Tuple | ast.List):
        result: tuple[str, ...] = ()
        for item in node.elts:
            result += _sequence_expression(item, assignments)
        return result
    if isinstance(node, ast.Name) and node.id in assignments:
        return _sequence_expression(assignments[node.id], assignments)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return _sequence_expression(node.left, assignments) + _sequence_expression(
            node.right, assignments
        )
    raise NbaApiRequestSurfaceError("parser header expression is not a static string sequence")


def _called_header_method(node: ast.AST) -> str:
    candidate = node
    if (
        isinstance(candidate, ast.Call)
        and isinstance(candidate.func, ast.Name)
        and candidate.func.id in {"list", "tuple"}
        and len(candidate.args) == 1
        and not candidate.keywords
    ):
        candidate = candidate.args[0]
    if (
        not isinstance(candidate, ast.Call)
        or candidate.args
        or candidate.keywords
        or not isinstance(candidate.func, ast.Attribute)
        or not isinstance(candidate.func.value, ast.Name)
        or candidate.func.value.id != "self"
    ):
        raise NbaApiRequestSurfaceError("parser result set lacks a static header method")
    return candidate.func.attr


@lru_cache(maxsize=32)
def _parser_headers(source_root: Path, endpoint_slug: str) -> dict[str, tuple[str, ...]]:
    """Read parser header methods as AST without executing provider code."""

    init_path = source_root / "nba_api/stats/endpoints/_parsers/__init__.py"
    init_tree = ast.parse(init_path.read_text(encoding="utf-8"), filename=str(init_path))
    imports: dict[str, str] = {}
    for node in init_tree.body:
        if not isinstance(node, ast.ImportFrom) or node.level != 1 or node.module is None:
            continue
        for alias in node.names:
            imports[alias.asname or alias.name] = node.module
    registry_node = next(
        (
            node.value
            for node in init_tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "_PARSER_REGISTRY"
                for target in node.targets
            )
        ),
        None,
    )
    if not isinstance(registry_node, ast.Dict):
        return {}
    class_name: str | None = None
    for key, value in zip(registry_node.keys, registry_node.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and key.value == endpoint_slug
            and isinstance(value, ast.Name)
        ):
            class_name = value.id
            break
    if class_name is None:
        return {}
    module_short = imports.get(class_name)
    if module_short is None:
        raise NbaApiRequestSurfaceError("parser registry class import is ambiguous")
    parser_path = source_root / f"nba_api/stats/endpoints/_parsers/{module_short}.py"
    parser_tree = ast.parse(parser_path.read_text(encoding="utf-8"), filename=str(parser_path))
    class_node = _endpoint_class(parser_tree, class_name)
    assignments: dict[str, ast.AST] = {
        target.id: node.value
        for node in parser_tree.body
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance((target := node.targets[0]), ast.Name)
    }
    methods = {node.name: node for node in class_node.body if isinstance(node, ast.FunctionDef)}
    data_method = methods.get("get_data_sets")
    if data_method is None:
        raise NbaApiRequestSurfaceError("registered parser lacks get_data_sets")
    returned = [node.value for node in ast.walk(data_method) if isinstance(node, ast.Return)]
    if len(returned) != 1 or not isinstance(returned[0], ast.Dict):
        return {}
    result: dict[str, tuple[str, ...]] = {}
    for key, value in zip(returned[0].keys, returned[0].values, strict=True):
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise NbaApiRequestSurfaceError("parser result-set identity is not literal")
        if not isinstance(value, ast.Dict):
            raise NbaApiRequestSurfaceError("parser result-set payload is not literal")
        headers_node = next(
            (
                item
                for nested_key, item in zip(value.keys, value.values, strict=True)
                if isinstance(nested_key, ast.Constant) and nested_key.value == "headers"
            ),
            None,
        )
        if headers_node is None:
            raise NbaApiRequestSurfaceError("parser result set omits headers")
        method_name = _called_header_method(headers_node)
        method = methods.get(method_name)
        if method is None:
            continue
        method_returns = [node.value for node in ast.walk(method) if isinstance(node, ast.Return)]
        if len(method_returns) != 1:
            continue
        method_return = method_returns[0]
        if method_return is None:
            continue
        try:
            headers = _sequence_expression(method_return, assignments)
        except NbaApiRequestSurfaceError:
            continue
        if not headers or len(headers) != len(set(headers)):
            raise NbaApiRequestSurfaceError("parser headers are empty or duplicated")
        result[key.value] = headers
    return result


def _derived_result_headers(
    source_root: Path,
    endpoint_slug: str,
    result_set_name: str,
    source_value: object,
) -> tuple[str, ...]:
    parser = _parser_headers(source_root, endpoint_slug)
    if result_set_name in parser:
        return parser[result_set_name]
    if isinstance(source_value, list) and all(isinstance(item, str) for item in source_value):
        headers = tuple(cast("list[str]", source_value))
        if len(headers) != len(set(headers)):
            raise NbaApiRequestSurfaceError("provider source headers are duplicated")
        return headers
    headers = _structured_headers(source_value)
    if not headers:
        raise NbaApiRequestSurfaceError("provider source headers cannot be derived")
    return headers


def _constructor_default_expressions(
    class_node: ast.ClassDef,
    ast_parameters: tuple[str, ...],
) -> dict[str, str | None]:
    init = next(
        (
            node
            for node in class_node.body
            if isinstance(node, ast.FunctionDef) and node.name == "__init__"
        ),
        None,
    )
    if init is None:
        raise NbaApiRequestSurfaceError(
            f"installed endpoint {class_node.name} lacks constructor defaults"
        )
    positional = (*init.args.posonlyargs, *init.args.args)
    defaults: dict[str, ast.expr | None] = dict.fromkeys(
        (argument.arg for argument in positional),
        None,
    )
    positional_with_defaults = positional[-len(init.args.defaults) :] if init.args.defaults else ()
    for argument, default in zip(
        positional_with_defaults,
        init.args.defaults,
        strict=True,
    ):
        defaults[argument.arg] = default
    defaults.update(
        {
            argument.arg: default
            for argument, default in zip(
                init.args.kwonlyargs,
                init.args.kw_defaults,
                strict=True,
            )
        }
    )
    if any(name not in defaults for name in ast_parameters):
        raise NbaApiRequestSurfaceError(
            "installed constructor parameters differ from default-expression authority"
        )
    return {
        name: ast.unparse(default) if (default := defaults[name]) is not None else None
        for name in ast_parameters
    }


def _signature_rows(
    module_name: str,
    class_name: str,
    ast_parameters: tuple[str, ...],
    class_node: ast.ClassDef,
) -> tuple[dict[str, object], ...]:
    module = importlib.import_module(module_name)
    runtime_class = getattr(module, class_name, None)
    if not inspect.isclass(runtime_class):
        raise NbaApiRequestSurfaceError("installed endpoint class is unavailable")
    try:
        signature = inspect.signature(runtime_class.__init__)
    except (TypeError, ValueError) as exc:
        raise NbaApiRequestSurfaceError("installed endpoint signature is unavailable") from exc
    default_expressions = _constructor_default_expressions(class_node, ast_parameters)
    rows: list[dict[str, object]] = []
    for name, parameter in signature.parameters.items():
        if name == "self" or name in _AUXILIARY_PARAMETERS:
            continue
        has_default = parameter.default is not inspect.Parameter.empty
        raw_default = parameter.default if has_default else None
        if raw_default is not None and type(raw_default) not in {str, bool, int, float}:
            raise NbaApiRequestSurfaceError("installed endpoint default is not a JSON scalar")
        expression = default_expressions[name]
        if expression in _DYNAMIC_DEFAULT_EXPRESSION_TYPES:
            if (
                not has_default
                or type(raw_default).__name__ != (_DYNAMIC_DEFAULT_EXPRESSION_TYPES[expression])
            ):
                raise NbaApiRequestSurfaceError(
                    "installed dynamic default differs from source expression type"
                )
            default = None
            default_authority = "provider_dynamic_default_expression_v1"
            default_expression = expression
        else:
            expression_owner = expression.partition(".")[0] if expression else None
            if expression_owner in _DYNAMIC_DEFAULT_CLASS_NAMES:
                raise NbaApiRequestSurfaceError(
                    "installed dynamic default uses an unsupported source expression"
                )
            default = raw_default
            default_authority = "provider_literal_or_required_v1"
            default_expression = None
        rows.append(
            {
                "ordinal": len(rows),
                "name": name,
                "required": not has_default,
                "nullable": has_default and (raw_default is None or name.endswith("_nullable")),
                "has_default": has_default,
                "default": default,
                "default_authority": default_authority,
                "default_expression": default_expression,
            }
        )
    if tuple(cast("str", row["name"]) for row in rows) != ast_parameters:
        raise NbaApiRequestSurfaceError("runtime signature differs from installed source AST")
    return tuple(rows)


def _stats_inventory(
    source_root: Path,
    contracts: Mapping[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for endpoint_id, raw_contract in sorted(contracts.items()):
        if not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("stats runtime contract is malformed")
        contract = cast("dict[str, Any]", raw_contract)
        module_name = contract.get("module_name")
        class_name = contract.get("runtime_class_name")
        if not isinstance(module_name, str) or not isinstance(class_name, str):
            raise NbaApiRequestSurfaceError("stats runtime identity is malformed")
        path = source_root.joinpath(*module_name.split(".")).with_suffix(".py")
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        class_node = _endpoint_class(tree, class_name)
        endpoint_slug = _class_assignment(
            class_node,
            "endpoint",
            module_nodes=tree.body,
            source_root=source_root,
        )
        try:
            expected_data = _class_assignment(
                class_node,
                "expected_data",
                module_nodes=tree.body,
                source_root=source_root,
            )
        except NbaApiRequestSurfaceError:
            # A small exact-pin subset builds a class constant from a parser
            # constant.  Importing the module does not instantiate the endpoint
            # or perform I/O, and the AST checks above still own its identity.
            module = importlib.import_module(module_name)
            expected_data = getattr(getattr(module, class_name), "expected_data", None)
        parameters = _constructor_parameters(class_node)
        wire_parameters = _wire_parameters(class_node)
        if endpoint_slug != contract.get("endpoint_slug"):
            raise NbaApiRequestSurfaceError("stats endpoint slug differs from installed source")
        if parameters != tuple(contract.get("parameters", ())):
            raise NbaApiRequestSurfaceError(
                "stats parameter inventory differs from installed source"
            )
        expected_wire = tuple(
            (item.get("name"), item.get("query_name"))
            for item in contract.get("parameter_query_names", ())
            if isinstance(item, dict)
        )
        if wire_parameters != expected_wire:
            raise NbaApiRequestSurfaceError("stats wire mapping differs from installed source")
        if not isinstance(expected_data, dict):
            raise NbaApiRequestSurfaceError("stats expected_data is not an object")
        expected_sets = tuple(
            (
                name,
                index,
                columns,
                _derived_result_headers(
                    source_root,
                    cast("str", endpoint_slug),
                    name,
                    columns,
                ),
            )
            for index, (name, columns) in enumerate(expected_data.items())
            if isinstance(name, str)
        )
        contract_sets = tuple(
            (
                item.get("result_set_name"),
                item.get("result_set_index"),
                tuple(item.get("expected_columns", ())),
            )
            for item in contract.get("result_sets", ())
            if isinstance(item, dict)
        )
        identities_match = tuple((name, ordinal) for name, ordinal, _, _ in expected_sets) == tuple(
            (name, ordinal) for name, ordinal, _ in contract_sets
        )
        headers_match = all(
            derived_headers == tuple(contract_headers)
            for (_, _, _, derived_headers), (_, _, contract_headers) in zip(
                expected_sets,
                contract_sets,
                strict=True,
            )
        )
        if len(expected_sets) != len(expected_data) or not identities_match or not headers_match:
            raise NbaApiRequestSurfaceError(
                "stats result-set/header ordinals differ from installed source"
            )
        signature_rows = _signature_rows(module_name, class_name, parameters, class_node)
        query_by_name = dict(wire_parameters)
        parameter_rows = [
            {**row, "query_name": query_by_name[cast("str", row["name"])], "location": "query"}
            for row in signature_rows
        ]
        result.append(
            {
                "source_family": "stats",
                "endpoint_id": endpoint_id,
                "module_name": module_name,
                "endpoint_slug": endpoint_slug,
                "parameters": parameter_rows,
                "wire_parameters": [list(item) for item in wire_parameters],
                "result_sets": [
                    {
                        "name": name,
                        "ordinal": ordinal,
                        "headers": list(derived_headers),
                        "raw_item_count": len(cast("list[object]", source_headers)),
                    }
                    for (name, ordinal, source_headers, derived_headers), _ in zip(
                        expected_sets, contract_sets, strict=True
                    )
                ],
            }
        )
    observed_dynamic_defaults = Counter(
        parameter.get("default_expression")
        for endpoint in result
        for parameter in cast("list[dict[str, object]]", endpoint["parameters"])
        if parameter.get("default_authority") == "provider_dynamic_default_expression_v1"
    )
    if (
        dict(sorted(observed_dynamic_defaults.items()))
        != _EXPECTED_DYNAMIC_DEFAULT_EXPRESSION_COUNTS
    ):
        raise NbaApiRequestSurfaceError(
            "installed dynamic-default expression inventory differs from the exact pin"
        )
    return result


def _live_inventory(
    source_root: Path,
    contracts: Mapping[str, object],
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for endpoint_id, raw_contract in sorted(contracts.items()):
        if not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("live runtime contract is malformed")
        contract = cast("dict[str, Any]", raw_contract)
        source_path = contract.get("source_path")
        class_name = contract.get("endpoint_id")
        if not isinstance(source_path, str) or not isinstance(class_name, str):
            raise NbaApiRequestSurfaceError("live runtime identity is malformed")
        path = source_root / source_path
        source = path.read_bytes()
        if hashlib.sha256(source).hexdigest() != contract.get("source_sha256"):
            raise NbaApiRequestSurfaceError("live endpoint source digest differs from pin")
        tree = ast.parse(source.decode("utf-8"), filename=str(path))
        class_node = _endpoint_class(tree, class_name)
        endpoint_url = _class_assignment(
            class_node,
            "endpoint_url",
            module_nodes=tree.body,
            source_root=source_root,
        )
        if not isinstance(endpoint_url, str):
            raise NbaApiRequestSurfaceError("live endpoint URL is not a string")
        expected_data = _class_assignment(
            class_node,
            "expected_data",
            module_nodes=tree.body,
            source_root=source_root,
        )
        parameters = _constructor_parameters(class_node)
        contract_parameters = tuple(
            item.get("name") for item in contract.get("parameters", ()) if isinstance(item, dict)
        )
        if (
            endpoint_url != contract.get("endpoint_url_template")
            or parameters != contract_parameters
        ):
            raise NbaApiRequestSurfaceError("live endpoint parameters differ from installed source")
        source_field_paths = _live_source_field_paths(expected_data)
        contract_paths = {
            field.get("json_path")
            for result_set in contract.get("result_sets", ())
            if isinstance(result_set, dict)
            for field in result_set.get("fields", ())
            if isinstance(field, dict)
            and field.get("source_field") is True
            and field.get("provenance_source") == "nba_api_live_expected_data"
        }
        if set(source_field_paths) != contract_paths:
            raise NbaApiRequestSurfaceError(
                "live expected-data fields differ from installed source"
            )
        signature_rows = _signature_rows(
            cast("str", contract.get("runtime_module")),
            class_name,
            parameters,
            class_node,
        )
        path_parameters = {
            match.group("name")
            for match in re.finditer(r"\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}", endpoint_url)
        }
        parameter_rows = [
            {
                **row,
                "query_name": "".join(
                    part.upper() if part == "id" else part[:1].upper() + part[1:]
                    for part in cast("str", row["name"]).split("_")
                ),
                "location": "path" if row["name"] in path_parameters else "query",
            }
            for row in signature_rows
        ]
        result_sets = tuple(
            {
                "name": item.get("name"),
                "ordinal": item.get("ordinal"),
                "json_path": item.get("json_path"),
                "headers": [
                    {"name": field.get("name"), "ordinal": field.get("ordinal")}
                    for field in item.get("fields", ())
                    if isinstance(field, dict)
                ],
            }
            for item in contract.get("result_sets", ())
            if isinstance(item, dict)
        )
        result.append(
            {
                "source_family": "live",
                "endpoint_id": endpoint_id,
                "module_name": contract.get("runtime_module"),
                "endpoint_slug": contract.get("endpoint_slug"),
                "endpoint_url": endpoint_url,
                "parameters": parameter_rows,
                "source_field_paths": list(source_field_paths),
                "result_sets": list(result_sets),
            }
        )
    return result


def _function_parameters(node: ast.FunctionDef) -> tuple[str, ...]:
    if node.args.vararg is not None or node.args.kwarg is not None:
        raise NbaApiRequestSurfaceError("static helper has variadic parameters")
    return tuple(
        argument.arg
        for argument in (*node.args.posonlyargs, *node.args.args, *node.args.kwonlyargs)
    )


def _function_required_parameters(node: ast.FunctionDef) -> tuple[str, ...]:
    positional = (*node.args.posonlyargs, *node.args.args)
    required_positional = positional[: len(positional) - len(node.args.defaults)]
    required_keyword_only = tuple(
        argument
        for argument, default in zip(
            node.args.kwonlyargs,
            node.args.kw_defaults,
            strict=True,
        )
        if default is None
    )
    return tuple(argument.arg for argument in (*required_positional, *required_keyword_only))


def _static_inventory(
    source_root: Path,
    contracts: Mapping[str, object],
    helper_manifest: object,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    datasets: list[dict[str, object]] = []
    module_helpers: dict[str, tuple[str, ...]] = {}
    for dataset_id, raw_contract in sorted(contracts.items()):
        if not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("static runtime contract is malformed")
        contract = cast("dict[str, Any]", raw_contract)
        provider_path = contract.get("provider_source_path")
        data_path = contract.get("data_source_path")
        source_symbol = contract.get("source_symbol")
        if not all(isinstance(item, str) for item in (provider_path, data_path, source_symbol)):
            raise NbaApiRequestSurfaceError("static source authority is malformed")
        provider_source = (source_root / cast("str", provider_path)).read_bytes()
        data_source = (source_root / cast("str", data_path)).read_bytes()
        if hashlib.sha256(provider_source).hexdigest() != contract.get("provider_source_sha256"):
            raise NbaApiRequestSurfaceError("static helper source digest differs from pin")
        if hashlib.sha256(data_source).hexdigest() != contract.get("data_source_sha256"):
            raise NbaApiRequestSurfaceError("static data source digest differs from pin")
        data_tree = ast.parse(data_source.decode("utf-8"), filename=cast("str", data_path))
        rows = _literal_assignment(
            data_tree.body,
            cast("str", source_symbol),
            source_root=source_root,
        )
        if not isinstance(rows, list) or not rows or any(not isinstance(row, list) for row in rows):
            raise NbaApiRequestSurfaceError("static embedded array is malformed")
        typed_rows = cast("list[list[object]]", rows)
        row_widths = {len(row) for row in typed_rows}
        if len(row_widths) != 1:
            raise NbaApiRequestSurfaceError("static embedded array is ragged")
        if len(rows) != contract.get("row_count") or _digest(rows) != contract.get(
            "source_rows_sha256"
        ):
            raise NbaApiRequestSurfaceError("static embedded array differs from pin")
        provider_tree = ast.parse(
            provider_source.decode("utf-8"), filename=cast("str", provider_path)
        )
        if cast("str", provider_path) not in module_helpers:
            module_helpers[cast("str", provider_path)] = tuple(
                node.name
                for node in provider_tree.body
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
            )
        datasets.append(
            {
                "dataset_id": dataset_id,
                "source_symbol": source_symbol,
                "row_count": len(rows),
                "row_width": next(iter(row_widths)),
                "embedded_body_sha256": _digest(rows),
            }
        )

    if not isinstance(helper_manifest, list):
        raise NbaApiRequestSurfaceError("static helper manifest is malformed")
    helpers: list[dict[str, object]] = []
    seen_functions: set[tuple[str, str]] = set()
    for raw_helper in helper_manifest:
        if not isinstance(raw_helper, dict):
            raise NbaApiRequestSurfaceError("static helper manifest entry is malformed")
        helper = cast("dict[str, Any]", raw_helper)
        helper_id = helper.get("helper_id")
        if not isinstance(helper_id, str) or "." not in helper_id:
            raise NbaApiRequestSurfaceError("static helper identity is malformed")
        module_short, function_name = helper_id.split(".", 1)
        path_text = f"nba_api/stats/static/{module_short}.py"
        path = source_root / path_text
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        matches = [
            node
            for node in tree.body
            if isinstance(node, ast.FunctionDef) and node.name == function_name
        ]
        if len(matches) != 1 or (path_text, function_name) in seen_functions:
            raise NbaApiRequestSurfaceError("static helper inventory is incomplete or duplicated")
        seen_functions.add((path_text, function_name))
        parameters = _function_parameters(matches[0])
        required_parameters = _function_required_parameters(matches[0])
        if parameters != tuple(helper.get("parameters", ())):
            raise NbaApiRequestSurfaceError("static helper signature differs from installed source")
        if required_parameters != tuple(helper.get("required_parameters", ())):
            raise NbaApiRequestSurfaceError(
                "static helper required signature differs from installed source"
            )
        helpers.append(
            {
                "helper_id": helper_id,
                "dataset_id": helper.get("dataset_id"),
                "helper_kind": helper.get("helper_kind"),
                "scope": helper.get("scope_status"),
                "parameters": list(parameters),
                "required_parameters": list(required_parameters),
            }
        )
    expected_functions = {(path, name) for path, names in module_helpers.items() for name in names}
    if seen_functions != expected_functions:
        raise NbaApiRequestSurfaceError("public static helper set differs from installed source")
    return datasets, helpers


@dataclass(frozen=True, slots=True)
class IndependentPackageInventory:
    """Canonical counts and digest independently derived from installed source."""

    stats_endpoint_count: int
    live_endpoint_count: int
    parameter_occurrence_count: int
    result_set_count: int
    header_occurrence_count: int
    static_dataset_count: int
    static_embedded_row_count: int
    static_helper_count: int
    distribution_record_entry_count: int
    distribution_record_hashed_entry_count: int
    distribution_record_authority_sha256: str
    source_atom_count: int
    source_atoms_sha256: str
    independently_derived_extended_header_count: int
    inventory_sha256: str


@dataclass(frozen=True, slots=True)
class _VerifierAuthority:
    runtime: dict[str, Any]
    request: dict[str, Any]
    endpoint_manifest: dict[tuple[str, str], dict[str, Any]]
    source_atoms: tuple[dict[str, object], ...]
    inventory: IndependentPackageInventory
    terminal_proof: IndependentTerminalStateProof


def _terminal_policy_authority() -> IndependentTerminalStateProof:
    """Authenticate the stable terminal policy without its primary compiler."""

    expected = build_independent_terminal_state_payload()
    try:
        proof = verify_pinned_terminal_state_authority()
    except NbaApiTerminalStateVerificationError as exc:
        raise NbaApiRequestSurfaceError("independent terminal policy authority is invalid") from exc
    if type(proof) is not IndependentTerminalStateProof:
        raise NbaApiRequestSurfaceError(
            "independent terminal policy proof has a foreign concrete type"
        )
    expected_release = expected.get("release_terminal_request_states")
    expected_incomplete = expected.get("incomplete_request_states")
    expected_wire = expected.get("wire_request_states")
    observed_kinds = {
        contract.state: contract.evidence_kind for contract in proof.accounting_state_contracts
    }
    if (
        expected_release != list(_RELEASE_TERMINAL_REQUEST_STATES)
        or expected_incomplete != list(_INCOMPLETE_REQUEST_STATES)
        or expected_wire != list(_WIRE_REQUEST_STATES)
        or expected.get("terminal_policy_sha256") != _TERMINAL_POLICY_SHA256
        or proof.release_terminal_request_states != _RELEASE_TERMINAL_REQUEST_STATES
        or proof.incomplete_request_states != _INCOMPLETE_REQUEST_STATES
        or proof.wire_request_states != _WIRE_REQUEST_STATES
        or proof.terminal_policy_sha256 != _TERMINAL_POLICY_SHA256
        or proof.checked_payload_sha256 != expected.get("payload_sha256")
        or observed_kinds != _TERMINAL_EVIDENCE_KINDS
    ):
        raise NbaApiRequestSurfaceError(
            "independent terminal policy differs from the exact 3/5 partition"
        )
    return proof


def _validate_request_terminal_binding(
    request: dict[str, Any],
    *,
    terminal_proof: IndependentTerminalStateProof,
    competition_payload_sha256: str,
) -> None:
    """Require request schema 3/policy 6 to bind the exact terminal policy."""

    if (
        request.get("schema_version") != _REQUEST_SCHEMA_VERSION
        or request.get("derivation_policy_version") != _REQUEST_DERIVATION_POLICY_VERSION
    ):
        raise NbaApiRequestSurfaceError(
            "independent request authority schema or derivation policy is unsupported"
        )
    if (
        request.get("terminal_policy_sha256") != terminal_proof.terminal_policy_sha256
        or request.get("release_terminal_request_states")
        != list(terminal_proof.release_terminal_request_states)
        or request.get("incomplete_request_states")
        != list(terminal_proof.incomplete_request_states)
        or request.get("terminal_evidence_kinds") != _TERMINAL_EVIDENCE_KINDS
        or "terminal_request_states" in request
        or "nonterminal_request_states" in request
    ):
        raise NbaApiRequestSurfaceError(
            "request surface differs from the exact independent terminal policy"
        )
    reserved = request.get("reserved_authorities")
    if not isinstance(reserved, dict) or set(reserved) != {
        "league_finite_values",
        "release_terminal_state",
    }:
        raise NbaApiRequestSurfaceError("request surface reserved authorities are malformed")
    if reserved.get("league_finite_values") != competition_payload_sha256:
        raise NbaApiRequestSurfaceError(
            "request surface differs from independent competition authority"
        )
    if reserved.get("release_terminal_state") != terminal_proof.terminal_policy_sha256:
        raise NbaApiRequestSurfaceError(
            "request surface differs from independent terminal policy authority"
        )


def _canonical_atoms(atoms: list[dict[str, object]]) -> tuple[dict[str, object], ...]:
    identifiers = [atom.get("atom_id") for atom in atoms]
    if any(not isinstance(item, str) or not item for item in identifiers):
        raise NbaApiRequestSurfaceError("source atom identity is invalid")
    if len(identifiers) != len(set(identifiers)):
        raise NbaApiRequestSurfaceError("source atom identity is duplicated")
    return tuple(sorted(atoms, key=lambda item: cast("str", item["atom_id"])))


def _source_atoms(
    stats: list[dict[str, object]],
    live: list[dict[str, object]],
    datasets: list[dict[str, object]],
    helpers: list[dict[str, object]],
) -> tuple[dict[str, object], ...]:
    atoms: list[dict[str, object]] = []
    for endpoint in (*stats, *live):
        family = cast("str", endpoint["source_family"])
        endpoint_id = cast("str", endpoint["endpoint_id"])
        atoms.append(
            {
                "atom_id": f"endpoint:{family}:{endpoint_id}",
                "kind": "endpoint",
                "source_family": family,
                "endpoint_id": endpoint_id,
                "module_name": endpoint["module_name"],
                "endpoint_slug": endpoint["endpoint_slug"],
                "request_method": "GET",
            }
        )
        for parameter in cast("list[dict[str, object]]", endpoint["parameters"]):
            ordinal = cast("int", parameter["ordinal"])
            normalized_parameter = _normalized_source_default(
                family,
                endpoint_id,
                parameter,
            )
            atoms.append(
                {
                    "atom_id": f"parameter:{family}:{endpoint_id}:{ordinal:04d}",
                    "kind": "parameter_occurrence",
                    "source_family": family,
                    "endpoint_id": endpoint_id,
                    **normalized_parameter,
                }
            )
    for endpoint in stats:
        endpoint_id = cast("str", endpoint["endpoint_id"])
        for result_set in cast("list[dict[str, object]]", endpoint["result_sets"]):
            result_ordinal = cast("int", result_set["ordinal"])
            for header_ordinal, header in enumerate(cast("list[str]", result_set["headers"])):
                atoms.append(
                    {
                        "atom_id": (
                            f"stats_header:{endpoint_id}:{result_ordinal:04d}:{header_ordinal:04d}"
                        ),
                        "kind": "stats_result_header",
                        "endpoint_id": endpoint_id,
                        "result_set_name": result_set["name"],
                        "result_set_ordinal": result_ordinal,
                        "header_ordinal": header_ordinal,
                        "header": header,
                    }
                )
    for endpoint in live:
        endpoint_id = cast("str", endpoint["endpoint_id"])
        for path in cast("list[str]", endpoint["source_field_paths"]):
            atoms.append(
                {
                    "atom_id": f"live_source_field:{endpoint_id}:{path}",
                    "kind": "live_source_field",
                    "endpoint_id": endpoint_id,
                    "json_path": path,
                }
            )
    for dataset in datasets:
        dataset_id = cast("str", dataset["dataset_id"])
        atoms.append(
            {
                "atom_id": f"static_dataset:{dataset_id}",
                "kind": "static_dataset",
                **dataset,
            }
        )
    for helper in helpers:
        helper_id = cast("str", helper["helper_id"])
        atoms.append(
            {
                "atom_id": f"static_helper:{helper_id}",
                "kind": "static_helper",
                **helper,
            }
        )
    return _canonical_atoms(atoms)


def _primary_surface_atoms() -> tuple[dict[str, object], ...]:
    authority = build_request_surface_authority()
    runtime = _load_resource(_RUNTIME_RESOURCE)
    atoms: list[dict[str, object]] = []
    for endpoint in authority.endpoints:
        atoms.append(
            {
                "atom_id": f"endpoint:{endpoint.source_family}:{endpoint.endpoint_id}",
                "kind": "endpoint",
                "source_family": endpoint.source_family,
                "endpoint_id": endpoint.endpoint_id,
                "module_name": endpoint.module_name,
                "endpoint_slug": endpoint.endpoint_slug,
                "request_method": endpoint.request_method,
            }
        )
        for parameter in endpoint.parameters:
            normalized_parameter = _normalized_source_default(
                endpoint.source_family,
                endpoint.endpoint_id,
                {
                    "ordinal": parameter.ordinal,
                    "name": parameter.name,
                    "required": parameter.required,
                    "nullable": parameter.nullable,
                    "has_default": parameter.has_default,
                    "default": parameter.default,
                    "default_authority": parameter.default_authority,
                    "default_expression": parameter.default_expression,
                    "query_name": parameter.query_name,
                    "location": parameter.location,
                },
            )
            atoms.append(
                {
                    "atom_id": (
                        f"parameter:{endpoint.source_family}:{endpoint.endpoint_id}:"
                        f"{parameter.ordinal:04d}"
                    ),
                    "kind": "parameter_occurrence",
                    "source_family": endpoint.source_family,
                    "endpoint_id": endpoint.endpoint_id,
                    **normalized_parameter,
                }
            )
    stats_contracts = runtime.get("contracts")
    live_contracts = runtime.get("live_contracts")
    if not isinstance(stats_contracts, dict) or not isinstance(live_contracts, dict):
        raise NbaApiRequestSurfaceError("primary runtime source atom inventory is malformed")
    for endpoint_id, raw_contract in sorted(stats_contracts.items()):
        if not isinstance(endpoint_id, str) or not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("primary stats source atom is malformed")
        raw_result_sets = raw_contract.get("result_sets")
        if not isinstance(raw_result_sets, list):
            raise NbaApiRequestSurfaceError("primary stats result-set inventory is malformed")
        for result_set in raw_result_sets:
            if not isinstance(result_set, dict):
                raise NbaApiRequestSurfaceError("primary stats result-set atom is malformed")
            result_ordinal = result_set.get("result_set_index")
            headers = result_set.get("expected_columns")
            if (
                isinstance(result_ordinal, bool)
                or not isinstance(result_ordinal, int)
                or not isinstance(headers, list)
            ):
                raise NbaApiRequestSurfaceError("primary stats header atom is malformed")
            for header_ordinal, header in enumerate(headers):
                if not isinstance(header, str):
                    raise NbaApiRequestSurfaceError("primary stats header is not a string")
                atoms.append(
                    {
                        "atom_id": (
                            f"stats_header:{endpoint_id}:{result_ordinal:04d}:{header_ordinal:04d}"
                        ),
                        "kind": "stats_result_header",
                        "endpoint_id": endpoint_id,
                        "result_set_name": result_set.get("result_set_name"),
                        "result_set_ordinal": result_ordinal,
                        "header_ordinal": header_ordinal,
                        "header": header,
                    }
                )
    for endpoint_id, raw_contract in sorted(live_contracts.items()):
        if not isinstance(endpoint_id, str) or not isinstance(raw_contract, dict):
            raise NbaApiRequestSurfaceError("primary live source atom is malformed")
        raw_result_sets = raw_contract.get("result_sets")
        if not isinstance(raw_result_sets, list):
            raise NbaApiRequestSurfaceError("primary live result-set inventory is malformed")
        for result_set in raw_result_sets:
            if not isinstance(result_set, dict):
                raise NbaApiRequestSurfaceError("primary live result-set atom is malformed")
            raw_fields = result_set.get("fields")
            if not isinstance(raw_fields, list):
                raise NbaApiRequestSurfaceError("primary live field inventory is malformed")
            for field in raw_fields:
                if (
                    isinstance(field, dict)
                    and field.get("source_field") is True
                    and field.get("provenance_source") == "nba_api_live_expected_data"
                ):
                    path = field.get("json_path")
                    if not isinstance(path, str):
                        raise NbaApiRequestSurfaceError("primary live field path is invalid")
                    atoms.append(
                        {
                            "atom_id": f"live_source_field:{endpoint_id}:{path}",
                            "kind": "live_source_field",
                            "endpoint_id": endpoint_id,
                            "json_path": path,
                        }
                    )
    for dataset in authority.static_datasets:
        atoms.append(
            {
                "atom_id": f"static_dataset:{dataset.dataset_id}",
                "kind": "static_dataset",
                "dataset_id": dataset.dataset_id,
                "source_symbol": dataset.source_symbol,
                "row_count": dataset.row_count,
                "row_width": dataset.row_width,
                "embedded_body_sha256": dataset.embedded_body_sha256,
            }
        )
    for helper in authority.static_helpers:
        atoms.append(
            {
                "atom_id": f"static_helper:{helper.helper_id}",
                "kind": "static_helper",
                "helper_id": helper.helper_id,
                "dataset_id": helper.dataset_id,
                "helper_kind": helper.helper_kind,
                "scope": helper.scope_status,
                "parameters": list(helper.parameters),
                "required_parameters": list(helper.required_parameters),
            }
        )
    return _canonical_atoms(atoms)


@lru_cache(maxsize=1)
def _authority() -> _VerifierAuthority:
    terminal_proof = _terminal_policy_authority()
    try:
        distribution = metadata.distribution("nba_api")
    except metadata.PackageNotFoundError as exc:
        raise NbaApiRequestSurfaceError("pinned nba_api distribution is not installed") from exc
    if distribution.version != _PINNED_VERSION:
        raise NbaApiRequestSurfaceError("installed nba_api version differs from the exact pin")
    runtime = _load_resource(_RUNTIME_RESOURCE)
    if runtime.get("schema_version") != 4:
        raise NbaApiRequestSurfaceError("independent authority schema version is unsupported")
    provider = runtime.get("provider")
    if not isinstance(provider, dict) or provider.get("version") != _PINNED_VERSION:
        raise NbaApiRequestSurfaceError("runtime provider authority differs from installed pin")
    try:
        competition_proof = verify_pinned_competition_authority()
    except NbaApiCompetitionVerificationError as exc:
        raise NbaApiRequestSurfaceError("independent competition authority is invalid") from exc
    expected_request = build_pinned_request_surface_payload()
    if type(expected_request) is not dict:
        raise NbaApiRequestSurfaceError("rebuilt request authority has a foreign concrete type")
    _validate_request_terminal_binding(
        expected_request,
        terminal_proof=terminal_proof,
        competition_payload_sha256=competition_proof.checked_payload_sha256,
    )
    if expected_request.get("runtime_contract_payload_sha256") != runtime.get("payload_sha256"):
        raise NbaApiRequestSurfaceError("request and runtime authorities are unrelated")
    rebuilt_authority = build_request_surface_authority()
    if (
        rebuilt_authority.runtime_contract_payload_sha256 != runtime.get("payload_sha256")
        or rebuilt_authority.terminal_policy_sha256 != terminal_proof.terminal_policy_sha256
        or expected_request.get("surface_sha256") != rebuilt_authority.surface_sha256
    ):
        raise NbaApiRequestSurfaceError(
            "checked request surface differs from rebuilt exact authority"
        )
    manifest = expected_request.get("manifest")
    if not isinstance(manifest, dict) or expected_request.get("manifest_sha256") != _digest(
        manifest
    ):
        raise NbaApiRequestSurfaceError("rebuilt request manifest digest is fabricated")
    endpoint_rows = manifest.get("endpoint_contracts")
    if not isinstance(endpoint_rows, list):
        raise NbaApiRequestSurfaceError("request endpoint manifest is malformed")
    endpoint_manifest: dict[tuple[str, str], dict[str, Any]] = {}
    for raw in endpoint_rows:
        if not isinstance(raw, dict):
            raise NbaApiRequestSurfaceError("request endpoint entry is malformed")
        row = cast("dict[str, Any]", raw)
        key = (row.get("source_family"), row.get("endpoint_id"))
        if not all(isinstance(item, str) for item in key) or key in endpoint_manifest:
            raise NbaApiRequestSurfaceError("request endpoint inventory is duplicated")
        endpoint_manifest[cast("tuple[str, str]", key)] = row

    source_inventory, record_authority = _verify_distribution_sources(distribution)
    source_root = Path(str(distribution.locate_file(""))).resolve(strict=True)
    stats_contracts = runtime.get("contracts")
    live_contracts = runtime.get("live_contracts")
    static_contracts = runtime.get("static_contracts")
    if not all(
        isinstance(item, dict) for item in (stats_contracts, live_contracts, static_contracts)
    ):
        raise NbaApiRequestSurfaceError("runtime inventories are malformed")
    source_paths = {cast("str", item["path"]) for item in source_inventory}
    installed_stats_modules = {
        path.removesuffix(".py").replace("/", ".")
        for path in source_paths
        if path.startswith("nba_api/stats/endpoints/")
        and len(PurePosixPath(path).parts) == 4
        and not PurePosixPath(path).name.startswith("_")
    }
    installed_live_modules = {
        path.removesuffix(".py").replace("/", ".")
        for path in source_paths
        if path.startswith("nba_api/live/nba/endpoints/")
        and len(PurePosixPath(path).parts) == 5
        and not PurePosixPath(path).name.startswith("_")
    }
    contracted_stats_modules = {
        item.get("module_name")
        for item in cast("dict[str, Any]", stats_contracts).values()
        if isinstance(item, dict)
    }
    contracted_live_modules = {
        item.get("runtime_module")
        for item in cast("dict[str, Any]", live_contracts).values()
        if isinstance(item, dict)
    }
    if (
        installed_stats_modules != contracted_stats_modules
        or installed_live_modules != contracted_live_modules
    ):
        raise NbaApiRequestSurfaceError(
            "runtime endpoint set differs from installed distribution sources"
        )
    stats = _stats_inventory(source_root, cast("dict[str, object]", stats_contracts))
    live = _live_inventory(source_root, cast("dict[str, object]", live_contracts))
    datasets, helpers = _static_inventory(
        source_root,
        cast("dict[str, object]", static_contracts),
        manifest.get("static_helpers"),
    )
    endpoints = sorted(
        (*stats, *live), key=lambda item: (item["source_family"], item["endpoint_id"])
    )
    source_keys = {
        (cast("str", item["source_family"]), cast("str", item["endpoint_id"])) for item in endpoints
    }
    if source_keys != set(endpoint_manifest):
        raise NbaApiRequestSurfaceError("request endpoint set differs from installed source")
    for item in endpoints:
        key = (cast("str", item["source_family"]), cast("str", item["endpoint_id"]))
        row = endpoint_manifest[key]
        if (
            row.get("module_name") != item["module_name"]
            or row.get("endpoint_slug") != item["endpoint_slug"]
            or row.get("request_method") != "GET"
            or row.get("parameter_count") != len(cast("list[object]", item["parameters"]))
        ):
            raise NbaApiRequestSurfaceError("request endpoint manifest differs from source")

    summary = expected_request.get("summary")
    if not isinstance(summary, dict):
        raise NbaApiRequestSurfaceError("request summary is malformed")
    parameter_count = sum(len(cast("list[object]", item["parameters"])) for item in endpoints)
    result_set_count = sum(len(cast("list[object]", item["result_sets"])) for item in endpoints)
    header_count = 0
    for item in endpoints:
        for result_set in cast("list[dict[str, Any]]", item["result_sets"]):
            headers = result_set.get("contract_headers", result_set.get("headers", ()))
            header_count += len(cast("list[object] | tuple[object, ...]", headers))
    extended_header_count = sum(
        len(cast("list[object]", result_set["headers"])) - cast("int", result_set["raw_item_count"])
        for endpoint in stats
        for result_set in cast("list[dict[str, object]]", endpoint["result_sets"])
    )
    source_atoms = _source_atoms(stats, live, datasets, helpers)
    primary_atoms = _primary_surface_atoms()
    if source_atoms != primary_atoms:
        raise NbaApiRequestSurfaceError(
            "primary request/runtime tuples differ from independent source atoms"
        )
    counts = {
        "stats_endpoint_count": len(stats),
        "live_endpoint_count": len(live),
        "parameter_occurrence_count": parameter_count,
        "static_dataset_count": len(datasets),
        "static_embedded_row_count": sum(cast("int", item["row_count"]) for item in datasets),
        "static_helper_count": len(helpers),
    }
    if any(summary.get(name) != value for name, value in counts.items()):
        raise NbaApiRequestSurfaceError("request summary contains fabricated counts")
    inventory_payload = {
        "provider_version": distribution.version,
        "distribution_source_inventory": list(source_inventory),
        "distribution_record_authority": record_authority,
        "runtime_payload_sha256": runtime["payload_sha256"],
        "request_surface_sha256": expected_request["surface_sha256"],
        "terminal_policy_authority": {
            "checked_payload_sha256": terminal_proof.checked_payload_sha256,
            "terminal_policy_sha256": terminal_proof.terminal_policy_sha256,
            "proof_sha256": terminal_proof.proof_sha256,
            "release_terminal_request_states": list(terminal_proof.release_terminal_request_states),
            "incomplete_request_states": list(terminal_proof.incomplete_request_states),
            "wire_request_states": list(terminal_proof.wire_request_states),
        },
        "competition_authority": {
            "checked_payload_sha256": competition_proof.checked_payload_sha256,
            "proof_sha256": competition_proof.proof_sha256,
        },
        "endpoints": endpoints,
        "static_datasets": datasets,
        "static_helpers": helpers,
        "source_atoms": list(source_atoms),
    }
    inventory = IndependentPackageInventory(
        stats_endpoint_count=len(stats),
        live_endpoint_count=len(live),
        parameter_occurrence_count=parameter_count,
        result_set_count=result_set_count,
        header_occurrence_count=header_count,
        static_dataset_count=len(datasets),
        static_embedded_row_count=counts["static_embedded_row_count"],
        static_helper_count=len(helpers),
        distribution_record_entry_count=cast("int", record_authority["entry_count"]),
        distribution_record_hashed_entry_count=cast("int", record_authority["hashed_entry_count"]),
        distribution_record_authority_sha256=cast("str", record_authority["authority_sha256"]),
        source_atom_count=len(source_atoms),
        source_atoms_sha256=_digest(list(source_atoms)),
        independently_derived_extended_header_count=extended_header_count,
        inventory_sha256=_digest(inventory_payload),
    )
    # The checked request resource is deliberately the sole candidate read and
    # the final input read, after every expected authority has been derived.
    request = _load_resource(_REQUEST_RESOURCE)
    _validate_request_terminal_binding(
        request,
        terminal_proof=terminal_proof,
        competition_payload_sha256=competition_proof.checked_payload_sha256,
    )
    if request.get("runtime_contract_payload_sha256") != runtime.get("payload_sha256"):
        raise NbaApiRequestSurfaceError("request and runtime authorities are unrelated")
    candidate_manifest = request.get("manifest")
    if not isinstance(candidate_manifest, dict) or request.get("manifest_sha256") != _digest(
        candidate_manifest
    ):
        raise NbaApiRequestSurfaceError("request manifest digest is fabricated")
    candidate_summary = request.get("summary")
    if not isinstance(candidate_summary, dict) or any(
        candidate_summary.get(name) != value for name, value in counts.items()
    ):
        raise NbaApiRequestSurfaceError("request summary contains fabricated counts")
    if request.get("surface_sha256") != rebuilt_authority.surface_sha256:
        raise NbaApiRequestSurfaceError(
            "checked request surface differs from rebuilt exact authority"
        )
    if request != expected_request:
        raise NbaApiRequestSurfaceError(
            "checked request surface differs from rebuilt exact authority"
        )
    return _VerifierAuthority(
        runtime,
        request,
        endpoint_manifest,
        source_atoms,
        inventory,
        terminal_proof,
    )


def build_independent_package_inventory() -> IndependentPackageInventory:
    """Return the cached no-network inventory of the exact installed package."""

    return _authority().inventory


def build_primary_surface_atoms() -> tuple[dict[str, object], ...]:
    """Return primary canonical atoms from nbadb's pinned contract builders."""

    return _primary_surface_atoms()


def build_independent_surface_atoms() -> tuple[dict[str, object], ...]:
    """Return exact source-derived atoms after primary reconciliation succeeds."""

    return _authority().source_atoms


def _canonical_scalar(value: object) -> object:
    if value is None or type(value) in {str, bool, int}:
        return value
    if type(value) is float and math.isfinite(cast("float", value)):
        return value
    raise NbaApiRequestSurfaceError("route value is not a finite JSON scalar")


def _canonical_tuple(values: object, *, field: str, allow_empty: bool) -> tuple[Any, ...]:
    if type(values) is not tuple:
        raise NbaApiRequestSurfaceError(f"{field} must be an exact tuple")
    canonical = cast("tuple[Any, ...]", values)
    keys = tuple(_canonical_bytes(item) for item in canonical)
    if (not allow_empty and not canonical) or keys != tuple(sorted(set(keys))):
        raise NbaApiRequestSurfaceError(f"{field} is not canonical, sorted, and unique")
    return canonical


def _endpoint_runtime(
    authority: _VerifierAuthority, family: str, endpoint_id: str
) -> dict[str, Any]:
    table_name = "contracts" if family == "stats" else "live_contracts"
    table = authority.runtime.get(table_name)
    row = table.get(endpoint_id) if isinstance(table, dict) else None
    if not isinstance(row, dict):
        raise NbaApiRequestSurfaceError("route references an unknown installed endpoint")
    return cast("dict[str, Any]", row)


def _parameter_contracts(runtime: Mapping[str, Any], family: str) -> list[dict[str, Any]]:
    if family == "live":
        raw = runtime.get("parameters", ())
        return [cast("dict[str, Any]", item) for item in raw if isinstance(item, dict)]
    names = runtime.get("parameters", ())
    defaults = {
        item.get("name"): item
        for item in runtime.get("parameter_defaults", ())
        if isinstance(item, dict) and isinstance(item.get("name"), str)
    }
    queries = {
        item.get("name"): item.get("query_name")
        for item in runtime.get("parameter_query_names", ())
        if isinstance(item, dict)
    }
    required = set(runtime.get("required_parameters", ()))
    nullable = set(runtime.get("nullable_parameters", ()))
    return [
        {
            "name": name,
            "query_name": queries.get(name),
            "location": "query",
            "required": name in required,
            "has_default": name in defaults,
            "default": (
                defaults[name].get("value")
                if name in defaults
                and defaults[name].get("default_authority") == "provider_literal_or_required_v1"
                else None
            ),
            "default_authority": (
                defaults[name].get("default_authority") if name in defaults else None
            ),
            "default_expression": (
                defaults[name].get("default_expression") if name in defaults else None
            ),
            "nullable": name in nullable,
            "pattern": None,
        }
        for name in names
    ]


def _parameter_dependencies(name: str) -> tuple[str, ...]:
    if name == "is_only_current_season":
        return ("explicit_scope_manifest",)
    if "event_id" in name:
        return ("game_event_index",)
    if "game_id" in name:
        return ("game_date_index",)
    if "player_id" in name or _PERSON_IDENTIFIER_RE.fullmatch(name):
        return ("season_player_universe",)
    if "team_id" in name:
        return ("season_team_universe",)
    if "series_id" in name:
        return ("playoff_series_universe",)
    if "group_id" in name:
        return ("lineup_group_universe",)
    if name == "game_date" or name.startswith("date_"):
        return ("game_date_index",)
    if "season_type" in name:
        return ("season_type_scope",)
    if name.startswith("season") or "_season" in name or name in {"draft_year", "rookie_year"}:
        return ("season_scope",)
    if "league_id" in name:
        return ("league_scope",)
    return ("explicit_scope_manifest",)


def _is_neutral_filter(name: str) -> bool:
    return _METRIC_FILTER_RE.match(name) is not None or (
        name.endswith("_nullable")
        and name not in _BOUNDED_NUMERIC_PARAMETERS
        and _parameter_dependencies(name) == ("explicit_scope_manifest",)
    )


def _materialize_route(
    authority: _VerifierAuthority,
    route: object,
) -> tuple[str, dict[str, object]]:
    family = getattr(route, "source_family", None)
    endpoint_id = getattr(route, "endpoint_id", None)
    if family not in {"stats", "live"} or not isinstance(endpoint_id, str):
        raise NbaApiRequestSurfaceError("route endpoint identity is invalid")
    endpoint_manifest = authority.endpoint_manifest.get((family, endpoint_id))
    if endpoint_manifest is None:
        raise NbaApiRequestSurfaceError("route endpoint is absent from installed authority")
    runtime = _endpoint_runtime(authority, family, endpoint_id)
    raw_parameters = getattr(route, "parameters", None)
    if type(raw_parameters) is not tuple:
        raise NbaApiRequestSurfaceError("route parameters must be an exact tuple")
    names: list[str] = []
    supplied: dict[str, object] = {}
    for item in raw_parameters:
        if type(item) is not tuple or len(item) != 2 or not isinstance(item[0], str):
            raise NbaApiRequestSurfaceError("route parameter entry is invalid")
        name, raw_value = item
        names.append(name)
        supplied[name] = _canonical_scalar(raw_value)
    if tuple(names) != tuple(sorted(set(names))):
        raise NbaApiRequestSurfaceError("route parameters are noncanonical or duplicated")
    parameters = _parameter_contracts(runtime, family)
    expected_names = {cast("str", item["name"]) for item in parameters}
    if set(supplied) - expected_names:
        raise NbaApiRequestSurfaceError("route supplies an unknown parameter")
    query_pairs: list[tuple[str, str]] = []
    path_values: dict[str, str] = {}
    materialized: dict[str, object] = {}
    for parameter in parameters:
        name = cast("str", parameter["name"])
        if name in supplied:
            value = supplied[name]
        elif parameter.get("default_authority") == "provider_dynamic_default_expression_v1":
            raise NbaApiRequestSurfaceError(
                "route omitted a dynamic provider default; explicit scope value is required"
            )
        elif parameter.get("has_default"):
            value = _canonical_scalar(parameter.get("default"))
        else:
            raise NbaApiRequestSurfaceError("route omits a required parameter")
        if value is None and not parameter.get("nullable"):
            raise NbaApiRequestSurfaceError("route serializes an unauthorized null")
        pattern = parameter.get("pattern")
        if pattern is not None and (
            not isinstance(value, str) or re.fullmatch(cast("str", pattern), value) is None
        ):
            raise NbaApiRequestSurfaceError("route value differs from its exact pattern")
        materialized[name] = value
        if parameter.get("location") == "path":
            if value is None:
                raise NbaApiRequestSurfaceError("path parameter cannot be null")
            path_values[name] = quote(str(value), safe="", encoding="utf-8")
        elif value is not None:
            query_name = parameter.get("query_name")
            if not isinstance(query_name, str):
                raise NbaApiRequestSurfaceError("query parameter lacks a wire name")
            query_pairs.append((query_name, str(value)))
    full_url = endpoint_manifest.get("url_template")
    if not isinstance(full_url, str) or not full_url.startswith("https://"):
        raise NbaApiRequestSurfaceError("endpoint URL authority is invalid")
    for name, value in sorted(path_values.items()):
        full_url = full_url.replace(f"{{{name}}}", value)
    if re.search(r"\{[A-Za-z_][A-Za-z0-9_]*\}", full_url):
        raise NbaApiRequestSurfaceError("route URL contains an unmaterialized token")
    query_string = urlencode(query_pairs, doseq=False)
    if query_string:
        full_url = f"{full_url}?{query_string}"
    path_start = full_url.find("/", len("https://"))
    if path_start < 0:
        raise NbaApiRequestSurfaceError("route URL has no absolute path")
    wire = {
        "request_surface_sha256": authority.request["surface_sha256"],
        "derivation_policy_sha256": authority.request["derivation_policy_sha256"],
        "runtime_contract_payload_sha256": authority.runtime["payload_sha256"],
        "source_family": family,
        "endpoint_id": endpoint_id,
        "request_method": "GET",
        "url_path": full_url[path_start:].split("?", 1)[0],
        "query_string": query_string,
    }
    return _digest(wire), materialized


def _route_payload(route: object) -> dict[str, object]:
    return {
        "route_id": getattr(route, "route_id", None),
        "source_family": getattr(route, "source_family", None),
        "endpoint_id": getattr(route, "endpoint_id", None),
        "parameters": [list(item) for item in getattr(route, "parameters", ())],
        "pagination_series_id": getattr(route, "pagination_series_id", None),
        "pagination_ordinal": getattr(route, "pagination_ordinal", None),
        "pagination_terminal": getattr(route, "pagination_terminal", None),
    }


def _scope_payload(scope: object) -> dict[str, object]:
    return {
        "request_surface_sha256": getattr(scope, "request_surface_sha256", None),
        "scope_id": getattr(scope, "scope_id", None),
        "seed_route_ids": list(getattr(scope, "seed_route_ids", ())),
        "dimensions": [
            {
                "dependency_id": getattr(item, "dependency_id", None),
                "source_kind": getattr(item, "source_kind", None),
                "source_authority_sha256": getattr(item, "source_authority_sha256", None),
                "values": list(getattr(item, "values", ())),
                "endpoint_id": getattr(item, "endpoint_id", None),
                "parameter_name": getattr(item, "parameter_name", None),
            }
            for item in getattr(scope, "dimensions", ())
        ],
    }


def _evidence_payload(item: object) -> dict[str, object]:
    return {
        "evidence_id": getattr(item, "evidence_id", None),
        "evidence_kind": getattr(item, "evidence_kind", None),
        "request_surface_sha256": getattr(item, "request_surface_sha256", None),
        "scope_sha256": getattr(item, "scope_sha256", None),
        "input_units": list(getattr(item, "input_units", ())),
        "discovered_units": list(getattr(item, "discovered_units", ())),
        "source_values": list(getattr(item, "source_values", ())),
        "complete": getattr(item, "complete", None),
        "pagination_ordinals": list(getattr(item, "pagination_ordinals", ())),
        "pagination_terminal_ordinal": getattr(item, "pagination_terminal_ordinal", None),
    }


def _request_binding_payload(value: object) -> dict[str, object]:
    route_ids = getattr(value, "route_ids", None)
    return {
        "request_surface_sha256": getattr(value, "request_surface_sha256", None),
        "runtime_contract_payload_sha256": getattr(value, "runtime_contract_payload_sha256", None),
        "provider_authority_sha256": getattr(value, "provider_authority_sha256", None),
        "route_manifest_sha256": getattr(value, "route_manifest_sha256", None),
        "scope_sha256": getattr(value, "scope_sha256", None),
        "provider_request_sha256": getattr(value, "provider_request_sha256", None),
        "source_request_sha256": getattr(value, "source_request_sha256", None),
        "competition_authority_sha256": getattr(value, "competition_authority_sha256", None),
        "competition_scope_sha256": getattr(value, "competition_scope_sha256", None),
        "competition_requirement_sha256": getattr(value, "competition_requirement_sha256", None),
        "role_binding_sha256": getattr(value, "role_binding_sha256", None),
        "source_evidence_sha256": getattr(value, "source_evidence_sha256", None),
        "source_family": getattr(value, "source_family", None),
        "endpoint_id": getattr(value, "endpoint_id", None),
        "route_ids": list(route_ids) if type(route_ids) is tuple else route_ids,
        "request_binding_sha256": getattr(value, "request_binding_sha256", None),
    }


def _support_authority_payload(value: object) -> dict[str, object]:
    return {
        "authority_kind": getattr(value, "authority_kind", None),
        "authority_version": getattr(value, "authority_version", None),
        "support_authority_sha256": getattr(value, "support_authority_sha256", None),
        "support_cell_id": getattr(value, "support_cell_id", None),
        "support_cell_sha256": getattr(value, "support_cell_sha256", None),
        "provider_authority_sha256": getattr(value, "provider_authority_sha256", None),
        "request_surface_sha256": getattr(value, "request_surface_sha256", None),
        "source_family": getattr(value, "source_family", None),
        "endpoint_id": getattr(value, "endpoint_id", None),
        "scope_sha256": getattr(value, "scope_sha256", None),
        "competition_scope_sha256": getattr(value, "competition_scope_sha256", None),
        "source_request_sha256": getattr(value, "source_request_sha256", None),
        "provider_request_sha256": getattr(value, "provider_request_sha256", None),
        "status": getattr(value, "status", None),
        "reason_code": getattr(value, "reason_code", None),
        "independent_verifier_id": getattr(value, "independent_verifier_id", None),
        "independent_verifier_sha256": getattr(value, "independent_verifier_sha256", None),
        "support_binding_sha256": getattr(value, "support_binding_sha256", None),
    }


def _typed_unavailable_payload(value: object) -> dict[str, object]:
    return {
        "request_binding": _request_binding_payload(getattr(value, "request_binding", None)),
        "support_authority": _support_authority_payload(getattr(value, "support_authority", None)),
        "state": getattr(value, "state", None),
        "unavailable_evidence_sha256": getattr(value, "unavailable_evidence_sha256", None),
    }


def _terminal_payload(
    *,
    binding: IndependentTerminalRequestBinding,
    state: str,
    kind: str,
    raw_values: tuple[tuple[str, object], ...],
    unavailable: IndependentTypedUpstreamUnavailableEvidence | None,
) -> dict[str, object]:
    return {
        "request_binding": _request_binding_payload(binding),
        "state": state,
        "evidence_kind": kind,
        "evidence_values": [list(value) for value in raw_values],
        "upstream_unavailable_evidence": (
            None if unavailable is None else _typed_unavailable_payload(unavailable)
        ),
    }


def _validate_terminal(
    item: object,
) -> tuple[
    str,
    IndependentTerminalRequestBinding,
    dict[str, object],
    dict[str, object],
]:
    try:
        binding = reproduce_terminal_request_binding(
            _request_binding_payload(getattr(item, "request_binding", None))
        )
    except NbaApiTerminalStateVerificationError as exc:
        raise NbaApiRequestSurfaceError(
            "terminal request binding is not independently reproducible"
        ) from exc
    request_key = binding.provider_request_sha256
    state = getattr(item, "state", None)
    kind = getattr(item, "evidence_kind", None)
    if (
        not isinstance(kind, str)
        or state not in _WIRE_REQUEST_STATES
        or kind != _TERMINAL_EVIDENCE_KINDS[state]
    ):
        raise NbaApiRequestSurfaceError("terminal state and typed evidence mismatch")
    raw_values = getattr(item, "evidence_values", None)
    if type(raw_values) is not tuple:
        raise NbaApiRequestSurfaceError("terminal evidence values are not an exact tuple")
    names: list[str] = []
    values: dict[str, object] = {}
    canonical_values: list[tuple[str, object]] = []
    for pair in raw_values:
        if type(pair) is not tuple or len(pair) != 2 or not isinstance(pair[0], str):
            raise NbaApiRequestSurfaceError("terminal evidence entry is malformed")
        name, raw_value = pair
        names.append(name)
        value = _canonical_scalar(raw_value)
        values[name] = value
        canonical_values.append((name, value))
    if tuple(names) != tuple(sorted(set(names))):
        raise NbaApiRequestSurfaceError("terminal evidence is noncanonical or duplicated")
    if set(values) - _PAGINATION_EVIDENCE_FIELDS != _TERMINAL_REQUIRED_FIELDS[state]:
        raise NbaApiRequestSurfaceError(
            "terminal evidence fields do not match the accounting-state contract"
        )

    unavailable: IndependentTypedUpstreamUnavailableEvidence | None = None
    raw_unavailable = getattr(item, "upstream_unavailable_evidence", None)
    if state == "upstream_unavailable":
        try:
            unavailable = reproduce_typed_upstream_unavailable_evidence(
                _typed_unavailable_payload(raw_unavailable)
            )
        except NbaApiTerminalStateVerificationError as exc:
            raise NbaApiRequestSurfaceError(
                "upstream unavailable state lacks complete typed evidence"
            ) from exc
        if unavailable.request_binding != binding or unavailable.state != state:
            raise NbaApiRequestSurfaceError(
                "upstream unavailable evidence rebinds its terminal request"
            )
    elif raw_unavailable is not None:
        raise NbaApiRequestSurfaceError(
            "typed upstream unavailable evidence belongs only to that state"
        )

    if state in {"success_nonempty", "success_empty"}:
        rows = values.get("row_count")
        occurrence = "present_nonempty" if state == "success_nonempty" else "present_empty"
        if (
            values.get("http_status") != 200
            or isinstance(rows, bool)
            or not isinstance(rows, int)
            or rows < 0
            or values.get("result_occurrence") != occurrence
            or (state == "success_nonempty" and rows == 0)
            or (state == "success_empty" and rows != 0)
        ):
            raise NbaApiRequestSurfaceError(
                "terminal provider-response evidence contradicts its state"
            )
        for field in (
            "decoded_results_receipt_sha256",
            "persistence_receipt_sha256",
            "response_body_sha256",
        ):
            _require_digest(values.get(field), f"terminal {field}")
    elif state == "contract_blocked":
        _require_digest(values.get("contract_evidence_sha256"), "contract evidence")
        reason = values.get("reason_code")
        if not isinstance(reason, str) or _SAFE_ID_RE.fullmatch(reason) is None:
            raise NbaApiRequestSurfaceError("contract evidence lacks a safe reason")
    elif state == "transient_failed":
        attempts = values.get("attempt_count")
        if isinstance(attempts, bool) or not isinstance(attempts, int) or attempts <= 0:
            raise NbaApiRequestSurfaceError("transient evidence has no positive attempt count")
    elif state == "response_contract_failed":
        _require_digest(values.get("response_body_sha256"), "contract failure body")
    elif state == "unclassified":
        _require_digest(values.get("classification_input_sha256"), "classification input")
    if state in {"transient_failed", "response_contract_failed"}:
        failure = values.get("failure_class")
        if not isinstance(failure, str) or _SAFE_ID_RE.fullmatch(failure) is None:
            raise NbaApiRequestSurfaceError("failure evidence lacks a safe class")
    if state == "unattempted":
        reason = values.get("reason_code")
        if not isinstance(reason, str) or _SAFE_ID_RE.fullmatch(reason) is None:
            raise NbaApiRequestSurfaceError("unattempted evidence lacks a safe reason")
    payload = _terminal_payload(
        binding=binding,
        state=state,
        kind=kind,
        raw_values=tuple(canonical_values),
        unavailable=unavailable,
    )
    return request_key, binding, payload, values


def verify_request_closure_independently(
    receipt: RequestClosureReceipt,
    *,
    verifier_id: str = _VERIFIER_ID,
) -> IndependentClosureProof:
    """Recompute a closure proof without calling the primary verifier path."""

    if type(receipt) is not RequestClosureReceipt:
        raise NbaApiRequestSurfaceError("independent verifier requires an exact closure receipt")
    if receipt.independent_proof is not None:
        raise NbaApiRequestSurfaceError("independent verifier refuses self-verified input")
    if (
        not isinstance(verifier_id, str)
        or _SAFE_ID_RE.fullmatch(verifier_id) is None
        or verifier_id in {_PRIMARY_VERIFIER_ID, "self", "self_verifier"}
    ):
        raise NbaApiRequestSurfaceError("independent verifier identity is invalid or self-owned")
    authority = _authority()
    surface_sha256 = _require_digest(
        authority.request.get("surface_sha256"), "pinned request surface"
    )
    manifest = receipt.route_manifest
    if (
        receipt.request_surface_sha256 != surface_sha256
        or receipt.scope.request_surface_sha256 != surface_sha256
        or manifest.request_surface_sha256 != surface_sha256
        or manifest.runtime_contract_payload_sha256 != authority.runtime.get("payload_sha256")
        or manifest.derivation_policy_sha256 != authority.request.get("derivation_policy_sha256")
    ):
        raise NbaApiRequestSurfaceError("closure references a foreign independent authority")

    routes = getattr(manifest, "routes", None)
    if type(routes) is not tuple or not routes:
        raise NbaApiRequestSurfaceError("route manifest must be a nonempty exact tuple")
    route_ids = tuple(getattr(route, "route_id", None) for route in routes)
    if any(not isinstance(route_id, str) for route_id in route_ids) or route_ids != tuple(
        sorted(set(route_ids))
    ):
        raise NbaApiRequestSurfaceError("route inventory is noncanonical or duplicated")
    route_payloads = [_route_payload(route) for route in routes]
    if manifest.registry_manifest_sha256 != _digest(route_payloads):
        raise NbaApiRequestSurfaceError("route manifest digest is fabricated")
    route_manifest_payload = {
        "request_surface_sha256": manifest.request_surface_sha256,
        "runtime_contract_payload_sha256": manifest.runtime_contract_payload_sha256,
        "derivation_policy_sha256": manifest.derivation_policy_sha256,
        "registry_manifest_sha256": manifest.registry_manifest_sha256,
        "routes": route_payloads,
    }
    route_manifest_sha256 = _digest(route_manifest_payload)

    expected_by_request: dict[str, list[str]] = defaultdict(list)
    materialized_by_route: dict[str, dict[str, object]] = {}
    pagination_series: dict[str, list[Any]] = defaultdict(list)
    for route in routes:
        if type(route.pagination_terminal) is not bool:
            raise NbaApiRequestSurfaceError("route pagination terminal flag is not boolean")
        if route.pagination_series_id is None and (
            route.pagination_ordinal is not None or route.pagination_terminal
        ):
            raise NbaApiRequestSurfaceError("non-pagination route has pagination metadata")
        route_id = cast("str", route.route_id)
        request_key, materialized = _materialize_route(authority, route)
        expected_by_request[request_key].append(route_id)
        materialized_by_route[route_id] = materialized
        endpoint = _endpoint_runtime(
            authority,
            cast("str", route.source_family),
            cast("str", route.endpoint_id),
        )
        cursor_names = {
            cast("str", item["name"])
            for item in _parameter_contracts(endpoint, cast("str", route.source_family))
            if item.get("name") == "counter"
        }
        series_id = getattr(route, "pagination_series_id", None)
        if bool(cursor_names) != (series_id is not None):
            raise NbaApiRequestSurfaceError("pagination metadata differs from source authority")
        if series_id is not None:
            if not isinstance(series_id, str) or _SAFE_ID_RE.fullmatch(series_id) is None:
                raise NbaApiRequestSurfaceError("pagination series identity is invalid")
            ordinal = getattr(route, "pagination_ordinal", None)
            value = materialized[next(iter(cursor_names))]
            if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
                raise NbaApiRequestSurfaceError("pagination ordinal is invalid")
            try:
                numeric_value = int(cast("str | int | float", value))
            except (TypeError, ValueError) as exc:
                raise NbaApiRequestSurfaceError("pagination cursor is not numeric") from exc
            if numeric_value != ordinal:
                raise NbaApiRequestSurfaceError("pagination cursor differs from its ordinal")
            pagination_series[series_id].append(route)
    for series_id, pages in pagination_series.items():
        del series_id
        ordinals = sorted(cast("int", page.pagination_ordinal) for page in pages)
        terminals = sorted(
            cast("int", page.pagination_ordinal)
            for page in pages
            if getattr(page, "pagination_terminal", None) is True
        )
        if ordinals != list(range(len(ordinals))) or terminals != [ordinals[-1]]:
            raise NbaApiRequestSurfaceError("pagination series is truncated or ambiguous")

    expected_bindings = tuple(
        (request_key, tuple(sorted(ids)))
        for request_key, ids in sorted(expected_by_request.items())
    )
    bindings = getattr(receipt, "bindings", None)
    if type(bindings) is not tuple:
        raise NbaApiRequestSurfaceError("route bindings must be an exact tuple")
    actual_bindings = tuple(
        (getattr(item, "provider_request_sha256", None), getattr(item, "route_ids", None))
        for item in bindings
    )
    if actual_bindings != expected_bindings:
        raise NbaApiRequestSurfaceError("route bindings differ from independent materialization")
    expected_units = tuple(request_key for request_key, _ in expected_bindings)

    scope = receipt.scope
    if not isinstance(scope.scope_id, str) or _SAFE_ID_RE.fullmatch(scope.scope_id) is None:
        raise NbaApiRequestSurfaceError("scope identity is invalid")
    scope_payload = _scope_payload(scope)
    scope_sha256 = _digest(scope_payload)
    if scope.scope_sha256 != scope_sha256:
        raise NbaApiRequestSurfaceError("scope digest is fabricated")
    seed_ids = _canonical_tuple(scope.seed_route_ids, field="scope seed routes", allow_empty=False)
    if not set(seed_ids) <= set(cast("tuple[str, ...]", route_ids)):
        raise NbaApiRequestSurfaceError("scope seed route is absent from route authority")
    dimensions = getattr(scope, "dimensions", None)
    if type(dimensions) is not tuple or not dimensions:
        raise NbaApiRequestSurfaceError("scope dimensions must be a nonempty exact tuple")
    dimension_digests: list[str] = []
    dimension_records: list[tuple[str, str | None, str | None, tuple[Any, ...]]] = []
    known_dependencies = set(authority.request.get("dependency_ids", ()))
    for item in dimensions:
        values = _canonical_tuple(
            getattr(item, "values", None), field="scope dimension values", allow_empty=False
        )
        dependency_id = getattr(item, "dependency_id", None)
        source_kind = getattr(item, "source_kind", None)
        endpoint_id = getattr(item, "endpoint_id", None)
        parameter_name = getattr(item, "parameter_name", None)
        if dependency_id not in known_dependencies:
            raise NbaApiRequestSurfaceError("scope dimension has an unknown dependency")
        if not isinstance(source_kind, str) or _SAFE_ID_RE.fullmatch(source_kind) is None:
            raise NbaApiRequestSurfaceError("scope dimension source kind is invalid")
        _require_digest(getattr(item, "source_authority_sha256", None), "scope dimension authority")
        if (endpoint_id is None) != (parameter_name is None) or any(
            not isinstance(value, str) or _SAFE_ID_RE.fullmatch(value) is None
            for value in (endpoint_id, parameter_name)
            if value is not None
        ):
            raise NbaApiRequestSurfaceError("scope dimension parameter authority is invalid")
        item_payload = {
            "dependency_id": dependency_id,
            "source_kind": source_kind,
            "source_authority_sha256": getattr(item, "source_authority_sha256", None),
            "values": list(getattr(item, "values", ())),
            "endpoint_id": endpoint_id,
            "parameter_name": parameter_name,
        }
        dimension_digest = _digest(item_payload)
        dimension_digests.append(dimension_digest)
        dimension_records.append((cast("str", dependency_id), endpoint_id, parameter_name, values))
    if tuple(dimension_digests) != tuple(sorted(set(dimension_digests))):
        raise NbaApiRequestSurfaceError("scope dimensions are noncanonical or duplicated")
    dependency_inventory = {record[0] for record in dimension_records}
    for route in routes:
        endpoint_id = cast("str", route.endpoint_id)
        runtime = _endpoint_runtime(authority, cast("str", route.source_family), endpoint_id)
        parameter_contracts = _parameter_contracts(runtime, cast("str", route.source_family))
        materialized = materialized_by_route[cast("str", route.route_id)]
        for parameter in parameter_contracts:
            name = cast("str", parameter["name"])
            dependencies = _parameter_dependencies(name)
            if not set(dependencies) <= dependency_inventory:
                raise NbaApiRequestSurfaceError("scope omits a parameter dependency")
            value = materialized[name]
            neutral = (
                bool(parameter.get("nullable"))
                and bool(parameter.get("has_default"))
                and value == parameter.get("default")
            )
            authorized = any(
                dependency in dependencies
                and (
                    dimension_endpoint is None
                    or (dimension_endpoint, dimension_parameter) == (endpoint_id, name)
                )
                and any(
                    _canonical_bytes(candidate) == _canonical_bytes(value) for candidate in values
                )
                for dependency, dimension_endpoint, dimension_parameter, values in dimension_records
            )
            if not neutral and not authorized:
                raise NbaApiRequestSurfaceError(
                    "route parameter is absent from its typed finite scope evidence"
                )
            if _is_neutral_filter(name) and not neutral:
                filter_authorized = any(
                    dependency == "explicit_scope_manifest"
                    and (dimension_endpoint, dimension_parameter) == (endpoint_id, name)
                    and any(
                        _canonical_bytes(candidate) == _canonical_bytes(value)
                        for candidate in values
                    )
                    for (
                        dependency,
                        dimension_endpoint,
                        dimension_parameter,
                        values,
                    ) in dimension_records
                )
                if not filter_authorized:
                    raise NbaApiRequestSurfaceError(
                        "non-neutral filter lacks parameter-specific scope evidence"
                    )

    iterations = getattr(receipt, "iterations", None)
    if type(iterations) is not tuple or len(iterations) < 2:
        raise NbaApiRequestSurfaceError("closure lacks a contiguous fixed-point chain")
    previous_output: tuple[str, ...] = ()
    for index, iteration in enumerate(iterations):
        if getattr(iteration, "iteration", None) != index:
            raise NbaApiRequestSurfaceError("closure iteration ordinals are discontinuous")
        if (
            getattr(iteration, "request_surface_sha256", None) != surface_sha256
            or getattr(iteration, "scope_sha256", None) != scope_sha256
        ):
            raise NbaApiRequestSurfaceError("closure iteration references a foreign authority")
        input_units = cast(
            "tuple[str, ...]",
            _canonical_tuple(
                getattr(iteration, "input_units", None),
                field="iteration input units",
                allow_empty=True,
            ),
        )
        new_units = cast(
            "tuple[str, ...]",
            _canonical_tuple(
                getattr(iteration, "new_units", None),
                field="iteration new units",
                allow_empty=True,
            ),
        )
        output_units = cast(
            "tuple[str, ...]",
            _canonical_tuple(
                getattr(iteration, "output_units", None),
                field="iteration output units",
                allow_empty=False,
            ),
        )
        if input_units != previous_output or set(input_units) & set(new_units):
            raise NbaApiRequestSurfaceError("closure chain replaces or repeats prior units")
        if output_units != tuple(sorted((*input_units, *new_units))):
            raise NbaApiRequestSurfaceError("closure output is not the exact set union")
        raw_evidence = getattr(iteration, "evidence", None)
        if type(raw_evidence) is not tuple or not raw_evidence:
            raise NbaApiRequestSurfaceError("closure iteration lacks exact evidence")
        evidence_digests = tuple(_digest(_evidence_payload(item)) for item in raw_evidence)
        if evidence_digests != tuple(sorted(set(evidence_digests))):
            raise NbaApiRequestSurfaceError("iteration evidence is noncanonical or duplicated")
        discoveries: list[str] = []
        fixed = False
        for item in raw_evidence:
            if (
                getattr(item, "request_surface_sha256", None) != surface_sha256
                or getattr(item, "scope_sha256", None) != scope_sha256
                or getattr(item, "input_units", None) != input_units
                or getattr(item, "complete", None) is not True
            ):
                raise NbaApiRequestSurfaceError("iteration evidence is incomplete or unrelated")
            discovered = cast("tuple[str, ...]", getattr(item, "discovered_units", ()))
            discoveries.extend(discovered)
            fixed = fixed or (
                getattr(item, "evidence_kind", None) == "fixed_point" and not discovered
            )
        if len(discoveries) != len(set(discoveries)) or set(discoveries) != set(new_units):
            raise NbaApiRequestSurfaceError("iteration evidence does not explain its exact delta")
        if not new_units and not fixed:
            raise NbaApiRequestSurfaceError("zero-growth iteration lacks fixed-point evidence")
        previous_output = output_units
    if previous_output != expected_units or getattr(iterations[-1], "new_units", None):
        raise NbaApiRequestSurfaceError("closure fixed point differs from route unit inventory")
    seed_units = tuple(
        sorted(
            request_key
            for request_key, ids in expected_bindings
            if set(ids) & set(cast("tuple[str, ...]", seed_ids))
        )
    )
    observed_seed_units = tuple(
        sorted(
            unit
            for item in iterations[0].evidence
            if getattr(item, "evidence_kind", None) == "seed"
            for unit in getattr(item, "discovered_units", ())
        )
    )
    if observed_seed_units != seed_units:
        raise NbaApiRequestSurfaceError("seed evidence differs from scope seed routes")

    terminal = getattr(receipt, "terminal_evidence", None)
    if type(terminal) is not tuple:
        raise NbaApiRequestSurfaceError("terminal evidence must be an exact tuple")
    validated_terminal = tuple(_validate_terminal(item) for item in terminal)
    terminal_units = tuple(item[0] for item in validated_terminal)
    if terminal_units != expected_units:
        raise NbaApiRequestSurfaceError("terminal evidence does not exactly conserve request units")
    route_binding_by_request = dict(expected_bindings)
    route_by_id = {cast("str", route.route_id): route for route in routes}
    for request_key, binding, _, _ in validated_terminal:
        if (
            binding.request_surface_sha256 != surface_sha256
            or binding.runtime_contract_payload_sha256 != authority.runtime.get("payload_sha256")
            or binding.route_manifest_sha256 != route_manifest_sha256
            or binding.scope_sha256 != scope_sha256
            or binding.provider_request_sha256 != request_key
            or binding.route_ids != route_binding_by_request[request_key]
        ):
            raise NbaApiRequestSurfaceError(
                "terminal request binding rebinds its closure authority or route unit"
            )
        endpoint_keys = {
            (
                getattr(route_by_id[route_id], "source_family", None),
                getattr(route_by_id[route_id], "endpoint_id", None),
            )
            for route_id in binding.route_ids
        }
        if endpoint_keys != {(binding.source_family, binding.endpoint_id)}:
            raise NbaApiRequestSurfaceError("terminal request binding rebinds its endpoint aliases")
    terminal_payload = [
        {
            "provider_request_sha256": request_key,
            "state": cast("str", payload["state"]),
            "evidence_sha256": _digest(payload),
        }
        for request_key, _, payload, _ in validated_terminal
    ]
    terminal_inventory_sha256 = _digest(terminal_payload)
    # Recompute the typed unavailable and blocked subsets even though the compact
    # v1 proof also binds them transitively through terminal_inventory_sha256.
    _digest(
        [
            _digest(payload)
            for _, _, payload, _ in validated_terminal
            if payload["state"] == "upstream_unavailable"
        ]
    )
    _digest(
        [
            _digest(payload)
            for _, _, payload, _ in validated_terminal
            if payload["state"] == "contract_blocked"
        ]
    )
    route_to_request = {
        route_id: request_key for request_key, ids in expected_bindings for route_id in ids
    }
    values_by_request = {request_key: values for request_key, _, _, values in validated_terminal}
    for route in routes:
        values = values_by_request[route_to_request[cast("str", route.route_id)]]
        if getattr(route, "pagination_series_id", None) is None:
            if set(values) & _PAGINATION_EVIDENCE_FIELDS:
                raise NbaApiRequestSurfaceError(
                    "non-pagination terminal evidence declares page metadata"
                )
            continue
        if (
            values.get("pagination_ordinal") != route.pagination_ordinal
            or values.get("pagination_terminal") is not route.pagination_terminal
        ):
            raise NbaApiRequestSurfaceError("pagination terminal evidence differs from route")
        reason = values.get("pagination_termination_reason")
        if route.pagination_terminal and reason not in {
            "declared_total",
            "empty_page",
            "short_page",
        }:
            raise NbaApiRequestSurfaceError("terminal pagination page lacks a stop reason")
        if not route.pagination_terminal and reason is not None:
            raise NbaApiRequestSurfaceError("nonterminal pagination page has a stop reason")

    return IndependentClosureProof(
        verifier_id=verifier_id,
        request_surface_sha256=surface_sha256,
        scope_sha256=scope_sha256,
        route_manifest_sha256=route_manifest_sha256,
        unit_inventory_sha256=_digest(list(expected_units)),
        terminal_inventory_sha256=terminal_inventory_sha256,
    )
