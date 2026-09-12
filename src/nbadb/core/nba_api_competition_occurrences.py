"""Checked authority for every NBA API competition-parameter occurrence.

The primary path deliberately uses runtime reflection for the installed
``nba-api==1.11.4`` endpoint classes and bytecode/global identity for nbadb's
registered extractors.  The companion verifier reconstructs both inventories
from source ASTs instead.  Neither path sends a provider request.
"""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import inspect
import json
import re
import types
import warnings
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from importlib import resources
from pathlib import Path
from typing import TYPE_CHECKING, Final, cast

import nba_api.stats.endpoints as provider_endpoints
from nba_api.stats.endpoints._base import Endpoint

from nbadb.core.nba_api_surface_inventory import (
    NBA_API_DISTRIBUTION,
    NBA_API_VERSION,
    NbaApiSurfaceInventoryError,
    build_distribution_record_authority,
)
from nbadb.extract.registry import registry

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from importlib.metadata import Distribution

    from nbadb.extract.base import BaseExtractor

COMPETITION_OCCURRENCE_SCHEMA_VERSION: Final = 1
COMPETITION_OCCURRENCE_RESOURCE: Final = "nba_api_competition_occurrences_v1_11_4.json"
REQUEST_SURFACE_RESOURCE: Final = "nba_api_request_surface_v1_11_4.json"

_COMPETITION_NAMES: Final = frozenset(
    {
        "league_id",
        "league_id_nullable",
        "person1_league_id",
        "person2_league_id",
    }
)
_TRANSPORT_NAMES: Final = frozenset({"get_request", "headers", "proxy", "timeout"})
_PRIMARY_NAMES: Final = frozenset({"league_id", "league_id_nullable"})
_PARTICIPANT_NAMES: Final = frozenset({"person1_league_id", "person2_league_id"})
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
_PLANNING_ROLE_FIELDS: Final = (
    "name",
    "query_name",
    "nullable",
    "has_default",
    "default",
    "semantic_role",
)
_SHA256_RE = re.compile(r"[0-9a-f]{64}", flags=re.ASCII)


class NbaApiCompetitionOccurrenceError(ValueError):
    """The package/repository competition occurrence authority is invalid."""


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
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence authority is not canonical JSON"
        ) from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _planning_digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value) + b"\n").hexdigest()


def _require_digest(value: object, field: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise NbaApiCompetitionOccurrenceError(f"{field} must be a canonical SHA-256")
    return value


def _object_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise NbaApiCompetitionOccurrenceError(
                f"competition occurrence resource contains duplicate object key: {key}"
            )
        result[key] = value
    return result


def _reject_constant(value: str) -> object:
    raise NbaApiCompetitionOccurrenceError(
        f"competition occurrence resource contains non-finite JSON constant: {value}"
    )


def _forwarding_behavior(name: str) -> str:
    if name in _PRIMARY_NAMES:
        return "semantic_primary_league_alias_forwarding"
    if name in _PARTICIPANT_NAMES:
        return "exact_constructor_name_forwarding"
    raise NbaApiCompetitionOccurrenceError("unknown competition constructor role")


def _output_behavior(name: str) -> str:
    if name in _PRIMARY_NAMES:
        return "inject_primary_league_id_when_provider_rows_omit_it"
    if name in _PARTICIPANT_NAMES:
        return "participant_role_only_no_primary_league_id_injection"
    raise NbaApiCompetitionOccurrenceError("unknown competition constructor role")


@dataclass(frozen=True, slots=True, order=True)
class PackageCompetitionOccurrence:
    """One exact competition constructor occurrence in the installed package."""

    occurrence_id: str
    provider_endpoint_id: str
    provider_module: str
    provider_source_path: str
    provider_source_sha256: str
    provider_source_size: int
    ordinal: int
    constructor_name: str
    wire_name: str
    nullable: bool
    has_default: bool
    default: str
    default_expression: str
    semantic_role: str
    request_surface_source_signature_sha256: str
    request_surface_typed_domain_sha256: str

    def __post_init__(self) -> None:
        if (
            not self.occurrence_id
            or not self.provider_endpoint_id
            or not self.provider_module.startswith("nba_api.stats.endpoints.")
            or not self.provider_source_path.startswith("nba_api/stats/endpoints/")
            or self.constructor_name not in _COMPETITION_NAMES
            or self.wire_name != _WIRE_NAMES[self.constructor_name]
            or self.default_expression != _DEFAULT_EXPRESSIONS[self.constructor_name]
            or self.semantic_role != "scope_axis"
            or type(self.nullable) is not bool
            or self.nullable != (self.constructor_name == "league_id_nullable")
            or self.has_default is not True
            or not isinstance(self.default, str)
            or isinstance(self.ordinal, bool)
            or not isinstance(self.ordinal, int)
            or self.ordinal < 0
            or isinstance(self.provider_source_size, bool)
            or not isinstance(self.provider_source_size, int)
            or self.provider_source_size <= 0
        ):
            raise NbaApiCompetitionOccurrenceError(
                "package competition occurrence classification is invalid"
            )
        _require_digest(self.provider_source_sha256, "provider_source_sha256")
        _require_digest(
            self.request_surface_source_signature_sha256,
            "request_surface_source_signature_sha256",
        )
        _require_digest(
            self.request_surface_typed_domain_sha256,
            "request_surface_typed_domain_sha256",
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "constructor_name": self.constructor_name,
            "default": self.default,
            "default_expression": self.default_expression,
            "has_default": self.has_default,
            "nullable": self.nullable,
            "occurrence_id": self.occurrence_id,
            "ordinal": self.ordinal,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_module": self.provider_module,
            "provider_source_path": self.provider_source_path,
            "provider_source_sha256": self.provider_source_sha256,
            "provider_source_size": self.provider_source_size,
            "request_surface_source_signature_sha256": (
                self.request_surface_source_signature_sha256
            ),
            "request_surface_typed_domain_sha256": (self.request_surface_typed_domain_sha256),
            "semantic_role": self.semantic_role,
            "wire_name": self.wire_name,
        }

    def planning_role_dict(self) -> dict[str, object]:
        return {
            "default": self.default,
            "has_default": self.has_default,
            "name": self.constructor_name,
            "nullable": self.nullable,
            "query_name": self.wire_name,
            "semantic_role": self.semantic_role,
        }


@dataclass(frozen=True, slots=True, order=True)
class ProjectedCompetitionRole:
    """One provider occurrence projected through one registered extractor alias."""

    provider_endpoint_id: str
    provider_occurrence_id: str
    constructor_name: str
    wire_name: str
    nullable: bool
    has_default: bool
    default: str
    semantic_role: str
    forwarding_behavior: str
    output_behavior: str

    def __post_init__(self) -> None:
        if (
            not self.provider_endpoint_id
            or not self.provider_occurrence_id
            or self.constructor_name not in _COMPETITION_NAMES
            or self.wire_name != _WIRE_NAMES[self.constructor_name]
            or self.nullable != (self.constructor_name == "league_id_nullable")
            or self.has_default is not True
            or not isinstance(self.default, str)
            or self.semantic_role != "scope_axis"
            or self.forwarding_behavior != _forwarding_behavior(self.constructor_name)
            or self.output_behavior != _output_behavior(self.constructor_name)
        ):
            raise NbaApiCompetitionOccurrenceError(
                "projected competition role classification is invalid"
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "constructor_name": self.constructor_name,
            "default": self.default,
            "forwarding_behavior": self.forwarding_behavior,
            "has_default": self.has_default,
            "nullable": self.nullable,
            "output_behavior": self.output_behavior,
            "provider_endpoint_id": self.provider_endpoint_id,
            "provider_occurrence_id": self.provider_occurrence_id,
            "semantic_role": self.semantic_role,
            "wire_name": self.wire_name,
        }

    def planning_dict(self) -> dict[str, object]:
        return {
            "default": self.default,
            "has_default": self.has_default,
            "name": self.constructor_name,
            "nullable": self.nullable,
            "query_name": self.wire_name,
            "semantic_role": self.semantic_role,
        }


@dataclass(frozen=True, slots=True, order=True)
class ExtractorCompetitionAlias:
    """One exact registered nbadb endpoint name and its provider role projection."""

    repo_endpoint_name: str
    extractor_module: str
    extractor_qualname: str
    source_path: str
    source_sha256: str
    source_size: int
    provider_endpoint_ids: tuple[str, ...]
    provider_occurrence_ids: tuple[str, ...]
    parameter_roles: tuple[ProjectedCompetitionRole, ...]

    def __post_init__(self) -> None:
        if (
            not self.repo_endpoint_name
            or not self.extractor_module.startswith("nbadb.extract.stats.")
            or not self.extractor_qualname
            or not self.source_path.startswith("src/nbadb/extract/stats/")
            or isinstance(self.source_size, bool)
            or not isinstance(self.source_size, int)
            or self.source_size <= 0
            or not self.provider_endpoint_ids
            or self.provider_endpoint_ids != tuple(sorted(set(self.provider_endpoint_ids)))
            or not self.provider_occurrence_ids
            or self.provider_occurrence_ids != tuple(sorted(set(self.provider_occurrence_ids)))
            or not self.parameter_roles
            or self.parameter_roles
            != tuple(
                sorted(
                    self.parameter_roles,
                    key=lambda item: (item.constructor_name, item.wire_name),
                )
            )
        ):
            raise NbaApiCompetitionOccurrenceError(
                "registered extractor competition alias is invalid"
            )
        _require_digest(self.source_sha256, "extractor_source_sha256")

    def to_dict(self) -> dict[str, object]:
        return {
            "extractor_module": self.extractor_module,
            "extractor_qualname": self.extractor_qualname,
            "parameter_roles": [item.to_dict() for item in self.parameter_roles],
            "provider_endpoint_ids": list(self.provider_endpoint_ids),
            "provider_occurrence_ids": list(self.provider_occurrence_ids),
            "repo_endpoint_name": self.repo_endpoint_name,
            "source_path": self.source_path,
            "source_sha256": self.source_sha256,
            "source_size": self.source_size,
        }

    def planning_dict(self) -> dict[str, object]:
        return {
            "parameter_roles": [item.planning_dict() for item in self.parameter_roles],
            "provider_endpoint_ids": list(self.provider_endpoint_ids),
            "provider_occurrence_ids": list(self.provider_occurrence_ids),
            "repo_endpoint_name": self.repo_endpoint_name,
        }


@dataclass(frozen=True, slots=True, order=True)
class RepoSourceBinding:
    """One complete repository source file contributing projected aliases."""

    path: str
    sha256: str
    size: int

    def __post_init__(self) -> None:
        if (
            not self.path.startswith("src/nbadb/extract/stats/")
            or isinstance(self.size, bool)
            or not isinstance(self.size, int)
            or self.size <= 0
        ):
            raise NbaApiCompetitionOccurrenceError("competition alias source binding is invalid")
        _require_digest(self.sha256, "repo_source_sha256")

    def to_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


@dataclass(frozen=True, slots=True)
class CompetitionOccurrenceAuthority:
    """Complete package occurrence and registered extractor-alias authority."""

    distribution_record_authority_sha256: str
    request_surface_resource_sha256: str
    request_surface_payload_sha256: str
    request_surface_sha256: str
    package_planning_census_sha256: str
    package_occurrences: tuple[PackageCompetitionOccurrence, ...]
    repo_alias_planning_census_sha256: str
    repo_aliases: tuple[ExtractorCompetitionAlias, ...]
    repo_source_inventory: tuple[RepoSourceBinding, ...]

    def __post_init__(self) -> None:
        for field, value in (
            (
                "distribution_record_authority_sha256",
                self.distribution_record_authority_sha256,
            ),
            ("request_surface_resource_sha256", self.request_surface_resource_sha256),
            ("request_surface_payload_sha256", self.request_surface_payload_sha256),
            ("request_surface_sha256", self.request_surface_sha256),
            ("package_planning_census_sha256", self.package_planning_census_sha256),
            ("repo_alias_planning_census_sha256", self.repo_alias_planning_census_sha256),
        ):
            _require_digest(value, field)
        if (
            not self.package_occurrences
            or self.package_occurrences
            != tuple(sorted(self.package_occurrences, key=lambda item: item.occurrence_id))
            or len({item.occurrence_id for item in self.package_occurrences})
            != len(self.package_occurrences)
            or not self.repo_aliases
            or self.repo_aliases
            != tuple(sorted(self.repo_aliases, key=lambda item: item.repo_endpoint_name))
            or len({item.repo_endpoint_name for item in self.repo_aliases})
            != len(self.repo_aliases)
            or not self.repo_source_inventory
            or self.repo_source_inventory
            != tuple(sorted(self.repo_source_inventory, key=lambda item: item.path))
            or len({item.path for item in self.repo_source_inventory})
            != len(self.repo_source_inventory)
        ):
            raise NbaApiCompetitionOccurrenceError(
                "competition occurrence inventories must be sorted, unique, and nonempty"
            )
        occurrences = {item.occurrence_id: item for item in self.package_occurrences}
        sources = {item.path: item for item in self.repo_source_inventory}
        for alias in self.repo_aliases:
            try:
                registered = registry.get(alias.repo_endpoint_name)
            except KeyError as exc:
                raise NbaApiCompetitionOccurrenceError(
                    "competition alias is not registered"
                ) from exc
            if (
                registered.__module__ != alias.extractor_module
                or registered.__qualname__ != alias.extractor_qualname
            ):
                raise NbaApiCompetitionOccurrenceError(
                    "competition alias differs from its registered extractor identity"
                )
            if alias.source_path not in sources:
                raise NbaApiCompetitionOccurrenceError(
                    "registered extractor alias is absent from the source inventory"
                )
            if sources[alias.source_path].sha256 != alias.source_sha256:
                raise NbaApiCompetitionOccurrenceError(
                    "registered extractor alias source digest is inconsistent"
                )
            if any(item not in occurrences for item in alias.provider_occurrence_ids):
                raise NbaApiCompetitionOccurrenceError(
                    "registered extractor alias references an unmapped package occurrence"
                )
            role_occurrences = tuple(
                sorted(role.provider_occurrence_id for role in alias.parameter_roles)
            )
            if role_occurrences != alias.provider_occurrence_ids:
                raise NbaApiCompetitionOccurrenceError(
                    "registered extractor alias does not conserve provider role occurrences"
                )
            if (
                tuple(sorted({role.provider_endpoint_id for role in alias.parameter_roles}))
                != alias.provider_endpoint_ids
            ):
                raise NbaApiCompetitionOccurrenceError(
                    "registered extractor alias does not conserve provider endpoints"
                )

    @property
    def package_endpoint_count(self) -> int:
        return len({item.provider_endpoint_id for item in self.package_occurrences})

    @property
    def projected_role_count(self) -> int:
        return sum(len(item.parameter_roles) for item in self.repo_aliases)

    @property
    def package_occurrences_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.package_occurrences])

    @property
    def repo_aliases_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.repo_aliases])

    @property
    def repo_source_bindings_sha256(self) -> str:
        return _digest([item.to_dict() for item in self.repo_source_inventory])

    @property
    def repo_source_inventory_sha256(self) -> str:
        aliases_by_path: dict[str, list[str]] = {}
        for alias in self.repo_aliases:
            aliases_by_path.setdefault(alias.source_path, []).append(alias.repo_endpoint_name)
        rows = [
            {
                "alias_count": len(aliases_by_path[source.path]),
                "aliases": sorted(aliases_by_path[source.path]),
                "path": source.path,
                "sha256": source.sha256,
            }
            for source in self.repo_source_inventory
        ]
        return _planning_digest(rows)

    @property
    def authority_sha256(self) -> str:
        return _digest(_authority_payload(self))


def _load_json_resource(resource: str) -> tuple[bytes, dict[str, object]]:
    try:
        raw = resources.files("nbadb.contracts").joinpath(resource).read_bytes()
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionOccurrenceError(
            f"required checked resource cannot be read: {resource}"
        ) from exc
    try:
        value = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionOccurrenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionOccurrenceError(
            f"required checked resource cannot be decoded: {resource}"
        ) from exc
    if not isinstance(value, dict) or raw != _canonical_bytes(value) + b"\n":
        raise NbaApiCompetitionOccurrenceError(
            f"required checked resource is not canonical JSON: {resource}"
        )
    body = dict(value)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, "upstream payload_sha256") != _digest(body):
        raise NbaApiCompetitionOccurrenceError(
            f"required checked resource payload digest is invalid: {resource}"
        )
    return raw, cast("dict[str, object]", value)


def _request_surface_planning_rows() -> tuple[
    bytes,
    dict[str, object],
    tuple[dict[str, object], ...],
]:
    raw, payload = _load_json_resource(REQUEST_SURFACE_RESOURCE)
    occurrence_rows = payload.get("parameter_occurrences")
    if not isinstance(occurrence_rows, list):
        raise NbaApiCompetitionOccurrenceError(
            "request surface omits its parameter occurrence inventory"
        )
    projected: list[dict[str, object]] = []
    for raw_row in occurrence_rows:
        if not isinstance(raw_row, dict) or raw_row.get("domain_kind") != "league_scope":
            continue
        typed_row = cast("dict[str, object]", raw_row)
        if set(_PLANNING_FIELDS) - set(typed_row):
            raise NbaApiCompetitionOccurrenceError(
                "request-surface league occurrence is incomplete"
            )
        projected.append({field: typed_row[field] for field in _PLANNING_FIELDS})
    ids = tuple(str(row["occurrence_id"]) for row in projected)
    if not projected or ids != tuple(sorted(ids)) or len(ids) != len(set(ids)):
        raise NbaApiCompetitionOccurrenceError(
            "request-surface league occurrences are not sorted and unique"
        )
    return raw, payload, tuple(projected)


def _provider_classes() -> tuple[type[object], ...]:
    classes: dict[str, type[object]] = {}
    for module_name in provider_endpoints.__all__:
        module = getattr(provider_endpoints, module_name, None)
        if module is None:
            module = importlib.import_module(f"nba_api.stats.endpoints.{module_name}")
        if not isinstance(module, types.ModuleType):
            raise NbaApiCompetitionOccurrenceError("nba_api endpoint export is not a module")
        for _, candidate in inspect.getmembers(module, inspect.isclass):
            if (
                candidate.__module__ == module.__name__
                and issubclass(candidate, Endpoint)
                and candidate is not Endpoint
            ):
                if candidate.__name__ in classes and classes[candidate.__name__] is not candidate:
                    raise NbaApiCompetitionOccurrenceError(
                        "nba_api endpoint class name is ambiguous"
                    )
                classes[candidate.__name__] = candidate
    return tuple(classes[name] for name in sorted(classes))


def _wire_names_for_class(
    endpoint_cls: type[object],
    competition_names: tuple[str, ...],
) -> Mapping[str, str]:
    parameters = inspect.signature(endpoint_cls).parameters
    kwargs: dict[str, object] = {}
    sentinels = {
        name: f"__nbadb_competition_occurrence_{index}_{name}__"
        for index, name in enumerate(competition_names)
    }
    for parameter in parameters.values():
        if parameter.name in sentinels:
            kwargs[parameter.name] = sentinels[parameter.name]
        elif (
            parameter.name not in _TRANSPORT_NAMES
            and parameter.default is inspect.Parameter.empty
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        ):
            kwargs[parameter.name] = f"__nbadb_required_{parameter.name}__"
    if "get_request" not in parameters:
        raise NbaApiCompetitionOccurrenceError(
            "nba_api endpoint lacks the no-request constructor switch"
        )
    kwargs["get_request"] = False
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", DeprecationWarning)
            instance = endpoint_cls(**kwargs)
    except Exception as exc:
        raise NbaApiCompetitionOccurrenceError(
            "nba_api endpoint could not be inspected without a request"
        ) from exc
    wire_parameters = getattr(instance, "parameters", None)
    if not isinstance(wire_parameters, dict):
        raise NbaApiCompetitionOccurrenceError(
            "nba_api endpoint did not expose its wire parameter mapping"
        )
    result: dict[str, str] = {}
    for constructor_name, sentinel in sentinels.items():
        matches = tuple(
            key
            for key, value in wire_parameters.items()
            if isinstance(key, str) and value == sentinel
        )
        if len(matches) != 1:
            raise NbaApiCompetitionOccurrenceError(
                "nba_api competition constructor parameter has ambiguous wire mapping"
            )
        result[constructor_name] = matches[0]
    return result


def _distribution_and_record() -> tuple[Distribution, object]:
    try:
        distribution = importlib.metadata.distribution(NBA_API_DISTRIBUTION)
    except importlib.metadata.PackageNotFoundError as exc:
        raise NbaApiCompetitionOccurrenceError(
            "pinned nba_api distribution is not installed"
        ) from exc
    if distribution.version != NBA_API_VERSION:
        raise NbaApiCompetitionOccurrenceError(
            "installed nba_api version differs from the exact pin"
        )
    try:
        record = build_distribution_record_authority(distribution)
    except NbaApiSurfaceInventoryError as exc:
        raise NbaApiCompetitionOccurrenceError(
            "installed nba_api RECORD authority is invalid"
        ) from exc
    return distribution, record


def _derive_runtime_package_occurrences(
    distribution: Distribution,
    record: object,
    planning_rows: tuple[dict[str, object], ...],
) -> tuple[PackageCompetitionOccurrence, ...]:
    record_entries = getattr(record, "entries", None)
    if not isinstance(record_entries, tuple):
        raise NbaApiCompetitionOccurrenceError("installed RECORD entries are unavailable")
    entries = {entry.path: entry for entry in record_entries}
    planning = {(str(row["endpoint_id"]), str(row["name"])): row for row in planning_rows}
    distribution_root = Path(str(distribution.locate_file(""))).resolve(strict=True)
    rows: list[PackageCompetitionOccurrence] = []
    for endpoint_cls in _provider_classes():
        signature_parameters = tuple(inspect.signature(endpoint_cls).parameters.values())
        business_parameters = tuple(
            parameter
            for parameter in signature_parameters
            if parameter.name not in _TRANSPORT_NAMES
            and parameter.kind
            in {
                inspect.Parameter.POSITIONAL_ONLY,
                inspect.Parameter.POSITIONAL_OR_KEYWORD,
                inspect.Parameter.KEYWORD_ONLY,
            }
        )
        competition_parameters = tuple(
            parameter for parameter in business_parameters if parameter.name in _COMPETITION_NAMES
        )
        if not competition_parameters:
            continue
        wire_names = _wire_names_for_class(
            endpoint_cls,
            tuple(parameter.name for parameter in competition_parameters),
        )
        source_name = inspect.getsourcefile(endpoint_cls)
        if source_name is None:
            raise NbaApiCompetitionOccurrenceError("nba_api endpoint source path is unavailable")
        source_path = Path(source_name).resolve(strict=True)
        try:
            relative_source = source_path.relative_to(distribution_root).as_posix()
        except ValueError as exc:
            raise NbaApiCompetitionOccurrenceError(
                "nba_api endpoint source is not owned by its distribution"
            ) from exc
        entry = entries.get(relative_source)
        if entry is None:
            raise NbaApiCompetitionOccurrenceError("nba_api endpoint source is absent from RECORD")
        raw = source_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry.sha256 or len(raw) != entry.size:
            raise NbaApiCompetitionOccurrenceError(
                "nba_api endpoint source differs from its RECORD binding"
            )
        for ordinal, parameter in enumerate(business_parameters):
            if parameter.name not in _COMPETITION_NAMES:
                continue
            planning_row = planning.get((endpoint_cls.__name__, parameter.name))
            if planning_row is None:
                raise NbaApiCompetitionOccurrenceError(
                    "runtime package occurrence is absent from the request-surface authority"
                )
            default = parameter.default
            if default is inspect.Parameter.empty or not isinstance(default, str):
                raise NbaApiCompetitionOccurrenceError(
                    "competition constructor occurrence lacks its string default"
                )
            expected = {
                "default": default,
                "has_default": True,
                "name": parameter.name,
                "nullable": parameter.name == "league_id_nullable",
                "occurrence_id": (
                    f"parameter:stats:{endpoint_cls.__name__}:{ordinal:04d}:{parameter.name}"
                ),
                "ordinal": ordinal,
                "query_name": wire_names[parameter.name],
                "semantic_role": "scope_axis",
            }
            if any(planning_row.get(key) != value for key, value in expected.items()):
                raise NbaApiCompetitionOccurrenceError(
                    "runtime package occurrence differs from the request-surface authority"
                )
            rows.append(
                PackageCompetitionOccurrence(
                    occurrence_id=str(planning_row["occurrence_id"]),
                    provider_endpoint_id=endpoint_cls.__name__,
                    provider_module=endpoint_cls.__module__,
                    provider_source_path=relative_source,
                    provider_source_sha256=entry.sha256,
                    provider_source_size=entry.size,
                    ordinal=ordinal,
                    constructor_name=parameter.name,
                    wire_name=wire_names[parameter.name],
                    nullable=parameter.name == "league_id_nullable",
                    has_default=True,
                    default=default,
                    default_expression=_DEFAULT_EXPRESSIONS[parameter.name],
                    semantic_role="scope_axis",
                    request_surface_source_signature_sha256=str(
                        planning_row["source_signature_sha256"]
                    ),
                    request_surface_typed_domain_sha256=str(planning_row["typed_domain_sha256"]),
                )
            )
    result = tuple(sorted(rows, key=lambda item: item.occurrence_id))
    if {(item.provider_endpoint_id, item.constructor_name) for item in result} != set(planning):
        raise NbaApiCompetitionOccurrenceError(
            "request-surface authority contains an unobserved package occurrence"
        )
    return result


def _nested_code_objects(code: types.CodeType) -> Iterable[types.CodeType]:
    yield code
    for value in code.co_consts:
        if isinstance(value, types.CodeType):
            yield from _nested_code_objects(value)


def _runtime_provider_references(extractor_cls: type[BaseExtractor]) -> tuple[str, ...]:
    module = importlib.import_module(extractor_cls.__module__)
    refs: set[str] = set()
    for value in vars(extractor_cls).values():
        function = value.__func__ if isinstance(value, (classmethod, staticmethod)) else value
        if not inspect.isfunction(function):
            continue
        for code in _nested_code_objects(function.__code__):
            for name in code.co_names:
                candidate = getattr(module, name, None)
                if (
                    inspect.isclass(candidate)
                    and issubclass(candidate, Endpoint)
                    and candidate is not Endpoint
                    and candidate.__module__.startswith("nba_api.stats.endpoints.")
                ):
                    refs.add(candidate.__name__)
    return tuple(sorted(refs))


def _derive_runtime_repo_aliases(
    package_occurrences: tuple[PackageCompetitionOccurrence, ...],
) -> tuple[tuple[ExtractorCompetitionAlias, ...], tuple[RepoSourceBinding, ...]]:
    registry.discover("nbadb.extract.stats")
    by_endpoint: dict[str, tuple[PackageCompetitionOccurrence, ...]] = {}
    for occurrence in package_occurrences:
        by_endpoint.setdefault(occurrence.provider_endpoint_id, ())
        by_endpoint[occurrence.provider_endpoint_id] = (
            *by_endpoint[occurrence.provider_endpoint_id],
            occurrence,
        )
    source_bindings: dict[str, RepoSourceBinding] = {}
    rows: list[ExtractorCompetitionAlias] = []
    for extractor_cls in sorted(
        (
            candidate
            for candidate in registry.get_all()
            if candidate.__module__.startswith("nbadb.extract.stats.")
        ),
        key=lambda candidate: candidate.endpoint_name,
    ):
        if registry.get(extractor_cls.endpoint_name) is not extractor_cls:
            raise NbaApiCompetitionOccurrenceError(
                "extractor class is not the current registered endpoint authority"
            )
        provider_ids = tuple(
            ref for ref in _runtime_provider_references(extractor_cls) if ref in by_endpoint
        )
        if not provider_ids:
            continue
        module_parts = extractor_cls.__module__.split(".")
        if module_parts[:3] != ["nbadb", "extract", "stats"] or len(module_parts) < 4:
            raise NbaApiCompetitionOccurrenceError("registered extractor module path is invalid")
        package_parts = (*module_parts[1:-1], f"{module_parts[-1]}.py")
        source_path = f"src/nbadb/{'/'.join(package_parts)}"
        try:
            raw = resources.files("nbadb").joinpath(*package_parts).read_bytes()
        except (AttributeError, OSError) as exc:
            raise NbaApiCompetitionOccurrenceError(
                "registered extractor package source cannot be read"
            ) from exc
        source_sha256 = hashlib.sha256(raw).hexdigest()
        binding = RepoSourceBinding(
            path=source_path,
            sha256=source_sha256,
            size=len(raw),
        )
        existing = source_bindings.setdefault(source_path, binding)
        if existing != binding:
            raise NbaApiCompetitionOccurrenceError(
                "registered extractor source binding changed during derivation"
            )
        occurrences = tuple(
            sorted(
                (
                    occurrence
                    for endpoint_id in provider_ids
                    for occurrence in by_endpoint[endpoint_id]
                ),
                key=lambda item: item.occurrence_id,
            )
        )
        roles = tuple(
            sorted(
                (
                    ProjectedCompetitionRole(
                        provider_endpoint_id=occurrence.provider_endpoint_id,
                        provider_occurrence_id=occurrence.occurrence_id,
                        constructor_name=occurrence.constructor_name,
                        wire_name=occurrence.wire_name,
                        nullable=occurrence.nullable,
                        has_default=occurrence.has_default,
                        default=occurrence.default,
                        semantic_role=occurrence.semantic_role,
                        forwarding_behavior=_forwarding_behavior(occurrence.constructor_name),
                        output_behavior=_output_behavior(occurrence.constructor_name),
                    )
                    for occurrence in occurrences
                ),
                key=lambda item: (item.constructor_name, item.wire_name),
            )
        )
        rows.append(
            ExtractorCompetitionAlias(
                repo_endpoint_name=extractor_cls.endpoint_name,
                extractor_module=extractor_cls.__module__,
                extractor_qualname=extractor_cls.__qualname__,
                source_path=source_path,
                source_sha256=source_sha256,
                source_size=len(raw),
                provider_endpoint_ids=provider_ids,
                provider_occurrence_ids=tuple(sorted(item.occurrence_id for item in occurrences)),
                parameter_roles=roles,
            )
        )
    return (
        tuple(sorted(rows, key=lambda item: item.repo_endpoint_name)),
        tuple(sorted(source_bindings.values(), key=lambda item: item.path)),
    )


def _authority_payload(authority: CompetitionOccurrenceAuthority) -> dict[str, object]:
    package_rows = [item.to_dict() for item in authority.package_occurrences]
    repo_rows = [item.to_dict() for item in authority.repo_aliases]
    source_rows = [item.to_dict() for item in authority.repo_source_inventory]
    constructor_counts = dict(
        sorted(Counter(item.constructor_name for item in authority.package_occurrences).items())
    )
    wire_counts = dict(
        sorted(Counter(item.wire_name for item in authority.package_occurrences).items())
    )
    role_counts = dict(
        sorted(
            Counter(
                role.constructor_name
                for alias in authority.repo_aliases
                for role in alias.parameter_roles
            ).items()
        )
    )
    return {
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
        "package_endpoint_count": authority.package_endpoint_count,
        "package_occurrence_count": len(authority.package_occurrences),
        "package_occurrence_planning_census_sha256": (authority.package_planning_census_sha256),
        "package_occurrences": package_rows,
        "package_occurrences_sha256": authority.package_occurrences_sha256,
        "package_wire_name_counts": wire_counts,
        "projected_role_count": authority.projected_role_count,
        "projected_role_name_counts": role_counts,
        "provider": {
            "distribution_name": NBA_API_DISTRIBUTION,
            "distribution_record_authority_sha256": (
                authority.distribution_record_authority_sha256
            ),
            "distribution_version": NBA_API_VERSION,
        },
        "repo_alias_count": len(authority.repo_aliases),
        "repo_alias_planning_census_sha256": (authority.repo_alias_planning_census_sha256),
        "repo_aliases": repo_rows,
        "repo_aliases_sha256": authority.repo_aliases_sha256,
        "repo_source_bindings_sha256": authority.repo_source_bindings_sha256,
        "repo_source_file_count": len(authority.repo_source_inventory),
        "repo_source_inventory": source_rows,
        "repo_source_inventory_sha256": authority.repo_source_inventory_sha256,
        "schema_version": COMPETITION_OCCURRENCE_SCHEMA_VERSION,
        "upstream_request_surface": {
            "payload_sha256": authority.request_surface_payload_sha256,
            "resource": REQUEST_SURFACE_RESOURCE,
            "resource_sha256": authority.request_surface_resource_sha256,
            "surface_sha256": authority.request_surface_sha256,
        },
    }


@lru_cache(maxsize=1)
def build_competition_occurrence_authority() -> CompetitionOccurrenceAuthority:
    """Derive the primary occurrence authority without provider I/O."""

    distribution, record = _distribution_and_record()
    request_raw, request_payload, planning_rows = _request_surface_planning_rows()
    package_occurrences = _derive_runtime_package_occurrences(
        distribution,
        record,
        planning_rows,
    )
    repo_aliases, repo_sources = _derive_runtime_repo_aliases(package_occurrences)
    package_planning_sha256 = _planning_digest(list(planning_rows))
    repo_planning_rows = [item.planning_dict() for item in repo_aliases]
    authority = CompetitionOccurrenceAuthority(
        distribution_record_authority_sha256=str(getattr(record, "authority_sha256", "")),
        request_surface_resource_sha256=hashlib.sha256(request_raw).hexdigest(),
        request_surface_payload_sha256=str(request_payload.get("payload_sha256", "")),
        request_surface_sha256=str(request_payload.get("surface_sha256", "")),
        package_planning_census_sha256=package_planning_sha256,
        package_occurrences=package_occurrences,
        repo_alias_planning_census_sha256=_planning_digest(repo_planning_rows),
        repo_aliases=repo_aliases,
        repo_source_inventory=repo_sources,
    )
    return authority


def build_pinned_competition_occurrence_payload() -> dict[str, object]:
    """Build the canonical checked occurrence authority for the current tree."""

    authority = build_competition_occurrence_authority()
    body = _authority_payload(authority)
    payload: dict[str, object] = {
        **body,
        "authority_sha256": authority.authority_sha256,
        "independent_proof": {
            "claim_status": "not_supplied_by_this_artifact",
            "kind": "independent_competition_occurrence_source_ast_receipt",
            "required": True,
            "schema_version": 1,
        },
    }
    payload["payload_sha256"] = _digest(payload)
    return payload


def write_pinned_competition_occurrences(path: Path, *, check: bool = False) -> bool:
    """Write or verify the canonical checked occurrence resource."""

    encoded = _canonical_bytes(build_pinned_competition_occurrence_payload()) + b"\n"
    if path.is_file() and path.read_bytes() == encoded:
        return True
    if check:
        raise NbaApiCompetitionOccurrenceError(
            "pinned competition occurrence authority has generated drift"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encoded)
    return False


def load_pinned_competition_occurrence_payload(
    path: Path | None = None,
) -> dict[str, object]:
    """Load the checked resource and reproduce every current authority edge."""

    try:
        raw = (
            resources.files("nbadb.contracts")
            .joinpath(COMPETITION_OCCURRENCE_RESOURCE)
            .read_bytes()
            if path is None
            else path.read_bytes()
        )
    except (AttributeError, OSError) as exc:
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence resource cannot be read"
        ) from exc
    try:
        payload = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_object_pairs,
            parse_constant=_reject_constant,
        )
    except NbaApiCompetitionOccurrenceError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence resource cannot be decoded"
        ) from exc
    if not isinstance(payload, dict) or raw != _canonical_bytes(payload) + b"\n":
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence resource bytes are not canonical JSON"
        )
    body = dict(payload)
    payload_sha256 = body.pop("payload_sha256", None)
    if _require_digest(payload_sha256, "payload_sha256") != _digest(body):
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence resource payload digest is invalid"
        )
    if payload != build_pinned_competition_occurrence_payload():
        raise NbaApiCompetitionOccurrenceError(
            "competition occurrence resource differs from current package or repository authority"
        )
    return cast("dict[str, object]", payload)


@lru_cache(maxsize=1)
def pinned_competition_occurrence_authority() -> CompetitionOccurrenceAuthority:
    """Return the primary authority only after independent source verification."""

    payload = load_pinned_competition_occurrence_payload()
    authority = build_competition_occurrence_authority()
    from nbadb.core.nba_api_competition_occurrences_verifier import (
        verify_pinned_competition_occurrence_authority,
    )

    proof = verify_pinned_competition_occurrence_authority()
    if (
        proof.checked_payload_sha256 != payload.get("payload_sha256")
        or proof.authority_sha256 != authority.authority_sha256
        or proof.package_occurrences_sha256 != authority.package_occurrences_sha256
        or proof.repo_aliases_sha256 != authority.repo_aliases_sha256
        or proof.package_occurrence_count != len(authority.package_occurrences)
        or proof.repo_alias_count != len(authority.repo_aliases)
        or proof.projected_role_count != authority.projected_role_count
    ):
        raise NbaApiCompetitionOccurrenceError(
            "primary and independent competition occurrence authorities differ"
        )
    return authority


__all__ = [
    "COMPETITION_OCCURRENCE_RESOURCE",
    "COMPETITION_OCCURRENCE_SCHEMA_VERSION",
    "CompetitionOccurrenceAuthority",
    "ExtractorCompetitionAlias",
    "NbaApiCompetitionOccurrenceError",
    "PackageCompetitionOccurrence",
    "ProjectedCompetitionRole",
    "RepoSourceBinding",
    "build_competition_occurrence_authority",
    "build_pinned_competition_occurrence_payload",
    "load_pinned_competition_occurrence_payload",
    "pinned_competition_occurrence_authority",
    "write_pinned_competition_occurrences",
]
