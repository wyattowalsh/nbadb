"""Independent source-AST verifier for competition occurrence closure.

This module intentionally does not import the primary occurrence authority,
the runtime endpoint registry, or ``EndpointCoverageGenerator``.  It parses
the pinned distribution and repository source trees independently and then
requires byte-for-byte semantic equality with the checked resource.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.metadata
import json
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

from nbadb.core.nba_api_surface_inventory import (
    NbaApiSurfaceInventoryError,
    build_distribution_record_authority,
)

if TYPE_CHECKING:
    from importlib.metadata import Distribution

_DISTRIBUTION: Final = "nba-api"
_VERSION: Final = "1.11.4"
_RESOURCE: Final = "nba_api_competition_occurrences_v1_11_4.json"
_REQUEST_RESOURCE: Final = "nba_api_request_surface_v1_11_4.json"
_VERIFIER_ID: Final = "nbadb_independent_competition_occurrence_source_ast_v1"
_COMPETITION_NAMES: Final = frozenset(
    {
        "league_id",
        "league_id_nullable",
        "person1_league_id",
        "person2_league_id",
    }
)
_TRANSPORT_NAMES: Final = frozenset({"get_request", "headers", "proxy", "timeout"})
_DEFAULT_EXPRESSIONS: Final = {
    "league_id": "LeagueID.default",
    "league_id_nullable": "LeagueIDNullable.default",
    "person1_league_id": "LeagueID.default",
    "person2_league_id": "LeagueID.default",
}
_WIRE_NAMES: Final = {
    "league_id": "LeagueID",
    "league_id_nullable": "LeagueID",
    "person1_league_id": "Person1LeagueId",
    "person2_league_id": "Person2LeagueId",
}
_PLANNING_FIELDS: Final = (
    "occurrence_id",
    "endpoint_id",
    "ordinal",
    "name",
    "query_name",
    "nullable",
    "has_default",
    "default",
    "default_authority",
    "semantic_role",
    "source_signature_sha256",
    "typed_domain_sha256",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class NbaApiCompetitionOccurrenceVerificationError(ValueError):
    """Independent competition occurrence verification failed closed."""


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
        raise NbaApiCompetitionOccurrenceVerificationError(
            "competition occurrence proof is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _planning_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value) + b"\n").hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionOccurrenceVerificationError(f"{field} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionOccurrenceVerificationError(
                f"competition occurrence resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionOccurrenceVerificationError(
        f"competition occurrence resource contains non-finite JSON constant: {value}"
    )


def _load_json_bytes(raw: bytes, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionOccurrenceVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(f"{label} cannot be decoded") from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value) + b"\n":
        raise NbaApiCompetitionOccurrenceVerificationError(f"{label} bytes are not canonical JSON")
    body = dict(value)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, f"{label} payload_sha256") != _digest(body):
        raise NbaApiCompetitionOccurrenceVerificationError(f"{label} payload digest is invalid")
    return cast("dict[str, object]", value)


def _load_resource(resource: str) -> tuple[bytes, dict[str, object]]:
    try:
        raw = resources.files("nbadb.contracts").joinpath(resource).read_bytes()
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(
            f"required checked resource cannot be read: {resource}"
        ) from exc
    return raw, _load_json_bytes(raw, label=resource)


def _load_checked_resource(path: Path | None) -> dict[str, object]:
    try:
        raw = (
            resources.files("nbadb.contracts").joinpath(_RESOURCE).read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "competition occurrence resource cannot be read"
        ) from exc
    return _load_json_bytes(raw, label="competition occurrence resource")


def _request_surface_rows() -> tuple[
    bytes,
    dict[str, object],
    tuple[dict[str, object], ...],
]:
    raw, payload = _load_resource(_REQUEST_RESOURCE)
    rows = payload.get("parameter_occurrences")
    if not isinstance(rows, list):
        raise NbaApiCompetitionOccurrenceVerificationError(
            "request surface omits its occurrence inventory"
        )
    projected: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict) or row.get("domain_kind") != "league_scope":
            continue
        typed_row = cast("dict[str, object]", row)
        if set(_PLANNING_FIELDS) - set(typed_row):
            raise NbaApiCompetitionOccurrenceVerificationError(
                "request-surface league occurrence is incomplete"
            )
        projected.append({field: typed_row[field] for field in _PLANNING_FIELDS})
    ids = tuple(str(row["occurrence_id"]) for row in projected)
    if not projected or ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
        raise NbaApiCompetitionOccurrenceVerificationError(
            "request-surface league occurrences are not sorted and unique"
        )
    return raw, payload, tuple(projected)


def _distribution_and_sources() -> tuple[
    Distribution,
    str,
    dict[str, tuple[bytes, str, int]],
]:
    try:
        distribution = importlib.metadata.distribution(_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "pinned nba_api distribution is not installed"
        ) from exc
    if distribution.version != _VERSION:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "installed nba_api version differs from the exact pin"
        )
    try:
        record = build_distribution_record_authority(distribution)
    except NbaApiSurfaceInventoryError as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "installed nba_api RECORD authority is invalid"
        ) from exc
    sources: dict[str, tuple[bytes, str, int]] = {}
    for entry in record.entries:
        if not (
            entry.path.startswith("nba_api/stats/endpoints/")
            and entry.path.endswith(".py")
            and not entry.path.endswith("/__init__.py")
            and not entry.path.endswith("/_base.py")
        ):
            continue
        try:
            raw = Path(str(distribution.locate_file(entry.path))).read_bytes()
        except OSError as exc:
            raise NbaApiCompetitionOccurrenceVerificationError(
                "nba_api endpoint source cannot be read"
            ) from exc
        if hashlib.sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.size:
            raise NbaApiCompetitionOccurrenceVerificationError(
                "nba_api endpoint source differs from its RECORD binding"
            )
        sources[entry.path] = (raw, entry.sha256, entry.size)
    if not sources:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "nba_api endpoint source inventory is empty"
        )
    return distribution, record.authority_sha256, sources


def _function_arguments(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
) -> tuple[tuple[str, ast.expr | None], ...]:
    positional = [*node.args.posonlyargs, *node.args.args]
    defaults: list[ast.expr | None] = [None] * (len(positional) - len(node.args.defaults)) + list(
        node.args.defaults
    )
    rows = [
        (argument.arg, default)
        for argument, default in zip(positional, defaults, strict=True)
        if argument.arg != "self"
    ]
    rows.extend(
        (argument.arg, default)
        for argument, default in zip(
            node.args.kwonlyargs,
            node.args.kw_defaults,
            strict=True,
        )
    )
    return tuple(rows)


def _wire_mapping(
    init: ast.FunctionDef | ast.AsyncFunctionDef,
) -> dict[str, str]:
    assignments: list[ast.Dict] = []
    for node in ast.walk(init):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        if any(
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "self"
            and target.attr == "parameters"
            for target in node.targets
        ):
            assignments.append(node.value)
    if len(assignments) != 1:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "endpoint source has ambiguous self.parameters assignment"
        )
    result: dict[str, str] = {}
    mapping = assignments[0]
    for key, value in zip(mapping.keys, mapping.values, strict=True):
        if (
            isinstance(key, ast.Constant)
            and isinstance(key.value, str)
            and isinstance(value, ast.Name)
            and value.id in _COMPETITION_NAMES
        ):
            if value.id in result:
                raise NbaApiCompetitionOccurrenceVerificationError(
                    "endpoint source has duplicate competition wire mapping"
                )
            result[value.id] = key.value
    return result


def _derive_package_rows(
    sources: dict[str, tuple[bytes, str, int]],
    planning_rows: tuple[dict[str, object], ...],
) -> tuple[dict[str, object], ...]:
    planning = {(str(row["endpoint_id"]), str(row["name"])): row for row in planning_rows}
    rows: list[dict[str, object]] = []
    for source_path, (raw, source_sha256, source_size) in sorted(sources.items()):
        try:
            tree = ast.parse(
                raw.decode("utf-8", errors="strict"),
                filename=source_path,
            )
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise NbaApiCompetitionOccurrenceVerificationError(
                "nba_api endpoint source is not valid UTF-8 Python"
            ) from exc
        provider_module = source_path.removesuffix(".py").replace("/", ".")
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            init_nodes = [
                node
                for node in class_node.body
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == "__init__"
            ]
            if not init_nodes:
                continue
            if len(init_nodes) != 1:
                raise NbaApiCompetitionOccurrenceVerificationError(
                    "nba_api endpoint source has ambiguous constructor"
                )
            init = init_nodes[0]
            arguments = tuple(
                (name, default)
                for name, default in _function_arguments(init)
                if name not in _TRANSPORT_NAMES
            )
            competition_arguments = tuple(
                (name, default) for name, default in arguments if name in _COMPETITION_NAMES
            )
            if not competition_arguments:
                continue
            wires = _wire_mapping(init)
            for ordinal, (name, default_node) in enumerate(arguments):
                if name not in _COMPETITION_NAMES:
                    continue
                if default_node is None:
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "competition constructor occurrence lacks a default"
                    )
                default_expression = ast.unparse(default_node)
                if default_expression != _DEFAULT_EXPRESSIONS[name]:
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "competition constructor default expression is invalid"
                    )
                wire_name = wires.get(name)
                if wire_name != _WIRE_NAMES[name]:
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "competition constructor wire name is invalid"
                    )
                planning_row = planning.get((class_node.name, name))
                if planning_row is None:
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "source-AST package occurrence is absent from request-surface authority"
                    )
                expected = {
                    "has_default": True,
                    "name": name,
                    "nullable": name == "league_id_nullable",
                    "occurrence_id": (f"parameter:stats:{class_node.name}:{ordinal:04d}:{name}"),
                    "ordinal": ordinal,
                    "query_name": wire_name,
                    "semantic_role": "scope_axis",
                }
                if any(planning_row.get(key) != value for key, value in expected.items()):
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "source-AST package occurrence differs from request-surface authority"
                    )
                default_value = planning_row.get("default")
                if not isinstance(default_value, str):
                    raise NbaApiCompetitionOccurrenceVerificationError(
                        "request-surface competition default is not a string"
                    )
                rows.append(
                    {
                        "constructor_name": name,
                        "default": default_value,
                        "default_expression": default_expression,
                        "has_default": True,
                        "nullable": name == "league_id_nullable",
                        "occurrence_id": str(planning_row["occurrence_id"]),
                        "ordinal": ordinal,
                        "provider_endpoint_id": class_node.name,
                        "provider_module": provider_module,
                        "provider_source_path": source_path,
                        "provider_source_sha256": source_sha256,
                        "provider_source_size": source_size,
                        "request_surface_source_signature_sha256": str(
                            planning_row["source_signature_sha256"]
                        ),
                        "request_surface_typed_domain_sha256": str(
                            planning_row["typed_domain_sha256"]
                        ),
                        "semantic_role": "scope_axis",
                        "wire_name": wire_name,
                    }
                )
    result = tuple(sorted(rows, key=lambda item: str(item["occurrence_id"])))
    observed = {(str(row["provider_endpoint_id"]), str(row["constructor_name"])) for row in result}
    if observed != set(planning):
        raise NbaApiCompetitionOccurrenceVerificationError(
            "request-surface authority contains an unobserved source-AST occurrence"
        )
    return result


def _provider_imports(tree: ast.Module) -> dict[str, str]:
    imports: dict[str, str] = {}
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom) or not (node.module or "").startswith(
            "nba_api.stats.endpoints"
        ):
            continue
        for alias in node.names:
            if alias.name == "*":
                raise NbaApiCompetitionOccurrenceVerificationError(
                    "extractor source uses an ambiguous provider star import"
                )
            local_name = alias.asname or alias.name
            if local_name in imports and imports[local_name] != alias.name:
                raise NbaApiCompetitionOccurrenceVerificationError(
                    "extractor provider import alias is ambiguous"
                )
            imports[local_name] = alias.name
    return imports


def _registered_class(node: ast.ClassDef) -> bool:
    return any(
        isinstance(decorator, ast.Attribute)
        and isinstance(decorator.value, ast.Name)
        and decorator.value.id == "registry"
        and decorator.attr == "register"
        for decorator in node.decorator_list
    )


def _endpoint_name(node: ast.ClassDef) -> str | None:
    values: list[str] = []
    for statement in node.body:
        value: ast.expr | None = None
        if (
            isinstance(statement, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "endpoint_name"
                for target in statement.targets
            )
        ) or (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "endpoint_name"
        ):
            value = statement.value
        if isinstance(value, ast.Constant) and isinstance(value.value, str):
            values.append(value.value)
    if not values:
        return None
    if len(values) != 1:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "registered extractor endpoint_name is ambiguous"
        )
    return values[0]


def _forwarding_behavior(name: str) -> str:
    if name in {"league_id", "league_id_nullable"}:
        return "semantic_primary_league_alias_forwarding"
    if name in {"person1_league_id", "person2_league_id"}:
        return "exact_constructor_name_forwarding"
    raise NbaApiCompetitionOccurrenceVerificationError("unknown competition constructor role")


def _output_behavior(name: str) -> str:
    if name in {"league_id", "league_id_nullable"}:
        return "inject_primary_league_id_when_provider_rows_omit_it"
    if name in {"person1_league_id", "person2_league_id"}:
        return "participant_role_only_no_primary_league_id_injection"
    raise NbaApiCompetitionOccurrenceVerificationError("unknown competition constructor role")


def _derive_repo_rows(
    package_rows: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    by_endpoint: dict[str, tuple[dict[str, object], ...]] = {}
    for row in package_rows:
        endpoint_id = str(row["provider_endpoint_id"])
        by_endpoint.setdefault(endpoint_id, ())
        by_endpoint[endpoint_id] = (*by_endpoint[endpoint_id], row)
    aliases: list[dict[str, object]] = []
    sources: dict[str, dict[str, object]] = {}
    seen_endpoint_names: set[str] = set()
    try:
        stats_dir = resources.files("nbadb").joinpath("extract", "stats")
        source_members = sorted(
            (
                member
                for member in stats_dir.iterdir()
                if member.is_file() and member.name.endswith(".py") and member.name != "__init__.py"
            ),
            key=lambda member: member.name,
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionOccurrenceVerificationError(
            "extractor package source inventory cannot be enumerated"
        ) from exc
    for member in source_members:
        try:
            raw = member.read_bytes()
        except (AttributeError, OSError) as exc:
            raise NbaApiCompetitionOccurrenceVerificationError(
                "extractor package source cannot be read"
            ) from exc
        relative_path = f"src/nbadb/extract/stats/{member.name}"
        if member.name == "__init__.py":
            continue
        try:
            tree = ast.parse(raw.decode("utf-8", errors="strict"), filename=relative_path)
        except (UnicodeDecodeError, SyntaxError) as exc:
            raise NbaApiCompetitionOccurrenceVerificationError(
                "extractor source is not valid UTF-8 Python"
            ) from exc
        imports = _provider_imports(tree)
        source_sha256 = hashlib.sha256(raw).hexdigest()
        aliases_in_source: list[str] = []
        for class_node in (node for node in tree.body if isinstance(node, ast.ClassDef)):
            endpoint_name = _endpoint_name(class_node)
            if endpoint_name is None or not _registered_class(class_node):
                continue
            if endpoint_name in seen_endpoint_names:
                raise NbaApiCompetitionOccurrenceVerificationError(
                    "registered extractor endpoint name is duplicated"
                )
            seen_endpoint_names.add(endpoint_name)
            referenced = tuple(
                sorted(
                    {
                        imports[node.id]
                        for node in ast.walk(class_node)
                        if isinstance(node, ast.Name)
                        and node.id in imports
                        and imports[node.id] in by_endpoint
                    }
                )
            )
            if not referenced:
                continue
            occurrences = tuple(
                sorted(
                    (
                        occurrence
                        for provider_endpoint_id in referenced
                        for occurrence in by_endpoint[provider_endpoint_id]
                    ),
                    key=lambda item: str(item["occurrence_id"]),
                )
            )
            roles = tuple(
                sorted(
                    (
                        {
                            "constructor_name": str(occurrence["constructor_name"]),
                            "default": occurrence["default"],
                            "forwarding_behavior": _forwarding_behavior(
                                str(occurrence["constructor_name"])
                            ),
                            "has_default": occurrence["has_default"],
                            "nullable": occurrence["nullable"],
                            "output_behavior": _output_behavior(
                                str(occurrence["constructor_name"])
                            ),
                            "provider_endpoint_id": str(occurrence["provider_endpoint_id"]),
                            "provider_occurrence_id": str(occurrence["occurrence_id"]),
                            "semantic_role": occurrence["semantic_role"],
                            "wire_name": str(occurrence["wire_name"]),
                        }
                        for occurrence in occurrences
                    ),
                    key=lambda item: (
                        str(item["constructor_name"]),
                        str(item["wire_name"]),
                    ),
                )
            )
            aliases.append(
                {
                    "extractor_module": (
                        relative_path.removeprefix("src/").removesuffix(".py").replace("/", ".")
                    ),
                    "extractor_qualname": class_node.name,
                    "parameter_roles": list(roles),
                    "provider_endpoint_ids": list(referenced),
                    "provider_occurrence_ids": sorted(
                        str(item["occurrence_id"]) for item in occurrences
                    ),
                    "repo_endpoint_name": endpoint_name,
                    "source_path": relative_path,
                    "source_sha256": source_sha256,
                    "source_size": len(raw),
                }
            )
            aliases_in_source.append(endpoint_name)
        if aliases_in_source:
            sources[relative_path] = {
                "path": relative_path,
                "sha256": source_sha256,
                "size": len(raw),
            }
    return (
        tuple(sorted(aliases, key=lambda item: str(item["repo_endpoint_name"]))),
        tuple(sources[path] for path in sorted(sources)),
    )


def _planning_repo_rows(
    repo_rows: tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    return [
        {
            "parameter_roles": [
                {
                    "default": role["default"],
                    "has_default": role["has_default"],
                    "name": role["constructor_name"],
                    "nullable": role["nullable"],
                    "query_name": role["wire_name"],
                    "semantic_role": role["semantic_role"],
                }
                for role in cast("list[dict[str, object]]", row["parameter_roles"])
            ],
            "provider_endpoint_ids": row["provider_endpoint_ids"],
            "provider_occurrence_ids": row["provider_occurrence_ids"],
            "repo_endpoint_name": row["repo_endpoint_name"],
        }
        for row in repo_rows
    ]


def _source_inventory_planning_rows(
    repo_rows: tuple[dict[str, object], ...],
    source_rows: tuple[dict[str, object], ...],
) -> list[dict[str, object]]:
    aliases_by_path: dict[str, list[str]] = {}
    for row in repo_rows:
        aliases_by_path.setdefault(str(row["source_path"]), []).append(
            str(row["repo_endpoint_name"])
        )
    return [
        {
            "alias_count": len(aliases_by_path[str(source["path"])]),
            "aliases": sorted(aliases_by_path[str(source["path"])]),
            "path": source["path"],
            "sha256": source["sha256"],
        }
        for source in source_rows
    ]


def _independent_authority_body() -> tuple[dict[str, object], tuple[int, int, int]]:
    _, record_sha256, sources = _distribution_and_sources()
    request_raw, request_payload, planning_rows = _request_surface_rows()
    package_rows = _derive_package_rows(sources, planning_rows)
    repo_rows, source_rows = _derive_repo_rows(package_rows)
    constructor_counts = dict(
        sorted(Counter(str(row["constructor_name"]) for row in package_rows).items())
    )
    wire_counts = dict(sorted(Counter(str(row["wire_name"]) for row in package_rows).items()))
    role_counts = dict(
        sorted(
            Counter(
                str(role["constructor_name"])
                for row in repo_rows
                for role in cast("list[dict[str, object]]", row["parameter_roles"])
            ).items()
        )
    )
    projected_role_count = sum(
        len(cast("list[dict[str, object]]", row["parameter_roles"])) for row in repo_rows
    )
    body: dict[str, object] = {
        "behavior_taxonomy": {
            "participant_competition_role": {
                "constructor_names": ["person1_league_id", "person2_league_id"],
                "forwarding_behavior": "exact_constructor_name_forwarding",
                "output_behavior": ("participant_role_only_no_primary_league_id_injection"),
            },
            "primary_competition_scope": {
                "constructor_names": ["league_id", "league_id_nullable"],
                "forwarding_behavior": "semantic_primary_league_alias_forwarding",
                "output_behavior": ("inject_primary_league_id_when_provider_rows_omit_it"),
            },
        },
        "kind": "nbadb_nba_api_competition_occurrence_authority",
        "package_constructor_name_counts": constructor_counts,
        "package_endpoint_count": len({str(row["provider_endpoint_id"]) for row in package_rows}),
        "package_occurrence_count": len(package_rows),
        "package_occurrence_planning_census_sha256": _planning_digest(list(planning_rows)),
        "package_occurrences": list(package_rows),
        "package_occurrences_sha256": _digest(list(package_rows)),
        "package_wire_name_counts": wire_counts,
        "projected_role_count": projected_role_count,
        "projected_role_name_counts": role_counts,
        "provider": {
            "distribution_name": _DISTRIBUTION,
            "distribution_record_authority_sha256": record_sha256,
            "distribution_version": _VERSION,
        },
        "repo_alias_count": len(repo_rows),
        "repo_alias_planning_census_sha256": _planning_digest(_planning_repo_rows(repo_rows)),
        "repo_aliases": list(repo_rows),
        "repo_aliases_sha256": _digest(list(repo_rows)),
        "repo_source_bindings_sha256": _digest(list(source_rows)),
        "repo_source_file_count": len(source_rows),
        "repo_source_inventory": list(source_rows),
        "repo_source_inventory_sha256": _planning_digest(
            _source_inventory_planning_rows(repo_rows, source_rows)
        ),
        "schema_version": 1,
        "upstream_request_surface": {
            "payload_sha256": request_payload["payload_sha256"],
            "resource": _REQUEST_RESOURCE,
            "resource_sha256": hashlib.sha256(request_raw).hexdigest(),
            "surface_sha256": request_payload["surface_sha256"],
        },
    }
    return body, (len(package_rows), len(repo_rows), projected_role_count)


@dataclass(frozen=True, slots=True)
class IndependentCompetitionOccurrenceProof:
    """Independent equality receipt for package occurrences and repo aliases."""

    verifier_id: str
    authority_sha256: str
    checked_payload_sha256: str
    package_occurrences_sha256: str
    repo_aliases_sha256: str
    package_planning_census_sha256: str
    repo_alias_planning_census_sha256: str
    repo_source_inventory_sha256: str
    package_occurrence_count: int
    repo_alias_count: int
    projected_role_count: int
    proof_sha256: str


def _verify(path: Path | None) -> IndependentCompetitionOccurrenceProof:
    expected_body, counts = _independent_authority_body()
    payload = _load_checked_resource(path)
    observed_body = {
        key: value
        for key, value in payload.items()
        if key not in {"authority_sha256", "independent_proof", "payload_sha256"}
    }
    expected_authority_sha256 = _digest(expected_body)
    expected_independent_proof = {
        "claim_status": "not_supplied_by_this_artifact",
        "kind": "independent_competition_occurrence_source_ast_receipt",
        "required": True,
        "schema_version": 1,
    }
    if (
        observed_body != expected_body
        or payload.get("authority_sha256") != expected_authority_sha256
        or payload.get("independent_proof") != expected_independent_proof
    ):
        raise NbaApiCompetitionOccurrenceVerificationError(
            "checked competition occurrence authority differs from independent source AST"
        )
    checked_payload_sha256 = _require_digest(
        payload.get("payload_sha256"),
        "checked payload_sha256",
    )
    package_occurrences_sha256 = _require_digest(
        expected_body["package_occurrences_sha256"],
        "package_occurrences_sha256",
    )
    repo_aliases_sha256 = _require_digest(
        expected_body["repo_aliases_sha256"],
        "repo_aliases_sha256",
    )
    proof_body = {
        "authority_sha256": expected_authority_sha256,
        "checked_payload_sha256": checked_payload_sha256,
        "kind": "nbadb_independent_competition_occurrence_proof",
        "package_occurrence_count": counts[0],
        "package_occurrences_sha256": package_occurrences_sha256,
        "package_planning_census_sha256": expected_body[
            "package_occurrence_planning_census_sha256"
        ],
        "projected_role_count": counts[2],
        "repo_alias_count": counts[1],
        "repo_alias_planning_census_sha256": expected_body["repo_alias_planning_census_sha256"],
        "repo_aliases_sha256": repo_aliases_sha256,
        "repo_source_inventory_sha256": expected_body["repo_source_inventory_sha256"],
        "schema_version": 1,
        "verifier_id": _VERIFIER_ID,
    }
    return IndependentCompetitionOccurrenceProof(
        verifier_id=_VERIFIER_ID,
        authority_sha256=expected_authority_sha256,
        checked_payload_sha256=checked_payload_sha256,
        package_occurrences_sha256=package_occurrences_sha256,
        repo_aliases_sha256=repo_aliases_sha256,
        package_planning_census_sha256=str(
            expected_body["package_occurrence_planning_census_sha256"]
        ),
        repo_alias_planning_census_sha256=str(expected_body["repo_alias_planning_census_sha256"]),
        repo_source_inventory_sha256=str(expected_body["repo_source_inventory_sha256"]),
        package_occurrence_count=counts[0],
        repo_alias_count=counts[1],
        projected_role_count=counts[2],
        proof_sha256=_digest(proof_body),
    )


@lru_cache(maxsize=1)
def verify_pinned_competition_occurrence_authority() -> IndependentCompetitionOccurrenceProof:
    """Verify the installed and repository sources against the checked receipt."""

    return _verify(None)


def verify_competition_occurrence_authority_file(
    path: Path,
) -> IndependentCompetitionOccurrenceProof:
    """Verify an explicit candidate receipt without caching it."""

    return _verify(path)


__all__ = [
    "IndependentCompetitionOccurrenceProof",
    "NbaApiCompetitionOccurrenceVerificationError",
    "verify_competition_occurrence_authority_file",
    "verify_pinned_competition_occurrence_authority",
]
