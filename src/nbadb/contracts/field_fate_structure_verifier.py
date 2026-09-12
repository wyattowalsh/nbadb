"""Independent readback verifier for the structural field-fate contract.

The verifier deliberately reconstructs expected rows from installed-source atoms,
the typed runtime registries, and the immutable staging-route bundle.  It does not
call the structural compiler and it has no star-schema or semantic-assurance input.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
from collections import Counter, defaultdict
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import ClassVar, Final, cast

import polars as pl

from nbadb.contracts.field_fate_structure import (
    FieldFateStructureV1,
)
from nbadb.contracts.staging_route_contract import (
    StagingRouteContract,
    StagingRouteContractBundle,
    staging_route_contract_bundle,
    validate_staging_route_contract_bundle,
)
from nbadb.core.nba_api_provenance import verify_nba_api_provider
from nbadb.core.nba_api_request_surface_verifier import (
    IndependentPackageInventory,
    build_independent_package_inventory,
    build_independent_surface_atoms,
)
from nbadb.core.nba_api_runtime_contract import (
    endpoint_contract_sha256,
    load_pinned_runtime_contract_payload,
    owned_contract_sha256,
    pinned_live_contracts,
    pinned_runtime_contracts,
    pinned_static_contracts,
)

__all__ = [
    "FieldFateStructureVerificationError",
    "FieldFateStructureVerificationV1",
    "canonical_verification_bytes",
    "parse_field_fate_structure_verification",
    "validate_field_fate_structure_verification",
    "verify_field_fate_structure",
    "verify_field_fate_structure_independently",
]

_UPSTREAM_ROOT_ENV: Final = "NBADB_NBA_API_DOCS_ROOT"
_LIVE_LOSSLESS_STAGING_KEY: Final = "stg_nba_api_live_lossless_nodes"
_EXACT_CHECKS: Final = tuple(
    sorted(
        {
            "exact_field_level_open_blockers",
            "exact_installed_live_expected_data_occurrences",
            "exact_installed_nested_scalar_projection",
            "exact_installed_static_index_projection_occurrences",
            "exact_installed_stats_occurrences",
            "exact_live_docs_authority_or_explicit_blocker",
            "exact_route_alias_expansion",
            "exact_source_route_partition",
            "exact_storage_sink_partition",
            "immutable_authority_digests",
            "shared_authority_boundaries_declared",
            "unrouted_sources_retained",
        }
    )
)
_SHARED_AUTHORITY_BOUNDARIES: Final = (
    "field_fate_structure_typed_schema",
    "pinned_runtime_contract_typed_registry",
    "staging_route_contract_typed_registry",
)
_LOSSLESS_BINDING_REQUIREMENT: Final = (
    "add an exact transactional raw structured-storage route and receipt for this provider "
    "field without collapsing its source occurrence"
)
_SOURCE_AUTHORITY_REQUIREMENT: Final = (
    "supply the verified exact nba_api checkout so the pinned live documentation bytes can "
    "be read and authenticated"
)
_EXPECTED_REQUEST_SCOPE_FIELD_COUNT: Final = 608
_EXPECTED_REQUEST_SCOPE_ROUTE_COUNT: Final = 313
_EXPECTED_REQUEST_SCOPE_COLUMN_COUNTS: Final = {
    "league_id": 309,
    "season_type": 127,
    "season_year": 172,
}
_REQUEST_SCOPE_POLICIES: Final = (
    (
        "season_year",
        (
            ("season", "large_string"),
            ("season_nullable", "large_string"),
            ("season_year", "int64"),
        ),
    ),
    (
        "season_type",
        (
            ("season_type_all_star", "large_string"),
            ("season_type_playoffs", "large_string"),
            ("season_type", "large_string"),
            ("season_type_nullable", "large_string"),
            ("season_type_all_star_nullable", "large_string"),
        ),
    ),
    (
        "league_id",
        (
            ("league_id", "large_string"),
            ("league_id_nullable", "large_string"),
        ),
    ),
)


class FieldFateStructureVerificationError(RuntimeError):
    """Raised when independent reconstruction differs from structural evidence."""


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FieldFateStructureVerificationError(
            "independent verification value is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _source_id(family: str, endpoint_id: str, result_ordinal: int, field_ordinal: int) -> str:
    return f"source_field:{family}:{endpoint_id}:{result_ordinal:04d}:{field_ordinal:04d}"


def _binding_id(route_id: str, mapping_ordinal: int) -> str:
    return f"route_binding:{route_id}:{mapping_ordinal:04d}"


def _sink_id(route_id: str, storage_ordinal: int) -> str:
    return f"storage_sink:{route_id}:{storage_ordinal:04d}"


def _verify_production_request_scope_policy() -> None:
    """Independently prove the production injection keys, order, and preservation."""

    from nbadb.extract import base

    expected_aliases = {
        column: tuple(name for name, _logical_type in aliases)
        for column, aliases in _REQUEST_SCOPE_POLICIES
    }
    actual_aliases = {
        "season_year": base._SEASON_YEAR_KEYS,
        "season_type": base._SEASON_TYPE_KEYS,
        "league_id": base._LEAGUE_ID_KEYS,
    }
    if tuple(actual_aliases) != tuple(expected_aliases) or actual_aliases != expected_aliases:
        raise FieldFateStructureVerificationError(
            "production request-scope injection policy differs from independent authority"
        )

    probe = pl.DataFrame({"provider_value": [1]})
    try:
        injected = base._inject_request_scope_columns(
            probe,
            {
                "season": "first-season",
                "season_nullable": "second-season",
                "season_type_all_star": "first-type",
                "season_type": "second-type",
                "league_id": "00",
                "league_id_nullable": "10",
            },
        )
        # Use an exact value outside signed int32 so Polars cannot silently
        # narrow the code-owned ``int64`` policy during the replay probe.
        integer_season_year = 1 << 40
        integer = base._inject_request_scope_columns(
            probe,
            {"season_year": integer_season_year},
        )
        provider = pl.DataFrame(
            {
                "season_year": ["provider-season"],
                "season_type": ["provider-type"],
                "league_id": ["provider-league"],
            }
        )
        preserved = base._inject_request_scope_columns(
            provider,
            {
                "season": "request-season",
                "season_type_all_star": "request-type",
                "league_id": "10",
            },
        )
    except Exception as exc:
        raise FieldFateStructureVerificationError(
            "production request-scope injection policy cannot be replayed"
        ) from exc
    if (
        tuple(injected.columns) != ("provider_value", "season_year", "season_type", "league_id")
        or injected.row(0) != (1, "first-season", "first-type", "00")
        or tuple(str(dtype) for dtype in injected.dtypes[1:]) != ("String",) * 3
        or tuple(integer.columns) != ("provider_value", "season_year")
        or integer.row(0) != (1, integer_season_year)
        or str(integer.schema["season_year"]) != "Int64"
        or not preserved.equals(provider)
    ):
        raise FieldFateStructureVerificationError(
            "production request-scope injection behavior differs from independent authority"
        )


def _expected_request_scope_field_rows(
    route: StagingRouteContract,
) -> tuple[dict[str, object], ...]:
    """Rebuild one route's possible scope suffix from pinned parameter authority."""

    if route.source_family != "stats":
        expected: tuple[dict[str, object], ...] = ()
    else:
        contract = pinned_runtime_contracts().get(route.provider_endpoint_id)
        if contract is None:
            raise FieldFateStructureVerificationError(
                "request-scope route lacks pinned parameter authority"
            )
        required = tuple(contract.required_parameters)
        optional = tuple(
            parameter for parameter in contract.parameters if parameter not in required
        )
        if (
            route.provider_required_parameters != required
            or route.provider_optional_parameters != optional
        ):
            raise FieldFateStructureVerificationError(
                "request-scope route parameters differ from pinned authority"
            )
        accepted = set(required) | set(optional)
        rows: list[dict[str, object]] = []
        for storage_column, aliases in _REQUEST_SCOPE_POLICIES:
            if storage_column in route.canonical_columns or storage_column in route.storage_columns:
                continue
            source_names = tuple(name for name, _logical_type in aliases if name in accepted)
            if not source_names:
                continue
            logical_types = {logical_type for name, logical_type in aliases if name in source_names}
            if len(logical_types) != 1:
                raise FieldFateStructureVerificationError(
                    "request-scope aliases have ambiguous independent logical types"
                )
            identity: dict[str, object] = {
                "schema_version": 1,
                "kind": "request_scope_storage_field_v1",
                "route_id": route.route_id,
                "field_ordinal": len(rows),
                "storage_column": storage_column,
                "source_parameter_names": list(source_names),
                "required_parameter_names": [name for name in source_names if name in required],
                "optional_parameter_names": [name for name in source_names if name in optional],
                "logical_type": next(iter(logical_types)),
            }
            rows.append(identity | {"field_sha256": _digest(identity)})
        expected = tuple(rows)

    observed = tuple(item.to_dict() for item in route.request_scope_storage_fields)
    if observed != expected:
        raise FieldFateStructureVerificationError(
            "request-scope fields differ from independent reconstruction"
        )
    expected_columns = route.storage_columns + tuple(
        cast("str", row["storage_column"]) for row in expected
    )
    if route.possible_storage_columns != expected_columns:
        raise FieldFateStructureVerificationError(
            "request-scope possible storage columns are missing, extra, or reordered"
        )
    return expected


@dataclass(frozen=True, slots=True)
class FieldFateStructureVerificationV1:
    """Recomputed structural readback receipt; never a MODEL-GREEN decision."""

    structure_sha256: str
    provider_sources_sha256: str
    route_bindings_sha256: str
    storage_sinks_sha256: str
    lossless_bindings_sha256: str
    blockers_sha256: str
    independent_package_inventory_sha256: str
    independent_source_atoms_sha256: str
    staging_route_contract_sha256: str
    provider_source_occurrence_count: int
    route_binding_count: int
    routed_source_occurrence_count: int
    unrouted_source_occurrence_count: int
    lossless_field_binding_count: int
    storage_sink_count: int
    provider_bound_storage_sink_count: int
    storage_only_sink_count: int
    source_authority_blocker_count: int
    unresolved_lossless_binding_count: int
    open_blocker_count: int
    authority_mode: str
    wide_route_complete: bool
    lossless_field_binding_complete: bool
    verified_against_current_authorities: bool
    shared_authority_boundaries: tuple[str, ...]
    checks: tuple[str, ...]

    schema_version: ClassVar[int] = 3
    kind: ClassVar[str] = "field_fate_structure_verification"

    def __post_init__(self) -> None:
        for field_name in (
            "structure_sha256",
            "provider_sources_sha256",
            "route_bindings_sha256",
            "storage_sinks_sha256",
            "lossless_bindings_sha256",
            "blockers_sha256",
            "independent_package_inventory_sha256",
            "independent_source_atoms_sha256",
            "staging_route_contract_sha256",
        ):
            value = getattr(self, field_name)
            if (
                type(value) is not str
                or len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise FieldFateStructureVerificationError(
                    f"{field_name} must be a lowercase SHA-256"
                )
        count_fields = (
            "provider_source_occurrence_count",
            "route_binding_count",
            "routed_source_occurrence_count",
            "unrouted_source_occurrence_count",
            "lossless_field_binding_count",
            "storage_sink_count",
            "provider_bound_storage_sink_count",
            "storage_only_sink_count",
            "source_authority_blocker_count",
            "unresolved_lossless_binding_count",
            "open_blocker_count",
        )
        if any(
            type(getattr(self, name)) is not int or getattr(self, name) < 0 for name in count_fields
        ):
            raise FieldFateStructureVerificationError(
                "verification receipt counts must be exact nonnegative integers"
            )
        if self.provider_source_occurrence_count <= 0 or self.route_binding_count <= 0:
            raise FieldFateStructureVerificationError("verification receipt cannot be empty")
        if (
            self.routed_source_occurrence_count + self.unrouted_source_occurrence_count
            != self.provider_source_occurrence_count
            or self.provider_bound_storage_sink_count + self.storage_only_sink_count
            != self.storage_sink_count
            or self.lossless_field_binding_count + self.unresolved_lossless_binding_count
            != self.unrouted_source_occurrence_count
            or self.open_blocker_count
            != self.source_authority_blocker_count + self.unresolved_lossless_binding_count
        ):
            raise FieldFateStructureVerificationError("verification receipt partitions drifted")
        if self.authority_mode not in {"exact_checkout", "blocked_missing_checkout"}:
            raise FieldFateStructureVerificationError("verification authority mode is unsupported")
        if (
            (self.authority_mode == "exact_checkout") != (self.source_authority_blocker_count == 0)
            or type(self.wide_route_complete) is not bool
            or self.wide_route_complete != (self.unrouted_source_occurrence_count == 0)
            or type(self.lossless_field_binding_complete) is not bool
            or self.lossless_field_binding_complete != (self.unresolved_lossless_binding_count == 0)
        ):
            raise FieldFateStructureVerificationError(
                "verification receipt misstates open source/storage blockers"
            )
        if self.verified_against_current_authorities is not True:
            raise FieldFateStructureVerificationError(
                "verification receipt lacks current-authority recomputation"
            )
        if self.shared_authority_boundaries != _SHARED_AUTHORITY_BOUNDARIES:
            raise FieldFateStructureVerificationError(
                "verification receipt omits a shared-authority boundary"
            )
        if self.checks != _EXACT_CHECKS:
            raise FieldFateStructureVerificationError("verification check set is not exact")

    @property
    def receipt_sha256(self) -> str:
        return _digest(self.to_dict())

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "structure_sha256": self.structure_sha256,
            "provider_sources_sha256": self.provider_sources_sha256,
            "route_bindings_sha256": self.route_bindings_sha256,
            "storage_sinks_sha256": self.storage_sinks_sha256,
            "lossless_bindings_sha256": self.lossless_bindings_sha256,
            "blockers_sha256": self.blockers_sha256,
            "independent_package_inventory_sha256": (self.independent_package_inventory_sha256),
            "independent_source_atoms_sha256": self.independent_source_atoms_sha256,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "authority_mode": self.authority_mode,
            "summary": {
                "provider_source_occurrence_count": self.provider_source_occurrence_count,
                "route_binding_count": self.route_binding_count,
                "routed_source_occurrence_count": self.routed_source_occurrence_count,
                "unrouted_source_occurrence_count": self.unrouted_source_occurrence_count,
                "lossless_field_binding_count": self.lossless_field_binding_count,
                "storage_sink_count": self.storage_sink_count,
                "provider_bound_storage_sink_count": self.provider_bound_storage_sink_count,
                "storage_only_sink_count": self.storage_only_sink_count,
                "source_authority_blocker_count": self.source_authority_blocker_count,
                "unresolved_lossless_binding_count": self.unresolved_lossless_binding_count,
                "open_blocker_count": self.open_blocker_count,
                "wide_route_complete": self.wide_route_complete,
                "lossless_field_binding_complete": self.lossless_field_binding_complete,
                "verified_against_current_authorities": (self.verified_against_current_authorities),
                "model_green": "not_evaluated_by_structural_verifier",
            },
            "shared_authority_boundaries": list(self.shared_authority_boundaries),
            "checks": list(self.checks),
        }


def _root_key(upstream_root: Path | str | None) -> str | None:
    candidate = upstream_root if upstream_root is not None else os.getenv(_UPSTREAM_ROOT_ENV)
    if candidate is None or not str(candidate).strip():
        return None
    try:
        resolved = Path(candidate).expanduser().resolve(strict=True)
    except OSError as exc:
        raise FieldFateStructureVerificationError(
            "independent exact nba_api checkout is unreadable"
        ) from exc
    if resolved.is_symlink() or not resolved.is_dir():
        raise FieldFateStructureVerificationError(
            "independent exact nba_api checkout is not a regular directory"
        )
    return str(resolved)


@lru_cache(maxsize=4)
def _checked_root(root_key: str) -> Path:
    root = Path(root_key)
    result = verify_nba_api_provider(
        root,
        project_root=Path(__file__).resolve().parents[3],
    )
    if result.get("verified") is not True:
        raise FieldFateStructureVerificationError(
            "independent exact nba_api checkout failed release verification"
        )
    return root


def _package_bytes(relative_path: str) -> bytes:
    if not relative_path.startswith("nba_api/") or ".." in Path(relative_path).parts:
        raise FieldFateStructureVerificationError("independent package source path is invalid")
    try:
        return (
            resources.files("nba_api")
            .joinpath(*relative_path.removeprefix("nba_api/").split("/"))
            .read_bytes()
        )
    except (FileNotFoundError, OSError) as exc:
        raise FieldFateStructureVerificationError(
            "independent package source is unreadable"
        ) from exc


def _module_assignment(nodes: list[ast.stmt], name: str) -> ast.AST:
    found = [
        node.value
        for node in nodes
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == name for target in node.targets)
    ]
    if len(found) != 1:
        raise FieldFateStructureVerificationError(
            f"independent installed source lacks one {name} assignment"
        )
    return found[0]


def _docs_field_evidence(
    root_key: str | None,
) -> dict[tuple[str, str], tuple[str, str, str]]:
    checked = _checked_root(root_key) if root_key is not None else None
    evidence_by_path: dict[tuple[str, str], tuple[str, str, str]] = {}
    for endpoint_id, contract in sorted(pinned_live_contracts().items()):
        fields = [
            field
            for result_set in contract.result_sets
            for field in result_set.fields
            if field.provenance_source == "live_docs_about_fields"
        ]
        if not fields:
            continue
        if checked is None:
            for live_field in fields:
                body = {
                    "schema_version": 1,
                    "kind": "unavailable_checked_upstream_live_docs_field",
                    "endpoint_id": endpoint_id,
                    "source_path": live_field.json_path,
                    "field_name": live_field.name,
                    "docs_source_path": contract.docs_source_path,
                    "expected_docs_source_sha256": contract.docs_source_sha256,
                    "reason": "exact_upstream_checkout_not_supplied",
                }
                evidence_by_path[(endpoint_id, live_field.json_path)] = (
                    f"unverified_live_docs_field:{endpoint_id}:{live_field.json_path}",
                    _digest(body),
                    "unverified_live_docs_field",
                )
            continue
        path = checked.joinpath(*contract.docs_source_path.split("/"))
        try:
            raw = path.read_bytes()
            lines = raw.decode("utf-8", errors="strict").splitlines()
        except (OSError, UnicodeDecodeError) as exc:
            raise FieldFateStructureVerificationError(
                "independent checked live docs are unreadable"
            ) from exc
        raw_sha = hashlib.sha256(raw).hexdigest()
        if raw_sha != contract.docs_source_sha256:
            raise FieldFateStructureVerificationError(
                "independent checked live docs differ from exact digest"
            )
        row_index: dict[str, tuple[int, str]] = {}
        for ordinal, line in enumerate(lines):
            if not line.lstrip().startswith("`") or "`|" not in line:
                continue
            field_name = line.lstrip()[1:].split("`|", 1)[0]
            if not field_name or field_name in row_index:
                raise FieldFateStructureVerificationError(
                    "independent checked live-docs field rows overlap"
                )
            row_index[field_name] = (ordinal, hashlib.sha256(line.encode()).hexdigest())
        for live_field in fields:
            line_authority = row_index.get(live_field.name)
            if line_authority is None:
                raise FieldFateStructureVerificationError(
                    "independent checked live docs omit one contract field"
                )
            body = {
                "schema_version": 1,
                "kind": "checked_upstream_live_docs_field",
                "endpoint_id": endpoint_id,
                "source_path": live_field.json_path,
                "field_name": live_field.name,
                "docs_source_path": contract.docs_source_path,
                "docs_source_sha256": raw_sha,
                "line_ordinal": line_authority[0],
                "line_sha256": line_authority[1],
            }
            evidence_by_path[(endpoint_id, live_field.json_path)] = (
                f"upstream_live_docs_field:{endpoint_id}:{live_field.json_path}",
                _digest(body),
                "upstream_live_docs_field",
            )
    return evidence_by_path


def _nested_field_evidence() -> dict[tuple[str, str], tuple[str, str, str]]:
    parser_path = Path(__file__).resolve().parents[1] / "core" / "nba_api_contract.py"
    parser_raw = parser_path.read_bytes()
    parser_tree = ast.parse(parser_raw.decode("utf-8", errors="strict"))
    parser_functions = [
        node
        for node in parser_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_flatten_live_expected_data_node"
    ]
    if len(parser_functions) != 1:
        raise FieldFateStructureVerificationError(
            "independent nested projection function is absent or ambiguous"
        )
    projection_markers = [
        node
        for node in ast.walk(parser_functions[0])
        if isinstance(node, ast.Constant) and node.value == "nbadb_nested_scalar_projection"
    ]
    value_calls = [
        node
        for node in ast.walk(parser_functions[0])
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_live_shape_field"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and node.args[0].value == "value"
    ]
    if len(projection_markers) != 1 or len(value_calls) != 1:
        raise FieldFateStructureVerificationError(
            "independent nested projection rule is absent or ambiguous"
        )

    result: dict[tuple[str, str], tuple[str, str, str]] = {}
    for endpoint_id, contract in sorted(pinned_live_contracts().items()):
        raw = _package_bytes(contract.source_path)
        if hashlib.sha256(raw).hexdigest() != contract.source_sha256:
            raise FieldFateStructureVerificationError(
                "independent installed live source digest drifted"
            )
        tree = ast.parse(raw.decode("utf-8", errors="strict"))
        classes = [
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == endpoint_id
        ]
        if len(classes) != 1:
            raise FieldFateStructureVerificationError(
                "independent installed live endpoint class is ambiguous"
            )
        expected_data = ast.literal_eval(_module_assignment(classes[0].body, "expected_data"))
        for result_set in contract.result_sets:
            for field in result_set.fields:
                if field.provenance_source != "nbadb_nested_scalar_projection":
                    continue
                path_parts = field.json_path.removeprefix("$.").split(".")
                cursor: object = expected_data
                for part in path_parts[:-2]:
                    if not isinstance(cursor, dict) or part not in cursor:
                        raise FieldFateStructureVerificationError(
                            "independent nested parent path is absent"
                        )
                    cursor = cast("dict[str, object]", cursor)[part]
                    if isinstance(cursor, list):
                        if not cursor:
                            raise FieldFateStructureVerificationError(
                                "independent nested parent list is empty"
                            )
                        cursor = cursor[0]
                parent_key = path_parts[-2]
                if not isinstance(cursor, dict) or parent_key not in cursor:
                    raise FieldFateStructureVerificationError(
                        "independent nested scalar parent is absent"
                    )
                scalar_items = cast("dict[str, object]", cursor)[parent_key]
                if (
                    not isinstance(scalar_items, list)
                    or not scalar_items
                    or any(isinstance(item, dict | list) for item in scalar_items)
                ):
                    raise FieldFateStructureVerificationError(
                        "independent nested authority is not a scalar list"
                    )
                body = {
                    "schema_version": 1,
                    "kind": "installed_live_nested_scalar_projection",
                    "endpoint_id": endpoint_id,
                    "source_path": field.json_path,
                    "field_name": field.name,
                    "runtime_source_path": contract.source_path,
                    "runtime_source_sha256": contract.source_sha256,
                    "parser_source_path": "src/nbadb/core/nba_api_contract.py",
                    "parser_source_sha256": hashlib.sha256(parser_raw).hexdigest(),
                    "projection_rule": "nonempty_scalar_list_item_to_value_field_v1",
                    "observed_scalar_type_names": sorted(
                        {type(item).__name__ for item in scalar_items}
                    ),
                }
                result[(endpoint_id, field.json_path)] = (
                    f"installed_live_nested_scalar_projection:{endpoint_id}:{field.json_path}",
                    _digest(body),
                    "installed_live_nested_scalar_projection",
                )
    return result


def _static_field_evidence() -> dict[tuple[str, int], tuple[str, str, str]]:
    result: dict[tuple[str, int], tuple[str, str, str]] = {}
    for dataset_id, contract in sorted(pinned_static_contracts().items()):
        provider_raw = _package_bytes(contract.provider_source_path)
        data_raw = _package_bytes(contract.data_source_path)
        if hashlib.sha256(provider_raw).hexdigest() != contract.provider_source_sha256:
            raise FieldFateStructureVerificationError(
                "independent static provider source digest drifted"
            )
        if hashlib.sha256(data_raw).hexdigest() != contract.data_source_sha256:
            raise FieldFateStructureVerificationError(
                "independent static data source digest drifted"
            )
        provider_tree = ast.parse(provider_raw.decode("utf-8", errors="strict"))
        data_tree = ast.parse(data_raw.decode("utf-8", errors="strict"))
        prefix = "player_index_" if dataset_id.endswith("players") else "team_index_"
        indexes: dict[str, int] = {}
        for node in data_tree.body:
            if not isinstance(node, ast.Assign) or len(node.targets) != 1:
                continue
            target = node.targets[0]
            if not isinstance(target, ast.Name) or not target.id.startswith(prefix):
                continue
            ordinal = ast.literal_eval(node.value)
            if type(ordinal) is not int or ordinal < 0:
                raise FieldFateStructureVerificationError(
                    "independent static index constant is invalid"
                )
            indexes[target.id] = ordinal

        projection_candidates: list[tuple[str, dict[str, str]]] = []
        for function in (node for node in provider_tree.body if isinstance(node, ast.FunctionDef)):
            returns = [node for node in ast.walk(function) if isinstance(node, ast.Return)]
            if len(returns) != 1 or not isinstance(returns[0].value, ast.Dict):
                continue
            projection: dict[str, str] = {}
            for key, value in zip(returns[0].value.keys, returns[0].value.values, strict=True):
                if (
                    not isinstance(key, ast.Constant)
                    or not isinstance(key.value, str)
                    or not isinstance(value, ast.Subscript)
                    or not isinstance(value.slice, ast.Name)
                ):
                    projection = {}
                    break
                projection[key.value] = value.slice.id
            if projection:
                projection_candidates.append((function.name, projection))
        if len(projection_candidates) != 1:
            raise FieldFateStructureVerificationError(
                "independent static getter projection is ambiguous"
            )
        getter_function, projection = projection_candidates[0]
        projected_names = {index_name: name for name, index_name in projection.items()}
        if len(projected_names) != len(projection):
            raise FieldFateStructureVerificationError(
                "independent static getter projection collapses indexes"
            )
        rows = _module_assignment(data_tree.body, contract.source_symbol)
        if not isinstance(rows, ast.List) or not rows.elts:
            raise FieldFateStructureVerificationError(
                "independent static source row assignment is absent"
            )
        widths = {len(row.elts) for row in rows.elts if isinstance(row, ast.List | ast.Tuple)}
        if len(widths) != 1 or len(rows.elts) != contract.row_count:
            raise FieldFateStructureVerificationError("independent static source row shape drifted")
        (width,) = tuple(widths)
        for index_name, ordinal in sorted(indexes.items(), key=lambda item: item[1]):
            projected_name = projected_names.get(index_name)
            field_name = projected_name or index_name.removeprefix(prefix)
            contract_fields = [field for field in contract.raw_fields if field.ordinal == ordinal]
            if len(contract_fields) != 1 or contract_fields[0].name != field_name:
                raise FieldFateStructureVerificationError(
                    "independent static ordinal/name differs from typed registry"
                )
            getter_projected = projected_name is not None
            if getter_projected != (
                contract_fields[0].provider_projection_disposition == "projected_by_provider"
            ):
                raise FieldFateStructureVerificationError(
                    "independent static projection disposition drifted"
                )
            body = {
                "schema_version": 1,
                "kind": "installed_static_field_projection",
                "dataset_id": dataset_id,
                "source_symbol": contract.source_symbol,
                "field_name": field_name,
                "field_ordinal": ordinal,
                "data_index_constant": index_name,
                "getter_projection_function": getter_function,
                "getter_projected": getter_projected,
                "provider_source_path": contract.provider_source_path,
                "provider_source_sha256": contract.provider_source_sha256,
                "data_source_path": contract.data_source_path,
                "data_source_sha256": contract.data_source_sha256,
                "source_row_count": len(rows.elts),
                "source_row_width": width,
            }
            result[(dataset_id, ordinal)] = (
                f"installed_static_field_projection:{dataset_id}:{ordinal:04d}",
                _digest(body),
                "installed_static_field_projection",
            )
    return result


def _evidence_inventory_digest(
    source_rows: dict[str, dict[str, object]],
    kinds: set[str],
) -> str:
    return _digest(
        [
            {
                "occurrence_id": occurrence_id,
                "authority_atom_id": row["authority_atom_id"],
                "authority_atom_sha256": row["authority_atom_sha256"],
                "provenance_kind": row["provenance_kind"],
            }
            for occurrence_id, row in sorted(source_rows.items())
            if row["provenance_kind"] in kinds
        ]
    )


def _expected_source_rows(
    root_key: str | None,
) -> tuple[
    dict[str, dict[str, object]],
    IndependentPackageInventory,
    str,
]:
    inventory = build_independent_package_inventory()
    atoms = build_independent_surface_atoms()
    if _digest(list(atoms)) != inventory.source_atoms_sha256:
        raise FieldFateStructureVerificationError("independent source-atom digest is stale")
    atom_by_id = {cast("str", atom["atom_id"]): atom for atom in atoms}
    if len(atom_by_id) != len(atoms):
        raise FieldFateStructureVerificationError("independent source atoms overlap")

    expected: dict[str, dict[str, object]] = {}
    stats_atoms = tuple(atom for atom in atoms if atom.get("kind") == "stats_result_header")
    for atom in stats_atoms:
        endpoint_id = cast("str", atom["endpoint_id"])
        result_ordinal = cast("int", atom["result_set_ordinal"])
        field_ordinal = cast("int", atom["header_ordinal"])
        result_name = cast("str", atom["result_set_name"])
        header = cast("str", atom["header"])
        contract = pinned_runtime_contracts().get(endpoint_id)
        result_sets = (
            ()
            if contract is None
            else tuple(
                result_set
                for result_set in contract.result_sets
                if result_set.result_set_index == result_ordinal
            )
        )
        if (
            contract is None
            or len(result_sets) != 1
            or (
                result_sets[0].result_set_name != result_name
                or field_ordinal >= len(result_sets[0].expected_columns)
                or result_sets[0].expected_columns[field_ordinal] != header
            )
        ):
            raise FieldFateStructureVerificationError(
                "stats atom differs from the typed runtime authority"
            )
        occurrence_id = _source_id("stats", endpoint_id, result_ordinal, field_ordinal)
        row: dict[str, object] = {
            "occurrence_id": occurrence_id,
            "source_family": "stats",
            "endpoint_id": endpoint_id,
            "result_set_name": result_name,
            "result_set_ordinal": result_ordinal,
            "field_ordinal": field_ordinal,
            "provider_field_name": header,
            "source_path": (
                f"result_sets[{result_ordinal}].{result_name}.headers[{field_ordinal}]"
            ),
            "authority_atom_id": atom["atom_id"],
            "authority_atom_sha256": _digest(atom),
            "endpoint_contract_sha256": endpoint_contract_sha256(contract),
            "provenance_kind": "installed_stats_header_atom",
            "direct_source_field": True,
        }
        if occurrence_id in expected:
            raise FieldFateStructureVerificationError("stats source identities overlap")
        expected[occurrence_id] = row

    docs_evidence = _docs_field_evidence(root_key)
    nested_evidence = _nested_field_evidence()
    direct_live_atom_ids: set[str] = set()
    for endpoint_id, contract in sorted(pinned_live_contracts().items()):
        endpoint_atom_id = f"endpoint:live:{endpoint_id}"
        endpoint_atom = atom_by_id.get(endpoint_atom_id)
        if endpoint_atom is None:
            raise FieldFateStructureVerificationError("live endpoint authority is absent")
        for result_set in contract.result_sets:
            for live_field in result_set.fields:
                direct_atom_id = f"live_source_field:{endpoint_id}:{live_field.json_path}"
                authority_atom = atom_by_id.get(direct_atom_id)
                if authority_atom is None:
                    independent = docs_evidence.get(
                        (endpoint_id, live_field.json_path)
                    ) or nested_evidence.get((endpoint_id, live_field.json_path))
                    if independent is None:
                        raise FieldFateStructureVerificationError(
                            "non-runtime live field lacks independent docs/parser evidence"
                        )
                    authority_atom_id, authority_atom_sha256, provenance_kind = independent
                else:
                    authority_atom_id = direct_atom_id
                    provenance_kind = "installed_live_source_field_atom"
                    direct_live_atom_ids.add(direct_atom_id)
                occurrence_id = _source_id(
                    "live", endpoint_id, result_set.ordinal, live_field.ordinal
                )
                row: dict[str, object] = {
                    "occurrence_id": occurrence_id,
                    "source_family": "live",
                    "endpoint_id": endpoint_id,
                    "result_set_name": result_set.name,
                    "result_set_ordinal": result_set.ordinal,
                    "field_ordinal": live_field.ordinal,
                    "provider_field_name": live_field.name,
                    "source_path": live_field.json_path,
                    "authority_atom_id": authority_atom_id,
                    "authority_atom_sha256": (
                        _digest(authority_atom)
                        if authority_atom is not None
                        else authority_atom_sha256
                    ),
                    "endpoint_contract_sha256": owned_contract_sha256(contract),
                    "provenance_kind": provenance_kind,
                    "direct_source_field": live_field.source_field,
                }
                if occurrence_id in expected:
                    raise FieldFateStructureVerificationError("live source identities overlap")
                expected[occurrence_id] = row
    live_atom_ids = {
        cast("str", atom["atom_id"]) for atom in atoms if atom.get("kind") == "live_source_field"
    }
    if direct_live_atom_ids != live_atom_ids:
        raise FieldFateStructureVerificationError("live direct-source atom partition drifted")

    static_atoms = {
        cast("str", atom["dataset_id"]): atom
        for atom in atoms
        if atom.get("kind") == "static_dataset"
    }
    static_contracts = pinned_static_contracts()
    static_evidence = _static_field_evidence()
    if set(static_contracts) != set(static_atoms):
        raise FieldFateStructureVerificationError("static dataset identities drifted")
    for dataset_id, contract in sorted(static_contracts.items()):
        atom = static_atoms[dataset_id]
        if atom.get("source_symbol") != contract.source_symbol or atom.get("row_width") != len(
            contract.raw_fields
        ):
            raise FieldFateStructureVerificationError("static field shape authority drifted")
        for static_field in contract.raw_fields:
            authority = static_evidence.get((dataset_id, static_field.ordinal))
            if authority is None:
                raise FieldFateStructureVerificationError(
                    "static field lacks independent index/projection evidence"
                )
            occurrence_id = _source_id("static", dataset_id, 0, static_field.ordinal)
            row: dict[str, object] = {
                "occurrence_id": occurrence_id,
                "source_family": "static",
                "endpoint_id": dataset_id,
                "result_set_name": f"{contract.source_symbol}_shape_1",
                "result_set_ordinal": 0,
                "field_ordinal": static_field.ordinal,
                "provider_field_name": static_field.name,
                "source_path": f"{contract.source_symbol}[*][{static_field.ordinal}]",
                "authority_atom_id": authority[0],
                "authority_atom_sha256": authority[1],
                "endpoint_contract_sha256": owned_contract_sha256(contract),
                "provenance_kind": authority[2],
                "direct_source_field": True,
            }
            if occurrence_id in expected:
                raise FieldFateStructureVerificationError("static source identities overlap")
            expected[occurrence_id] = row

    if len(expected) != len(stats_atoms) + len(live_atom_ids) + len(docs_evidence) + len(
        nested_evidence
    ) + len(static_evidence):
        raise FieldFateStructureVerificationError(
            "independently derived provider source denominator does not conserve evidence"
        )
    return (
        expected,
        inventory,
        cast("str", load_pinned_runtime_contract_payload()["payload_sha256"]),
    )


def _route_source_row(
    route: StagingRouteContract,
    mapping_ordinal: int,
    source_by_ordinal: dict[tuple[str, str, int, int], dict[str, object]],
    live_by_path: dict[tuple[str, str], dict[str, object]],
) -> dict[str, object]:
    mapping = route.column_mappings[mapping_ordinal]
    if route.source_family == "live" and mapping.transform == "nested_projection":
        contract = pinned_live_contracts().get(route.provider_endpoint_id)
        base_sets = (
            ()
            if contract is None or route.provider_result_set_ordinal is None
            else tuple(
                result_set
                for result_set in contract.result_sets
                if result_set.ordinal == route.provider_result_set_ordinal
            )
        )
        if len(base_sets) != 1:
            raise FieldFateStructureVerificationError("nested route base is ambiguous")
        source = live_by_path.get(
            (route.provider_endpoint_id, f"{base_sets[0].json_path}.{mapping.provider_column}")
        )
    else:
        if (
            route.provider_result_set_ordinal is None
            or mapping_ordinal >= len(route.provider_columns)
            or route.provider_columns[mapping_ordinal] != mapping.provider_column
        ):
            raise FieldFateStructureVerificationError("route mapping ordinal drifted")
        source = source_by_ordinal.get(
            (
                route.source_family,
                route.provider_endpoint_id,
                route.provider_result_set_ordinal,
                mapping_ordinal,
            )
        )
    if source is None or source["provider_field_name"] != mapping.provider_column.split(".")[-1]:
        raise FieldFateStructureVerificationError("route mapping lacks one exact source")
    if source["endpoint_contract_sha256"] != route.endpoint_contract_sha256:
        raise FieldFateStructureVerificationError("route source contract digest drifted")
    return source


def _expected_route_rows(
    source_rows: dict[str, dict[str, object]],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    StagingRouteContractBundle,
]:
    routes = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(routes)
    if not routes.routes:
        raise FieldFateStructureVerificationError("independent route authority is empty")
    source_by_ordinal = {
        (
            cast("str", row["source_family"]),
            cast("str", row["endpoint_id"]),
            cast("int", row["result_set_ordinal"]),
            cast("int", row["field_ordinal"]),
        ): row
        for row in source_rows.values()
    }
    live_by_path = {
        (cast("str", row["endpoint_id"]), cast("str", row["source_path"])): row
        for row in source_rows.values()
        if row["source_family"] == "live"
    }
    if len(source_by_ordinal) != len(source_rows):
        raise FieldFateStructureVerificationError("source ordinal identities overlap")

    expected_bindings: dict[str, dict[str, object]] = {}
    bindings_by_source: dict[str, list[dict[str, object]]] = defaultdict(list)
    request_scope_counts: Counter[str] = Counter()
    request_scope_route_count = 0
    for route in routes.routes:
        request_scope_rows = _expected_request_scope_field_rows(route)
        request_scope_counts.update(
            cast("str", row["storage_column"]) for row in request_scope_rows
        )
        request_scope_route_count += bool(request_scope_rows)
        for mapping_ordinal, mapping in enumerate(route.column_mappings):
            source = _route_source_row(route, mapping_ordinal, source_by_ordinal, live_by_path)
            if mapping.storage_column is None:
                raise FieldFateStructureVerificationError("route mapping has no storage sink")
            storage_ordinals = tuple(
                ordinal
                for ordinal, column in enumerate(route.storage_columns)
                if column == mapping.storage_column
            )
            if len(storage_ordinals) != 1:
                raise FieldFateStructureVerificationError("route storage sink is ambiguous")
            binding_id = _binding_id(route.route_id, mapping_ordinal)
            row: dict[str, object] = {
                "binding_id": binding_id,
                "route_id": route.route_id,
                "route_ordinal": route.ordinal,
                "mapping_ordinal": mapping_ordinal,
                "source_family": route.source_family,
                "source_occurrence_id": source["occurrence_id"],
                "source_occurrence_sha256": _digest(source),
                "route_contract_sha256": route.contract_sha256,
                "endpoint_role": route.endpoint_role,
                "endpoint_alias_target": route.endpoint_alias_target,
                "storage_role": route.storage_role,
                "storage_role_target": route.storage_role_target,
                "provider_column": mapping.provider_column,
                "canonical_column": mapping.canonical_column,
                "mapping_transform": mapping.transform,
                "storage_sink_id": _sink_id(route.route_id, storage_ordinals[0]),
                "storage_column": mapping.storage_column,
            }
            if binding_id in expected_bindings:
                raise FieldFateStructureVerificationError("route binding identities overlap")
            expected_bindings[binding_id] = row
            bindings_by_source[cast("str", source["occurrence_id"])].append(row)

    if (
        sum(request_scope_counts.values()) != _EXPECTED_REQUEST_SCOPE_FIELD_COUNT
        or request_scope_route_count != _EXPECTED_REQUEST_SCOPE_ROUTE_COUNT
        or request_scope_counts != _EXPECTED_REQUEST_SCOPE_COLUMN_COUNTS
    ):
        raise FieldFateStructureVerificationError(
            "request-scope field census differs from independent pinned authority"
        )

    expected_expansions: dict[str, dict[str, object]] = {}
    for occurrence_id, source in sorted(source_rows.items()):
        bindings = bindings_by_source.get(occurrence_id, [])
        binding_ids = tuple(sorted(cast("str", row["binding_id"]) for row in bindings))
        expected_expansions[occurrence_id] = {
            "source_occurrence_id": occurrence_id,
            "source_occurrence_sha256": _digest(source),
            "binding_ids": list(binding_ids),
            "alias_binding_ids": sorted(
                cast("str", row["binding_id"])
                for row in bindings
                if row["endpoint_role"] != "canonical"
            ),
            "copy_binding_ids": sorted(
                cast("str", row["binding_id"])
                for row in bindings
                if row["storage_role"] != "direct"
            ),
            "status": (
                "unrouted"
                if not binding_ids
                else "single_route"
                if len(binding_ids) == 1
                else "expanded_routes"
            ),
        }
    return expected_bindings, expected_expansions, routes


def _expected_sink_rows(
    binding_rows: dict[str, dict[str, object]],
    routes: StagingRouteContractBundle,
) -> dict[str, dict[str, object]]:
    bindings_by_sink: dict[str, list[str]] = defaultdict(list)
    for binding_id, row in binding_rows.items():
        bindings_by_sink[cast("str", row["storage_sink_id"])].append(binding_id)
    expected: dict[str, dict[str, object]] = {}
    for route in routes.routes:
        request_scope_rows = _expected_request_scope_field_rows(route)
        possible_storage_columns = route.storage_columns + tuple(
            cast("str", row["storage_column"]) for row in request_scope_rows
        )
        for storage_ordinal, storage_column in enumerate(possible_storage_columns):
            sink_id = _sink_id(route.route_id, storage_ordinal)
            binding_ids = sorted(bindings_by_sink.get(sink_id, ()))
            expected[sink_id] = {
                "sink_id": sink_id,
                "route_id": route.route_id,
                "route_ordinal": route.ordinal,
                "storage_ordinal": storage_ordinal,
                "staging_key": route.staging_key,
                "schema_tier": route.resolved_schema_tier,
                "schema_table": route.resolved_schema_table,
                "schema_class": route.resolved_schema_class,
                "storage_role": route.storage_role,
                "storage_role_target": route.storage_role_target,
                "storage_column": storage_column,
                "route_contract_sha256": route.contract_sha256,
                "binding_ids": binding_ids,
                "status": "provider_bound" if binding_ids else "storage_only",
            }
    return expected


@lru_cache(maxsize=1)
def _independent_live_lossless_sink_authority() -> str:
    root = Path(__file__).resolve().parents[3]
    paths = (
        "src/nbadb/contracts/staging_route_contract.py",
        "src/nbadb/extract/live_lossless.py",
        "src/nbadb/extract/nba_api_adapter.py",
        "src/nbadb/orchestrate/extractor_runner.py",
        "src/nbadb/orchestrate/staging_batches.py",
        "src/nbadb/schemas/staging/nba_api_live_lossless.py",
    )
    parsed: dict[str, tuple[bytes, ast.Module]] = {}
    for relative in paths:
        raw = (root / relative).read_bytes()
        parsed[relative] = (raw, ast.parse(raw.decode("utf-8", errors="strict")))

    live_nodes = parsed["src/nbadb/extract/live_lossless.py"][1].body
    schema_values = [
        node.value
        for node in live_nodes
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "LIVE_LOSSLESS_SCHEMA"
    ]
    if len(schema_values) != 1 or not isinstance(schema_values[0], ast.Dict):
        raise FieldFateStructureVerificationError(
            "independent live lossless schema assignment is absent"
        )
    columns: list[str] = []
    for key in schema_values[0].keys:
        if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
            raise FieldFateStructureVerificationError(
                "independent live lossless schema column is not literal"
            )
        columns.append(key.value)
    if len(columns) != len(set(columns)):
        raise FieldFateStructureVerificationError(
            "independent live lossless schema columns overlap"
        )
    required = {
        "array_ordinal",
        "canonical_json",
        "contract_field_ordinal",
        "contract_json_path",
        "endpoint_contract_sha256",
        "endpoint_id",
        "object_key",
        "presence_kind",
        "provider_authority_sha256",
        "request_parameters_json",
        "response_receipt_sha256",
        "result_set_ordinal",
        "snapshot_at",
        "value_kind",
    }
    if not required <= set(columns):
        raise FieldFateStructureVerificationError(
            "independent live lossless sink selector columns are incomplete"
        )

    schema_classes = [
        node
        for node in parsed["src/nbadb/schemas/staging/nba_api_live_lossless.py"][1].body
        if isinstance(node, ast.ClassDef) and node.name == "StagingNbaApiLiveLosslessNodesSchema"
    ]
    if len(schema_classes) != 1:
        raise FieldFateStructureVerificationError(
            "independent live lossless staging schema is ambiguous"
        )
    staged_columns = [
        node.target.id
        for node in schema_classes[0].body
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
    ]
    if staged_columns != columns:
        raise FieldFateStructureVerificationError(
            "independent live lossless frame/staging schemas differ"
        )

    expected_symbols = {
        "src/nbadb/contracts/staging_route_contract.py": {
            "admit_conditional_live_lossless_route",
        },
        "src/nbadb/extract/live_lossless.py": {
            "NbaApiLiveLosslessLanding",
            "build_live_lossless_landing",
            "reconstruct_live_payload",
            "validate_live_lossless_frame",
        },
        "src/nbadb/extract/nba_api_adapter.py": {
            "_parse_live_payloads",
            "fetch_live_payloads",
            "replay_live_payloads",
        },
        "src/nbadb/orchestrate/extractor_runner.py": {"ExtractorRunner"},
        "src/nbadb/orchestrate/staging_batches.py": {
            "_validate_persisted_live_lossless",
        },
    }
    for relative, names in expected_symbols.items():
        observed = {
            node.name
            for node in parsed[relative][1].body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        }
        if not names <= observed:
            raise FieldFateStructureVerificationError(
                "independent live lossless implementation symbols are incomplete"
            )

    runner_classes = [
        node
        for node in parsed["src/nbadb/orchestrate/extractor_runner.py"][1].body
        if isinstance(node, ast.ClassDef) and node.name == "ExtractorRunner"
    ]
    if len(runner_classes) != 1:
        raise FieldFateStructureVerificationError(
            "independent live lossless runner authority is ambiguous"
        )
    runner_methods = {
        node.name: node
        for node in runner_classes[0].body
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
    }
    required_runner_calls = {
        "_verified_live_lossless_landings": {"validate_live_lossless_frame"},
        "_verify_live_lossless_request_scope": {
            "admit_conditional_live_lossless_route",
            "logical_parameters_sha256",
        },
        "_admit_conditional_result_routes": {"_conditional_route_admission"},
        "_finalize_logical_call_receipt": {
            "LogicalCallReceiptBinding",
            "record_logical_call",
        },
    }
    for method_name, required_calls in required_runner_calls.items():
        method = runner_methods.get(method_name)
        if method is None:
            raise FieldFateStructureVerificationError(
                "independent live lossless runner binding method is absent"
            )
        observed_calls = {
            (
                call.func.id
                if isinstance(call.func, ast.Name)
                else call.func.attr
                if isinstance(call.func, ast.Attribute)
                else ""
            )
            for call in ast.walk(method)
            if isinstance(call, ast.Call)
        }
        if not required_calls <= observed_calls:
            raise FieldFateStructureVerificationError(
                "independent live lossless runner binding calls are incomplete"
            )

    staging_classes = [
        node
        for node in parsed["src/nbadb/orchestrate/staging_batches.py"][1].body
        if isinstance(node, ast.ClassDef) and node.name == "StagingBatchStore"
    ]
    if len(staging_classes) != 1:
        raise FieldFateStructureVerificationError(
            "independent live lossless staging store authority is ambiguous"
        )
    persist_methods = [
        node
        for node in staging_classes[0].body
        if isinstance(node, ast.FunctionDef) and node.name == "persist_frame_batches"
    ]
    if len(persist_methods) != 1:
        raise FieldFateStructureVerificationError(
            "independent live lossless persistence method is ambiguous"
        )
    persist_calls = {
        (
            call.func.id
            if isinstance(call.func, ast.Name)
            else call.func.attr
            if isinstance(call.func, ast.Attribute)
            else ""
        )
        for call in ast.walk(persist_methods[0])
        if isinstance(call, ast.Call)
    }
    if not {"_validate_persisted_live_lossless", "_persist_frame_batch_list", "execute"} <= (
        persist_calls
    ):
        raise FieldFateStructureVerificationError(
            "independent live lossless transactional persistence calls are incomplete"
        )
    authority = {
        "schema_version": 1,
        "kind": "receipt_bound_live_lossless_sink_authority",
        "staging_key": _LIVE_LOSSLESS_STAGING_KEY,
        "schema_columns": columns,
        "source_files": [
            {
                "path": relative,
                "sha256": hashlib.sha256(parsed[relative][0]).hexdigest(),
            }
            for relative in paths
        ],
        "guarantees": [
            "complete_decoded_payload_node_projection",
            "endpoint_contract_and_provider_authority_binding",
            "explicit_missing_null_empty_and_present_states",
            "logical_request_and_response_receipt_binding",
            "typed_conditional_route_admission",
            "typed_staging_persistence_and_replay_validation",
        ],
        "verified_call_edges": [
            "ExtractorRunner._admit_conditional_result_routes->_conditional_route_admission",
            "ExtractorRunner._finalize_logical_call_receipt->record_logical_call",
            "ExtractorRunner._verified_live_lossless_landings->validate_live_lossless_frame",
            "ExtractorRunner._verify_live_lossless_request_scope->admit_conditional_live_lossless_route",
            "StagingBatchStore.persist_frame_batches->_persist_frame_batch_list",
            "StagingBatchStore.persist_frame_batches->_validate_persisted_live_lossless",
        ],
    }
    return _digest(authority)


def _expected_lossless_binding_rows(
    source_rows: dict[str, dict[str, object]],
    expansion_rows: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    sink_authority = _independent_live_lossless_sink_authority()
    contracts = pinned_live_contracts()
    bindings: dict[str, dict[str, object]] = {}
    for occurrence_id, expansion in sorted(expansion_rows.items()):
        if expansion["status"] != "unrouted":
            continue
        source = source_rows[occurrence_id]
        if source["source_family"] != "live":
            raise FieldFateStructureVerificationError(
                "independent wide-unrouted source is outside live lossless scope"
            )
        endpoint_id = cast("str", source["endpoint_id"])
        result_ordinal = cast("int", source["result_set_ordinal"])
        field_ordinal = cast("int", source["field_ordinal"])
        contract = contracts.get(endpoint_id)
        result_sets = (
            ()
            if contract is None
            else tuple(item for item in contract.result_sets if item.ordinal == result_ordinal)
        )
        if len(result_sets) != 1:
            raise FieldFateStructureVerificationError(
                "independent lossless result-set authority is ambiguous"
            )
        result_set = result_sets[0]
        fields = tuple(item for item in result_set.fields if item.ordinal == field_ordinal)
        if (
            len(fields) != 1
            or fields[0].name != source["provider_field_name"]
            or fields[0].json_path != source["source_path"]
        ):
            raise FieldFateStructureVerificationError(
                "independent lossless field differs from typed live authority"
            )
        common = {
            "contract_json_path",
            "endpoint_contract_sha256",
            "endpoint_id",
            "provider_authority_sha256",
            "request_parameters_json",
            "response_receipt_sha256",
            "result_set_ordinal",
            "snapshot_at",
        }
        if source["direct_source_field"] is True:
            strategy = "object_contract_field"
            selectors = common | {
                "canonical_json",
                "contract_field_ordinal",
                "object_key",
                "presence_kind",
                "value_kind",
            }
        else:
            if len(result_set.fields) != 1 or source["provider_field_name"] != "value":
                raise FieldFateStructureVerificationError(
                    "independent scalar result-set selector is ambiguous"
                )
            strategy = "scalar_result_set_item"
            selectors = common | {
                "array_ordinal",
                "canonical_json",
                "presence_kind",
                "value_kind",
            }
        selector_columns = sorted(selectors)
        binding_id = f"lossless_field_binding:{occurrence_id}"
        body = {
            "schema_version": 1,
            "kind": "receipt_bound_live_lossless_field_binding",
            "binding_id": binding_id,
            "source_occurrence_id": occurrence_id,
            "source_occurrence_sha256": _digest(source),
            "staging_key": _LIVE_LOSSLESS_STAGING_KEY,
            "endpoint_id": endpoint_id,
            "result_set_name": source["result_set_name"],
            "result_set_ordinal": result_ordinal,
            "field_ordinal": field_ordinal,
            "provider_field_name": source["provider_field_name"],
            "contract_result_set_json_path": result_set.json_path,
            "contract_field_json_path": source["source_path"],
            "binding_strategy": strategy,
            "selector_columns": selector_columns,
            "sink_authority_sha256": sink_authority,
        }
        bindings[binding_id] = {
            "binding_id": binding_id,
            "source_occurrence_id": occurrence_id,
            "source_occurrence_sha256": _digest(source),
            "staging_key": _LIVE_LOSSLESS_STAGING_KEY,
            "endpoint_id": endpoint_id,
            "result_set_name": source["result_set_name"],
            "result_set_ordinal": result_ordinal,
            "field_ordinal": field_ordinal,
            "provider_field_name": source["provider_field_name"],
            "contract_result_set_json_path": result_set.json_path,
            "contract_field_json_path": source["source_path"],
            "binding_strategy": strategy,
            "selector_columns": selector_columns,
            "sink_authority_sha256": sink_authority,
            "binding_evidence_sha256": _digest(body),
        }
    return bindings


def _expected_blocker_rows(
    source_rows: dict[str, dict[str, object]],
    expansion_rows: dict[str, dict[str, object]],
    staging_route_contract_sha256: str,
    lossless_binding_rows: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    blockers: dict[str, dict[str, object]] = {}
    for occurrence_id, source in sorted(source_rows.items()):
        if source["provenance_kind"] != "unverified_live_docs_field":
            continue
        source_sha = _digest(source)
        blocker_id = f"field_fate_blocker:source_authority_unavailable:{occurrence_id}"
        evidence_sha = _digest(
            {
                "schema_version": 1,
                "kind": "source_authority_unavailable",
                "source_occurrence_id": occurrence_id,
                "source_occurrence_sha256": source_sha,
                "expected_authority_atom_id": source["authority_atom_id"],
                "expected_authority_atom_sha256": source["authority_atom_sha256"],
            }
        )
        blockers[blocker_id] = {
            "blocker_id": blocker_id,
            "blocker_kind": "source_authority_unavailable",
            "source_occurrence_id": occurrence_id,
            "source_occurrence_sha256": source_sha,
            "evidence_sha256": evidence_sha,
            "resolution_requirement": _SOURCE_AUTHORITY_REQUIREMENT,
            "status": "open",
        }
    lossless_bound_sources = {
        cast("str", row["source_occurrence_id"]) for row in lossless_binding_rows.values()
    }
    for occurrence_id, expansion in sorted(expansion_rows.items()):
        if expansion["status"] != "unrouted":
            continue
        if occurrence_id in lossless_bound_sources:
            continue
        source = source_rows[occurrence_id]
        source_sha = _digest(source)
        blocker_id = f"field_fate_blocker:lossless_storage_binding_unresolved:{occurrence_id}"
        evidence_sha = _digest(
            {
                "schema_version": 1,
                "kind": "lossless_storage_binding_unresolved",
                "source_occurrence_id": occurrence_id,
                "source_occurrence_sha256": source_sha,
                "source_route_expansion": expansion,
                "staging_route_contract_sha256": staging_route_contract_sha256,
                "binding_state": "no_executable_route_or_storage_sink",
            }
        )
        blockers[blocker_id] = {
            "blocker_id": blocker_id,
            "blocker_kind": "lossless_storage_binding_unresolved",
            "source_occurrence_id": occurrence_id,
            "source_occurrence_sha256": source_sha,
            "evidence_sha256": evidence_sha,
            "resolution_requirement": _LOSSLESS_BINDING_REQUIREMENT,
            "status": "open",
        }
    return blockers


@lru_cache(maxsize=4)
def _expected_current_rows(
    root_key: str | None,
) -> tuple[
    dict[str, dict[str, object]],
    IndependentPackageInventory,
    str,
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    StagingRouteContractBundle,
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
    dict[str, dict[str, object]],
]:
    """Reconstruct one immutable current-authority generation for readback joins."""

    sources, package_inventory, payload_sha256 = _expected_source_rows(root_key)
    bindings, expansions, routes = _expected_route_rows(sources)
    sinks = _expected_sink_rows(bindings, routes)
    lossless_bindings = _expected_lossless_binding_rows(sources, expansions)
    blockers = _expected_blocker_rows(
        sources,
        expansions,
        routes.digest,
        lossless_bindings,
    )
    return (
        sources,
        package_inventory,
        payload_sha256,
        bindings,
        expansions,
        routes,
        sinks,
        lossless_bindings,
        blockers,
    )


def verify_field_fate_structure_independently(
    structure: FieldFateStructureV1,
    upstream_root: Path | str | None = None,
) -> FieldFateStructureVerificationV1:
    """Rebuild every structural row and return a positive readback receipt."""

    if type(structure) is not FieldFateStructureV1:
        raise FieldFateStructureVerificationError("structure has a foreign concrete type")
    _verify_production_request_scope_policy()
    root_key = _root_key(upstream_root)
    (
        expected_sources,
        package_inventory,
        payload_sha256,
        expected_bindings,
        expected_expansions,
        routes,
        expected_sinks,
        expected_lossless_bindings,
        expected_blockers,
    ) = _expected_current_rows(root_key)
    actual_sources = {
        item.occurrence_id: item.to_dict() for item in structure.provider_sources.occurrences
    }
    if actual_sources != expected_sources:
        raise FieldFateStructureVerificationError(
            "provider source occurrences differ from independent reconstruction"
        )
    if (
        structure.provider_sources.independent_package_inventory_sha256
        != package_inventory.inventory_sha256
        or structure.provider_sources.independent_source_atoms_sha256
        != package_inventory.source_atoms_sha256
        or structure.provider_sources.pinned_runtime_contract_payload_sha256 != payload_sha256
        or structure.provider_sources.live_docs_field_evidence_sha256
        != _evidence_inventory_digest(
            expected_sources,
            {"upstream_live_docs_field", "unverified_live_docs_field"},
        )
        or structure.provider_sources.live_nested_scalar_evidence_sha256
        != _evidence_inventory_digest(
            expected_sources,
            {"installed_live_nested_scalar_projection"},
        )
        or structure.provider_sources.static_field_evidence_sha256
        != _evidence_inventory_digest(
            expected_sources,
            {"installed_static_field_projection"},
        )
    ):
        raise FieldFateStructureVerificationError("provider source authority digest is stale")

    actual_bindings = {
        item.binding_id: item.to_dict() for item in structure.route_bindings.bindings
    }
    actual_expansions = {
        item.source_occurrence_id: item.to_dict()
        for item in structure.route_bindings.source_expansions
    }
    if actual_bindings != expected_bindings:
        raise FieldFateStructureVerificationError(
            "route bindings differ from independent reconstruction"
        )
    if actual_expansions != expected_expansions:
        raise FieldFateStructureVerificationError(
            "source route expansions omit, overlap, or differ from exact aliases"
        )
    if structure.route_bindings.staging_route_contract_sha256 != routes.digest:
        raise FieldFateStructureVerificationError("route binding authority digest is stale")

    actual_sinks = {item.sink_id: item.to_dict() for item in structure.storage_sinks.sinks}
    if actual_sinks != expected_sinks:
        raise FieldFateStructureVerificationError(
            "storage sinks differ from independent reconstruction"
        )
    actual_lossless_bindings = {
        item.binding_id: item.to_dict() for item in structure.lossless_bindings
    }
    if actual_lossless_bindings != expected_lossless_bindings:
        raise FieldFateStructureVerificationError(
            "lossless field bindings differ from independent reconstruction"
        )
    actual_blockers = {item.blocker_id: item.to_dict() for item in structure.blockers}
    if actual_blockers != expected_blockers:
        raise FieldFateStructureVerificationError(
            "field-level open blockers differ from independent reconstruction"
        )

    source_statuses = Counter(row["status"] for row in expected_expansions.values())
    sink_statuses = Counter(row["status"] for row in expected_sinks.values())
    blocker_statuses = Counter(row["blocker_kind"] for row in expected_blockers.values())
    if (
        sum(source_statuses.values()) != len(expected_sources)
        or sum(sink_statuses.values()) != len(expected_sinks)
        or blocker_statuses["lossless_storage_binding_unresolved"] + len(expected_lossless_bindings)
        != source_statuses["unrouted"]
        or sum(blocker_statuses.values()) != len(expected_blockers)
    ):
        raise FieldFateStructureVerificationError("joined structural denominator drifted")

    return FieldFateStructureVerificationV1(
        structure_sha256=structure.identity_sha256,
        provider_sources_sha256=structure.provider_sources.identity_sha256,
        route_bindings_sha256=structure.route_bindings.identity_sha256,
        storage_sinks_sha256=structure.storage_sinks.identity_sha256,
        lossless_bindings_sha256=_digest(
            [expected_lossless_bindings[key] for key in sorted(expected_lossless_bindings)]
        ),
        blockers_sha256=_digest([expected_blockers[key] for key in sorted(expected_blockers)]),
        independent_package_inventory_sha256=package_inventory.inventory_sha256,
        independent_source_atoms_sha256=package_inventory.source_atoms_sha256,
        staging_route_contract_sha256=routes.digest,
        provider_source_occurrence_count=len(expected_sources),
        route_binding_count=len(expected_bindings),
        routed_source_occurrence_count=(len(expected_expansions) - source_statuses["unrouted"]),
        unrouted_source_occurrence_count=source_statuses["unrouted"],
        lossless_field_binding_count=len(expected_lossless_bindings),
        storage_sink_count=len(expected_sinks),
        provider_bound_storage_sink_count=sink_statuses["provider_bound"],
        storage_only_sink_count=sink_statuses["storage_only"],
        source_authority_blocker_count=blocker_statuses["source_authority_unavailable"],
        unresolved_lossless_binding_count=blocker_statuses["lossless_storage_binding_unresolved"],
        open_blocker_count=len(expected_blockers),
        authority_mode=("exact_checkout" if root_key is not None else "blocked_missing_checkout"),
        wide_route_complete=source_statuses["unrouted"] == 0,
        lossless_field_binding_complete=(
            blocker_statuses["lossless_storage_binding_unresolved"] == 0
        ),
        verified_against_current_authorities=True,
        shared_authority_boundaries=_SHARED_AUTHORITY_BOUNDARIES,
        checks=_EXACT_CHECKS,
    )


def verify_field_fate_structure(
    structure: FieldFateStructureV1,
    upstream_root: Path | str | None = None,
) -> FieldFateStructureVerificationV1:
    """Public concise alias for independent structural verification."""

    return verify_field_fate_structure_independently(structure, upstream_root)


def canonical_verification_bytes(receipt: FieldFateStructureVerificationV1) -> bytes:
    """Serialize one typed receipt to its sole accepted canonical JSON representation."""

    if type(receipt) is not FieldFateStructureVerificationV1:
        raise FieldFateStructureVerificationError("verification receipt has a foreign type")
    return _canonical_bytes(receipt.to_dict()) + b"\n"


def _reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise FieldFateStructureVerificationError(
                f"verification receipt repeats object key: {key}"
            )
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> object:
    raise FieldFateStructureVerificationError(
        f"verification receipt contains non-finite JSON value: {value}"
    )


def _exact_object(
    value: object,
    expected_keys: set[str],
    field_name: str,
) -> dict[str, object]:
    if type(value) is not dict or set(value) != expected_keys:
        raise FieldFateStructureVerificationError(
            f"verification receipt {field_name} schema is not exact"
        )
    return cast("dict[str, object]", value)


def _string_tuple(value: object, field_name: str) -> tuple[str, ...]:
    if type(value) is not list or any(type(item) is not str for item in value):
        raise FieldFateStructureVerificationError(
            f"verification receipt {field_name} must be an exact string array"
        )
    return tuple(cast("list[str]", value))


def parse_field_fate_structure_verification(
    raw: bytes,
) -> FieldFateStructureVerificationV1:
    """Parse only canonical, duplicate-free schema-v3 verification receipt bytes."""

    if type(raw) is not bytes:
        raise FieldFateStructureVerificationError("verification receipt bytes are not exact")
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_nonfinite,
        )
    except FieldFateStructureVerificationError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise FieldFateStructureVerificationError("verification receipt JSON is invalid") from exc
    payload = _exact_object(
        value,
        {
            "schema_version",
            "kind",
            "structure_sha256",
            "provider_sources_sha256",
            "route_bindings_sha256",
            "storage_sinks_sha256",
            "lossless_bindings_sha256",
            "blockers_sha256",
            "independent_package_inventory_sha256",
            "independent_source_atoms_sha256",
            "staging_route_contract_sha256",
            "authority_mode",
            "summary",
            "shared_authority_boundaries",
            "checks",
        },
        "top-level",
    )
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 3:
        raise FieldFateStructureVerificationError(
            "verification receipt schema_version is not exact"
        )
    if payload["kind"] != FieldFateStructureVerificationV1.kind:
        raise FieldFateStructureVerificationError("verification receipt kind is not exact")
    summary = _exact_object(
        payload["summary"],
        {
            "provider_source_occurrence_count",
            "route_binding_count",
            "routed_source_occurrence_count",
            "unrouted_source_occurrence_count",
            "lossless_field_binding_count",
            "storage_sink_count",
            "provider_bound_storage_sink_count",
            "storage_only_sink_count",
            "source_authority_blocker_count",
            "unresolved_lossless_binding_count",
            "open_blocker_count",
            "wide_route_complete",
            "lossless_field_binding_complete",
            "verified_against_current_authorities",
            "model_green",
        },
        "summary",
    )
    if summary["model_green"] != "not_evaluated_by_structural_verifier":
        raise FieldFateStructureVerificationError("verification receipt model status is not exact")
    receipt = FieldFateStructureVerificationV1(
        structure_sha256=cast("str", payload["structure_sha256"]),
        provider_sources_sha256=cast("str", payload["provider_sources_sha256"]),
        route_bindings_sha256=cast("str", payload["route_bindings_sha256"]),
        storage_sinks_sha256=cast("str", payload["storage_sinks_sha256"]),
        lossless_bindings_sha256=cast("str", payload["lossless_bindings_sha256"]),
        blockers_sha256=cast("str", payload["blockers_sha256"]),
        independent_package_inventory_sha256=cast(
            "str", payload["independent_package_inventory_sha256"]
        ),
        independent_source_atoms_sha256=cast("str", payload["independent_source_atoms_sha256"]),
        staging_route_contract_sha256=cast("str", payload["staging_route_contract_sha256"]),
        provider_source_occurrence_count=cast("int", summary["provider_source_occurrence_count"]),
        route_binding_count=cast("int", summary["route_binding_count"]),
        routed_source_occurrence_count=cast("int", summary["routed_source_occurrence_count"]),
        unrouted_source_occurrence_count=cast("int", summary["unrouted_source_occurrence_count"]),
        lossless_field_binding_count=cast("int", summary["lossless_field_binding_count"]),
        storage_sink_count=cast("int", summary["storage_sink_count"]),
        provider_bound_storage_sink_count=cast("int", summary["provider_bound_storage_sink_count"]),
        storage_only_sink_count=cast("int", summary["storage_only_sink_count"]),
        source_authority_blocker_count=cast("int", summary["source_authority_blocker_count"]),
        unresolved_lossless_binding_count=cast("int", summary["unresolved_lossless_binding_count"]),
        open_blocker_count=cast("int", summary["open_blocker_count"]),
        authority_mode=cast("str", payload["authority_mode"]),
        wide_route_complete=cast("bool", summary["wide_route_complete"]),
        lossless_field_binding_complete=cast("bool", summary["lossless_field_binding_complete"]),
        verified_against_current_authorities=cast(
            "bool", summary["verified_against_current_authorities"]
        ),
        shared_authority_boundaries=_string_tuple(
            payload["shared_authority_boundaries"], "shared_authority_boundaries"
        ),
        checks=_string_tuple(payload["checks"], "checks"),
    )
    if canonical_verification_bytes(receipt) != raw:
        raise FieldFateStructureVerificationError("verification receipt bytes are not canonical")
    return receipt


def validate_field_fate_structure_verification(
    receipt: FieldFateStructureVerificationV1,
    structure: FieldFateStructureV1,
    upstream_root: Path | str | None = None,
) -> None:
    """Recompute current authorities and reject any forged, rebound, or stale receipt."""

    if type(receipt) is not FieldFateStructureVerificationV1:
        raise FieldFateStructureVerificationError("verification receipt has a foreign type")
    expected = verify_field_fate_structure_independently(structure, upstream_root)
    if receipt.receipt_sha256 != expected.receipt_sha256 or receipt != expected:
        raise FieldFateStructureVerificationError(
            "verification receipt differs from exact current-authority recomputation"
        )
