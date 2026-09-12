"""Fail-closed current-authority binding for request-universe candidates.

This slice proves only that every *supplied* route and its complete declared
field denominator belongs to the current frozen authority graph.  It cannot
prove that the caller supplied every route, parameter value, temporal value,
dependent workload, or cumulative-stat value.  The resulting receipt is
therefore structurally nonterminal and never release eligible.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, is_dataclass
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast

from nbadb.orchestrate.request_universe_generation_contract import (
    ExplicitTemporalScopeValueV1,
    FieldOccurrenceInputV1,
    FieldPeriodDenominatorCellV1,
    RequestUniverseCandidateGenerationV1,
    RequestUniverseCandidateSourceV1,
    RequestUniverseFinalizationSourceV1,
    RequestUniverseV1,
    RouteRequestMemberV1,
    canonical_request_universe_json_bytes,
    canonical_request_universe_sha256,
    compile_request_universe_candidate_generation_v1,
    compile_request_universe_v1,
)
from nbadb.orchestrate.request_universe_generation_verifier import (
    RequestUniverseCandidateIndependentProofV1,
    RequestUniverseIndependentEmptyDeltaReceiptV1,
    RequestUniverseIndependentProofV1,
    verify_request_universe_candidate_independently,
    verify_request_universe_v1_independently,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from nbadb.orchestrate.checkpoint_contract import CheckpointTransaction
    from nbadb.orchestrate.request_closure_runtime import RequestClosureRuntimeReceipt

__all__ = [
    "REQUEST_UNIVERSE_FINAL_AUTHORITY_SCHEMA_VERSION",
    "REQUEST_UNIVERSE_SOURCE_ADMISSION_SCHEMA_VERSION",
    "RequestUniverseFinalAuthorityV1",
    "RequestUniverseSourceAdmissionError",
    "RequestUniverseSourceAdmissionV1",
    "RequestUniverseTemporalFieldDenominatorV1",
    "compile_request_universe_final_authority_v1",
    "compile_request_universe_source_admission_v1",
    "validate_request_universe_final_authority_v1",
    "validate_request_universe_source_admission_v1",
]

REQUEST_UNIVERSE_SOURCE_ADMISSION_SCHEMA_VERSION = 1
REQUEST_UNIVERSE_FINAL_AUTHORITY_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"[0-9a-f]{64}")
_MAX_CANONICAL_BYTES = 64 * 1024 * 1024
_BASE_BLOCKERS = (
    "complete_parameter_domain_not_admitted",
    "complete_request_denominator_not_admitted",
    "least_fixed_point_not_proven",
    "source_relative_candidate_only",
    "temporal_observation_evidence_not_admitted",
)


class RequestUniverseSourceAdmissionError(ValueError):
    """Raised when a candidate cannot be bound to current authorities."""


def _sha(value: object, *, field_name: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        raise RequestUniverseSourceAdmissionError(
            f"{field_name} must be an exact lowercase SHA-256"
        )
    return value


def _count(value: object, *, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise RequestUniverseSourceAdmissionError(f"{field_name} must be a nonnegative integer")
    return value


def _mapping(value: object, *, field_name: str) -> dict[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in value):
        raise RequestUniverseSourceAdmissionError(
            f"{field_name} must be an exact string-keyed object"
        )
    return cast("dict[str, object]", value)


def _array(value: object, *, field_name: str) -> list[object]:
    if type(value) is not list:
        raise RequestUniverseSourceAdmissionError(f"{field_name} must be an exact array")
    return cast("list[object]", value)


def _canonical_bytes(value: object) -> bytes:
    try:
        return canonical_request_universe_json_bytes(value)
    except (TypeError, ValueError, RecursionError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "request-universe source admission is not canonical JSON"
        ) from exc


def _canonical_sha256(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _exact_typed_equal(left: object, right: object) -> bool:
    """Compare nested contract state without bool/int or container coercion."""

    if type(left) is not type(right):
        return False
    if is_dataclass(left) and not isinstance(left, type):
        return all(
            _exact_typed_equal(getattr(left, item.name), getattr(right, item.name))
            for item in dataclass_fields(left)
        )
    if type(left) is dict:
        left_map = cast("dict[object, object]", left)
        right_map = cast("dict[object, object]", right)
        return set(left_map) == set(right_map) and all(
            _exact_typed_equal(key, next(key2 for key2 in right_map if key2 == key))
            and _exact_typed_equal(left_map[key], right_map[key])
            for key in left_map
        )
    if type(left) in {list, tuple}:
        left_items = cast("list[object] | tuple[object, ...]", left)
        right_items = cast("list[object] | tuple[object, ...]", right)
        return len(left_items) == len(right_items) and all(
            _exact_typed_equal(first, second)
            for first, second in zip(left_items, right_items, strict=True)
        )
    return left == right


def _strict_candidate_inputs(
    source: RequestUniverseCandidateSourceV1,
    candidate: RequestUniverseCandidateGenerationV1,
    independent_proof: RequestUniverseCandidateIndependentProofV1,
) -> tuple[
    RequestUniverseCandidateSourceV1,
    RequestUniverseCandidateGenerationV1,
    RequestUniverseCandidateIndependentProofV1,
]:
    """Reconstruct all caller DTOs and reject post-init mutation or type confusion."""

    try:
        rebuilt_source = RequestUniverseCandidateSourceV1.from_dict(
            _mapping(source.to_dict(), field_name="candidate source payload")
        )
        rebuilt_candidate = RequestUniverseCandidateGenerationV1.from_canonical_bytes(
            candidate.canonical_bytes
        )
        rebuilt_proof = RequestUniverseCandidateIndependentProofV1.from_canonical_bytes(
            independent_proof.canonical_bytes
        )
    except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "candidate inputs fail strict DTO reconstruction"
        ) from exc
    if (
        not _exact_typed_equal(source, rebuilt_source)
        or not _exact_typed_equal(candidate, rebuilt_candidate)
        or not _exact_typed_equal(independent_proof, rebuilt_proof)
    ):
        raise RequestUniverseSourceAdmissionError(
            "candidate inputs differ after strict DTO reconstruction"
        )
    return rebuilt_source, rebuilt_candidate, rebuilt_proof


def _decode_canonical_mapping(raw: bytes) -> dict[str, object]:
    if type(raw) is not bytes or not raw or len(raw) > _MAX_CANONICAL_BYTES:
        raise RequestUniverseSourceAdmissionError(
            "request-universe source admission byte length is invalid"
        )

    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise RequestUniverseSourceAdmissionError(
                    "request-universe source admission contains duplicate keys"
                )
            result[key] = value
        return result

    try:
        decoded = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=reject_duplicates,
            parse_constant=lambda _value: (_ for _ in ()).throw(
                RequestUniverseSourceAdmissionError(
                    "request-universe source admission contains a non-finite number"
                )
            ),
        )
    except RequestUniverseSourceAdmissionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "request-universe source admission is not valid JSON"
        ) from exc
    payload = _mapping(decoded, field_name="request-universe source admission root")
    if _canonical_bytes(payload) != raw:
        raise RequestUniverseSourceAdmissionError(
            "request-universe source admission is not exact canonical JSON"
        )
    return payload


@dataclass(frozen=True, slots=True)
class RequestUniverseSourceAdmissionV1:
    """Structural receipt for a current-authority-bound, nonterminal candidate."""

    authority_generation_sha256: str
    candidate_source_sha256: str
    candidate_generation_sha256: str
    candidate_independent_proof_sha256: str
    provider_authority_sha256: str
    request_surface_sha256: str
    competition_identity_authority_sha256: str
    current_source_authority_sha256: str
    staging_route_contract_sha256: str
    field_fate_contract_sha256: str
    temporal_contract_sha256: str
    logical_call_inventory_sha256: str
    route_member_inventory_sha256: str
    field_occurrence_inventory_sha256: str
    explicit_temporal_scope_inventory_sha256: str
    dependent_workload_inventory_sha256: str
    unintegrated_cume_inventory_sha256: str
    logical_call_count: int
    route_member_count: int
    field_occurrence_count: int
    explicit_temporal_scope_count: int
    dependent_workload_count: int
    unintegrated_cume_count: int
    blocker_codes: tuple[str, ...]
    supplied_member_bindings_validated: Literal[True] = True
    complete_denominator_admitted: Literal[False] = False
    least_fixed_point_proven: Literal[False] = False
    terminal: Literal[False] = False
    release_eligible: Literal[False] = False
    admission_sha256: str = ""

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_SOURCE_ADMISSION_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_source_admission_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "candidate_source_sha256",
            "candidate_generation_sha256",
            "candidate_independent_proof_sha256",
            "provider_authority_sha256",
            "request_surface_sha256",
            "competition_identity_authority_sha256",
            "current_source_authority_sha256",
            "staging_route_contract_sha256",
            "field_fate_contract_sha256",
            "temporal_contract_sha256",
            "logical_call_inventory_sha256",
            "route_member_inventory_sha256",
            "field_occurrence_inventory_sha256",
            "explicit_temporal_scope_inventory_sha256",
            "dependent_workload_inventory_sha256",
            "unintegrated_cume_inventory_sha256",
        ):
            _sha(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "logical_call_count",
            "route_member_count",
            "field_occurrence_count",
            "explicit_temporal_scope_count",
            "dependent_workload_count",
            "unintegrated_cume_count",
        ):
            _count(getattr(self, field_name), field_name=field_name)
        if type(self.blocker_codes) is not tuple or not self.blocker_codes:
            raise RequestUniverseSourceAdmissionError(
                "blocker_codes must be an exact nonempty tuple"
            )
        if any(type(code) is not str or not code for code in self.blocker_codes):
            raise RequestUniverseSourceAdmissionError("blocker code is invalid")
        if self.blocker_codes != tuple(sorted(set(self.blocker_codes))):
            raise RequestUniverseSourceAdmissionError("blocker_codes must be sorted and unique")
        if not set(_BASE_BLOCKERS) <= set(self.blocker_codes):
            raise RequestUniverseSourceAdmissionError(
                "source-relative admission lacks its mandatory blockers"
            )
        if (
            self.supplied_member_bindings_validated is not True
            or self.complete_denominator_admitted is not False
            or self.least_fixed_point_proven is not False
            or self.terminal is not False
            or self.release_eligible is not False
        ):
            raise RequestUniverseSourceAdmissionError(
                "source-relative admission cannot attest completeness or release"
            )
        expected = _canonical_sha256(self._body())
        if self.admission_sha256 != expected:
            raise RequestUniverseSourceAdmissionError(
                "admission_sha256 differs from the exact admission body"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "candidate_source_sha256": self.candidate_source_sha256,
            "candidate_generation_sha256": self.candidate_generation_sha256,
            "candidate_independent_proof_sha256": (self.candidate_independent_proof_sha256),
            "provider_authority_sha256": self.provider_authority_sha256,
            "request_surface_sha256": self.request_surface_sha256,
            "competition_identity_authority_sha256": (self.competition_identity_authority_sha256),
            "current_source_authority_sha256": self.current_source_authority_sha256,
            "staging_route_contract_sha256": self.staging_route_contract_sha256,
            "field_fate_contract_sha256": self.field_fate_contract_sha256,
            "temporal_contract_sha256": self.temporal_contract_sha256,
            "logical_call_inventory_sha256": self.logical_call_inventory_sha256,
            "route_member_inventory_sha256": self.route_member_inventory_sha256,
            "field_occurrence_inventory_sha256": self.field_occurrence_inventory_sha256,
            "explicit_temporal_scope_inventory_sha256": (
                self.explicit_temporal_scope_inventory_sha256
            ),
            "dependent_workload_inventory_sha256": (self.dependent_workload_inventory_sha256),
            "unintegrated_cume_inventory_sha256": self.unintegrated_cume_inventory_sha256,
            "logical_call_count": self.logical_call_count,
            "route_member_count": self.route_member_count,
            "field_occurrence_count": self.field_occurrence_count,
            "explicit_temporal_scope_count": self.explicit_temporal_scope_count,
            "dependent_workload_count": self.dependent_workload_count,
            "unintegrated_cume_count": self.unintegrated_cume_count,
            "blocker_codes": list(self.blocker_codes),
            "supplied_member_bindings_validated": self.supplied_member_bindings_validated,
            "complete_denominator_admitted": self.complete_denominator_admitted,
            "least_fixed_point_proven": self.least_fixed_point_proven,
            "terminal": self.terminal,
            "release_eligible": self.release_eligible,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "admission_sha256": self.admission_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "candidate_source_sha256",
                "candidate_generation_sha256",
                "candidate_independent_proof_sha256",
                "provider_authority_sha256",
                "request_surface_sha256",
                "competition_identity_authority_sha256",
                "current_source_authority_sha256",
                "staging_route_contract_sha256",
                "field_fate_contract_sha256",
                "temporal_contract_sha256",
                "logical_call_inventory_sha256",
                "route_member_inventory_sha256",
                "field_occurrence_inventory_sha256",
                "explicit_temporal_scope_inventory_sha256",
                "dependent_workload_inventory_sha256",
                "unintegrated_cume_inventory_sha256",
                "logical_call_count",
                "route_member_count",
                "field_occurrence_count",
                "explicit_temporal_scope_count",
                "dependent_workload_count",
                "unintegrated_cume_count",
                "blocker_codes",
                "supplied_member_bindings_validated",
                "complete_denominator_admitted",
                "least_fixed_point_proven",
                "terminal",
                "release_eligible",
                "admission_sha256",
            }
        )
        item = _mapping(payload, field_name="request-universe source admission")
        if frozenset(item) != expected:
            raise RequestUniverseSourceAdmissionError(
                "request-universe source admission has missing or unexpected fields"
            )
        if (
            type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
            or item["kind"] != cls.kind
        ):
            raise RequestUniverseSourceAdmissionError(
                "request-universe source admission schema identity is invalid"
            )
        return cls(
            authority_generation_sha256=cast("str", item["authority_generation_sha256"]),
            candidate_source_sha256=cast("str", item["candidate_source_sha256"]),
            candidate_generation_sha256=cast("str", item["candidate_generation_sha256"]),
            candidate_independent_proof_sha256=cast(
                "str", item["candidate_independent_proof_sha256"]
            ),
            provider_authority_sha256=cast("str", item["provider_authority_sha256"]),
            request_surface_sha256=cast("str", item["request_surface_sha256"]),
            competition_identity_authority_sha256=cast(
                "str", item["competition_identity_authority_sha256"]
            ),
            current_source_authority_sha256=cast("str", item["current_source_authority_sha256"]),
            staging_route_contract_sha256=cast("str", item["staging_route_contract_sha256"]),
            field_fate_contract_sha256=cast("str", item["field_fate_contract_sha256"]),
            temporal_contract_sha256=cast("str", item["temporal_contract_sha256"]),
            logical_call_inventory_sha256=cast("str", item["logical_call_inventory_sha256"]),
            route_member_inventory_sha256=cast("str", item["route_member_inventory_sha256"]),
            field_occurrence_inventory_sha256=cast(
                "str", item["field_occurrence_inventory_sha256"]
            ),
            explicit_temporal_scope_inventory_sha256=cast(
                "str", item["explicit_temporal_scope_inventory_sha256"]
            ),
            dependent_workload_inventory_sha256=cast(
                "str", item["dependent_workload_inventory_sha256"]
            ),
            unintegrated_cume_inventory_sha256=cast(
                "str", item["unintegrated_cume_inventory_sha256"]
            ),
            logical_call_count=cast("int", item["logical_call_count"]),
            route_member_count=cast("int", item["route_member_count"]),
            field_occurrence_count=cast("int", item["field_occurrence_count"]),
            explicit_temporal_scope_count=cast("int", item["explicit_temporal_scope_count"]),
            dependent_workload_count=cast("int", item["dependent_workload_count"]),
            unintegrated_cume_count=cast("int", item["unintegrated_cume_count"]),
            blocker_codes=tuple(
                cast("list[str]", _array(item["blocker_codes"], field_name="blocker_codes"))
            ),
            supplied_member_bindings_validated=cast(
                "Literal[True]", item["supplied_member_bindings_validated"]
            ),
            complete_denominator_admitted=cast(
                "Literal[False]", item["complete_denominator_admitted"]
            ),
            least_fixed_point_proven=cast("Literal[False]", item["least_fixed_point_proven"]),
            terminal=cast("Literal[False]", item["terminal"]),
            release_eligible=cast("Literal[False]", item["release_eligible"]),
            admission_sha256=cast("str", item["admission_sha256"]),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw))
        if result.canonical_bytes != raw:
            raise RequestUniverseSourceAdmissionError(
                "request-universe source admission changed after strict reconstruction"
            )
        return result


def _current_authorities() -> dict[str, Any]:
    from nbadb.contracts.field_fate_contract import compile_field_fate_contracts
    from nbadb.contracts.implicit_competition_source_authority_loader import (
        load_implicit_competition_current_source_authority,
    )
    from nbadb.contracts.staging_route_contract import (
        staging_route_contract_bundle,
        validate_staging_route_contract_bundle,
    )
    from nbadb.contracts.temporal_availability_contract import (
        temporal_availability_contract_bundle,
        validate_temporal_availability_contract_bundle,
    )
    from nbadb.core.nba_api_competition_identity import (
        load_pinned_competition_identity_payload,
    )
    from nbadb.core.nba_api_competition_identity_verifier import (
        verify_pinned_competition_identity_authority,
    )
    from nbadb.core.nba_api_provenance import expected_nba_api_provider_authority
    from nbadb.core.nba_api_request_surface import pinned_request_surface_authority

    routes = staging_route_contract_bundle()
    validate_staging_route_contract_bundle(routes)
    fields = compile_field_fate_contracts()
    temporal = temporal_availability_contract_bundle()
    validate_temporal_availability_contract_bundle(temporal)
    competition = load_pinned_competition_identity_payload()
    competition_proof = verify_pinned_competition_identity_authority()
    if (
        competition_proof.candidate_authority_sha256 != competition["authority_sha256"]
        or competition_proof.findings
    ):
        raise RequestUniverseSourceAdmissionError(
            "competition identity authority is not independently green"
        )
    return {
        "provider": expected_nba_api_provider_authority(),
        "request": pinned_request_surface_authority(),
        "competition": competition,
        "current_source": load_implicit_competition_current_source_authority(),
        "routes": routes,
        "fields": fields,
        "temporal": temporal,
    }


def _validate_current_membership(
    source: RequestUniverseCandidateSourceV1,
    *,
    authorities: Mapping[str, Any],
) -> None:
    from nbadb.core.nba_api_request_surface import (
        NbaApiRequestSurfaceError,
        materialize_provider_request,
    )

    routes = authorities["routes"]
    fields = authorities["fields"]
    temporal = authorities["temporal"]
    request = authorities["request"]
    if source.field_fate_contract_sha256 != fields.digest:
        raise RequestUniverseSourceAdmissionError(
            "candidate field-fate authority differs from the current contract"
        )
    if source.temporal_contract_sha256 != temporal.digest:
        raise RequestUniverseSourceAdmissionError(
            "candidate temporal authority differs from the current contract"
        )

    current_routes = {route.route_id: route for route in routes.routes}
    calls = {call.physical_call_id: call for call in source.logical_calls}
    referenced_calls: set[str] = set()
    selected_route_ids: set[str] = set()
    current_route_by_call: dict[str, Any] = {}
    for member in source.route_members:
        current = current_routes.get(member.route_id)
        call = calls.get(member.physical_call_id)
        if current is None or call is None:
            raise RequestUniverseSourceAdmissionError(
                "candidate route member is absent from the current route authority"
            )
        if (
            call.source_family != current.source_family
            or call.endpoint_name != current.endpoint_name
            or call.canonical_endpoint_name != current.canonical_endpoint_name
            or call.physical_endpoint_name != current.endpoint_name
        ):
            raise RequestUniverseSourceAdmissionError(
                "candidate physical call differs from the current route authority"
            )
        expected_member = RouteRequestMemberV1.build(
            call=call,
            route_id=current.route_id,
            result_name=current.provider_result_set_name,
            result_ordinal=current.provider_result_set_ordinal,
            nested_path=member.nested_path,
        )
        if member != expected_member:
            raise RequestUniverseSourceAdmissionError(
                "candidate route member differs from the current result authority"
            )
        referenced_calls.add(call.physical_call_id)
        selected_route_ids.add(current.route_id)
        prior_route = current_route_by_call.setdefault(call.physical_call_id, current)
        if (
            prior_route.source_family,
            prior_route.provider_endpoint_id,
        ) != (
            current.source_family,
            current.provider_endpoint_id,
        ):
            raise RequestUniverseSourceAdmissionError(
                "one physical call cannot materialize multiple provider endpoints"
            )
    if referenced_calls != set(calls):
        raise RequestUniverseSourceAdmissionError(
            "candidate contains a physical call with no current route member"
        )

    static_dataset_ids = {dataset.dataset_id for dataset in request.static_datasets}
    for physical_call_id, current in current_route_by_call.items():
        call = calls[physical_call_id]
        if call.pagination_kind != "none":
            raise RequestUniverseSourceAdmissionError(
                "candidate pagination lacks a current provider pagination authority"
            )
        if current.source_family == "static":
            if current.provider_endpoint_id not in static_dataset_ids or call.parameter_items:
                raise RequestUniverseSourceAdmissionError(
                    "candidate static call differs from the current embedded dataset authority"
                )
            continue
        try:
            endpoint = request.endpoint(current.source_family, current.provider_endpoint_id)
            materialize_provider_request(
                endpoint,
                dict(call.parameter_items),
                request_surface_sha256=request.surface_sha256,
                runtime_contract_payload_sha256=request.runtime_contract_payload_sha256,
            )
        except NbaApiRequestSurfaceError as exc:
            raise RequestUniverseSourceAdmissionError(
                "candidate parameters differ from the current provider request authority"
            ) from exc

    expected_fields = tuple(
        sorted(
            (
                FieldOccurrenceInputV1.from_current_contract(
                    authority_generation_sha256=source.authority_generation_sha256,
                    field_fate_contract_sha256=fields.digest,
                    field_fate=field,
                )
                for field in fields.fields
                if field.route_id in selected_route_ids
            ),
            key=lambda item: item.identity_sha256,
        )
    )
    if source.field_occurrences != expected_fields:
        raise RequestUniverseSourceAdmissionError(
            "candidate omits or mutates the current field denominator for a supplied route"
        )

    expected_result_paths_by_route: dict[str, set[tuple[str, int, tuple[str | int, ...]]]] = {}
    for field in expected_fields:
        expected_result_paths_by_route.setdefault(field.route_id, set()).add(
            (field.result_name, field.result_ordinal, field.nested_path)
        )
    actual_result_paths_by_call_route: dict[
        tuple[str, str], set[tuple[str, int, tuple[str | int, ...]]]
    ] = {}
    for member in source.route_members:
        actual_result_paths_by_call_route.setdefault(
            (member.physical_call_id, member.route_id), set()
        ).add((member.result_name, member.result_ordinal, member.nested_path))
    for (_physical_call_id, route_id), actual_paths in actual_result_paths_by_call_route.items():
        current = current_routes[route_id]
        expected_paths = expected_result_paths_by_route.get(route_id)
        if expected_paths is None:
            if (
                current.provider_result_set_name is None
                or current.provider_result_set_ordinal is None
            ):
                raise RequestUniverseSourceAdmissionError(
                    "current zero-field route lacks an exact result identity"
                )
            expected_paths = {
                (
                    current.provider_result_set_name,
                    current.provider_result_set_ordinal,
                    (),
                )
            }
        if actual_paths != expected_paths:
            raise RequestUniverseSourceAdmissionError(
                "candidate route members omit or invent a current result/nested-path member"
            )

    current_temporal = {scope.route_id: scope for scope in temporal.scopes}
    route_members = {member.route_request_member_id: member for member in source.route_members}
    for period in source.explicit_temporal_scopes:
        route_member = route_members[period.route_request_member_id]
        route_scope = current_temporal.get(period.route_id)
        if route_scope is None:
            raise RequestUniverseSourceAdmissionError(
                "candidate temporal scope is absent from the current route authority"
            )
        expected_period = ExplicitTemporalScopeValueV1.from_current_contract(
            authority_generation_sha256=source.authority_generation_sha256,
            temporal_contract_sha256=temporal.digest,
            route_member=route_member,
            route_scope=route_scope,
            temporal_scope_kind=period.temporal_scope_kind,
            temporal_scope_value=period.temporal_scope_value,
        )
        if period != expected_period:
            raise RequestUniverseSourceAdmissionError(
                "candidate temporal scope differs from the current temporal authority"
            )


def compile_request_universe_source_admission_v1(
    *,
    source: RequestUniverseCandidateSourceV1,
    candidate: RequestUniverseCandidateGenerationV1,
    independent_proof: RequestUniverseCandidateIndependentProofV1,
) -> RequestUniverseSourceAdmissionV1:
    """Bind one candidate to current authorities without promoting it to finality."""

    if type(source) is not RequestUniverseCandidateSourceV1:
        raise RequestUniverseSourceAdmissionError("source must be the exact source DTO")
    if type(candidate) is not RequestUniverseCandidateGenerationV1:
        raise RequestUniverseSourceAdmissionError("candidate must be the exact candidate DTO")
    if type(independent_proof) is not RequestUniverseCandidateIndependentProofV1:
        raise RequestUniverseSourceAdmissionError(
            "independent_proof must be the exact independent proof DTO"
        )
    source, candidate, independent_proof = _strict_candidate_inputs(
        source,
        candidate,
        independent_proof,
    )
    expected_candidate = compile_request_universe_candidate_generation_v1(source)
    if not _exact_typed_equal(candidate, expected_candidate):
        raise RequestUniverseSourceAdmissionError(
            "candidate differs from the current source compilation"
        )
    expected_proof = verify_request_universe_candidate_independently(
        source_payload=source.to_dict(),
        candidate_payload=candidate.to_dict(),
    )
    if not _exact_typed_equal(independent_proof, expected_proof):
        raise RequestUniverseSourceAdmissionError(
            "candidate independent proof differs from current source bytes"
        )

    authorities = _current_authorities()
    _validate_current_membership(source, authorities=authorities)
    provider = authorities["provider"]
    request = authorities["request"]
    competition = authorities["competition"]
    current_source = authorities["current_source"]
    routes = authorities["routes"]
    fields = authorities["fields"]
    temporal = authorities["temporal"]

    dependent = [
        {
            "physical_call_id": call.physical_call_id,
            "dependent_workload_kind": call.dependent_workload_kind,
            "dependent_workload_sha256": call.dependent_workload_sha256,
            "dependent_physical_alias": call.dependent_physical_alias,
        }
        for call in source.logical_calls
        if call.dependent_workload_sha256 is not None
    ]
    cume = [value.to_dict() for value in source.unintegrated_cume_values]
    blockers = set(_BASE_BLOCKERS)
    if dependent:
        blockers.add("dependent_workload_authority_not_admitted")
    if cume:
        blockers.add("cume_workload_values_not_integrated")

    body: dict[str, object] = {
        "schema_version": REQUEST_UNIVERSE_SOURCE_ADMISSION_SCHEMA_VERSION,
        "kind": RequestUniverseSourceAdmissionV1.kind,
        "authority_generation_sha256": source.authority_generation_sha256,
        "candidate_source_sha256": source.source_inputs_sha256,
        "candidate_generation_sha256": candidate.identity_sha256,
        "candidate_independent_proof_sha256": independent_proof.identity_sha256,
        "provider_authority_sha256": provider["authority_sha256"],
        "request_surface_sha256": request.surface_sha256,
        "competition_identity_authority_sha256": competition["authority_sha256"],
        "current_source_authority_sha256": current_source.authority_sha256,
        "staging_route_contract_sha256": routes.digest,
        "field_fate_contract_sha256": fields.digest,
        "temporal_contract_sha256": temporal.digest,
        "logical_call_inventory_sha256": candidate.logical_call_inventory_sha256,
        "route_member_inventory_sha256": candidate.route_member_inventory_sha256,
        "field_occurrence_inventory_sha256": canonical_request_universe_sha256(
            [item.to_dict() for item in source.field_occurrences]
        ),
        "explicit_temporal_scope_inventory_sha256": canonical_request_universe_sha256(
            [item.to_dict() for item in source.explicit_temporal_scopes]
        ),
        "dependent_workload_inventory_sha256": canonical_request_universe_sha256(dependent),
        "unintegrated_cume_inventory_sha256": canonical_request_universe_sha256(cume),
        "logical_call_count": len(source.logical_calls),
        "route_member_count": len(source.route_members),
        "field_occurrence_count": len(source.field_occurrences),
        "explicit_temporal_scope_count": len(source.explicit_temporal_scopes),
        "dependent_workload_count": len(dependent),
        "unintegrated_cume_count": len(cume),
        "blocker_codes": sorted(blockers),
        "supplied_member_bindings_validated": True,
        "complete_denominator_admitted": False,
        "least_fixed_point_proven": False,
        "terminal": False,
        "release_eligible": False,
    }
    return RequestUniverseSourceAdmissionV1.from_dict(
        {**body, "admission_sha256": _canonical_sha256(body)}
    )


def validate_request_universe_source_admission_v1(
    *,
    observed: RequestUniverseSourceAdmissionV1 | Mapping[str, object] | bytes,
    source: RequestUniverseCandidateSourceV1,
    candidate: RequestUniverseCandidateGenerationV1,
    independent_proof: RequestUniverseCandidateIndependentProofV1,
) -> RequestUniverseSourceAdmissionV1:
    """Recompile current authorities and reject a stale or self-resealed receipt."""

    if type(observed) is RequestUniverseSourceAdmissionV1:
        parsed = RequestUniverseSourceAdmissionV1.from_canonical_bytes(observed.canonical_bytes)
    elif type(observed) is bytes:
        parsed = RequestUniverseSourceAdmissionV1.from_canonical_bytes(observed)
    elif type(observed) is dict:
        parsed = RequestUniverseSourceAdmissionV1.from_dict(observed)
    else:
        raise RequestUniverseSourceAdmissionError(
            "observed source admission has an unsupported representation"
        )
    expected = compile_request_universe_source_admission_v1(
        source=source,
        candidate=candidate,
        independent_proof=independent_proof,
    )
    if parsed != expected:
        raise RequestUniverseSourceAdmissionError(
            "observed source admission differs from current authority recompilation"
        )
    return expected


@dataclass(frozen=True, slots=True)
class RequestUniverseTemporalFieldDenominatorV1:
    """Typed replayable field-period denominator bound to upstream authorities."""

    authority_generation_sha256: str
    candidate_generation_sha256: str
    checkpoint_identity_sha256: str
    request_closure_receipt_sha256: str
    w2_authority_identity_sha256: str
    parent_field_period_inventory_sha256: str
    field_period_cells: tuple[FieldPeriodDenominatorCellV1, ...]
    field_period_inventory_sha256: str
    field_period_count: int
    receipt_sha256: str

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_temporal_field_denominator_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "candidate_generation_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "parent_field_period_inventory_sha256",
            "field_period_inventory_sha256",
        ):
            _sha(getattr(self, field_name), field_name=field_name)
        _count(self.field_period_count, field_name="field_period_count")
        if type(self.field_period_cells) is not tuple or any(
            type(item) is not FieldPeriodDenominatorCellV1 for item in self.field_period_cells
        ):
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator cells must be an exact typed tuple"
            )
        cells = tuple(sorted(self.field_period_cells, key=lambda item: item.cell_id))
        if (
            not cells
            or cells != self.field_period_cells
            or len({item.cell_id for item in cells}) != len(cells)
            or any(
                item.authority_generation_sha256 != self.authority_generation_sha256
                for item in cells
            )
        ):
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator is empty, duplicated, unsorted, or foreign"
            )
        inventory = _canonical_sha256([item.to_dict() for item in cells])
        if (
            self.field_period_count != len(cells)
            or self.field_period_inventory_sha256 != inventory
            or self.parent_field_period_inventory_sha256 != inventory
        ):
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator count or inventory differs"
            )
        if self.receipt_sha256 != _canonical_sha256(self._body()):
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator receipt digest differs"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            "authority_generation_sha256": self.authority_generation_sha256,
            "candidate_generation_sha256": self.candidate_generation_sha256,
            "checkpoint_identity_sha256": self.checkpoint_identity_sha256,
            "request_closure_receipt_sha256": self.request_closure_receipt_sha256,
            "w2_authority_identity_sha256": self.w2_authority_identity_sha256,
            "parent_field_period_inventory_sha256": (self.parent_field_period_inventory_sha256),
            "field_period_inventory_sha256": self.field_period_inventory_sha256,
            "field_period_count": self.field_period_count,
            "field_period_cells": [item.to_dict() for item in self.field_period_cells],
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "receipt_sha256": self.receipt_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def build(
        cls,
        *,
        candidate: RequestUniverseCandidateGenerationV1,
        checkpoint_identity_sha256: str,
        request_closure_receipt_sha256: str,
        w2_authority_identity_sha256: str,
    ) -> Self:
        cells = candidate.field_period_cells
        inventory = _canonical_sha256([item.to_dict() for item in cells])
        body = {
            "schema_version": cls.schema_version,
            "kind": cls.kind,
            "authority_generation_sha256": candidate.authority_generation_sha256,
            "candidate_generation_sha256": candidate.identity_sha256,
            "checkpoint_identity_sha256": checkpoint_identity_sha256,
            "request_closure_receipt_sha256": request_closure_receipt_sha256,
            "w2_authority_identity_sha256": w2_authority_identity_sha256,
            "parent_field_period_inventory_sha256": (candidate.field_period_inventory_sha256),
            "field_period_inventory_sha256": inventory,
            "field_period_count": len(cells),
            "field_period_cells": [item.to_dict() for item in cells],
        }
        return cls.from_dict({**body, "receipt_sha256": _canonical_sha256(body)})

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        expected = frozenset(
            {
                "schema_version",
                "kind",
                "authority_generation_sha256",
                "candidate_generation_sha256",
                "checkpoint_identity_sha256",
                "request_closure_receipt_sha256",
                "w2_authority_identity_sha256",
                "parent_field_period_inventory_sha256",
                "field_period_inventory_sha256",
                "field_period_count",
                "field_period_cells",
                "receipt_sha256",
            }
        )
        item = _mapping(payload, field_name="temporal-field denominator")
        if frozenset(item) != expected:
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator has missing or unexpected fields"
            )
        if (
            type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
            or item["kind"] != cls.kind
        ):
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator schema identity is invalid"
            )
        cells = tuple(
            FieldPeriodDenominatorCellV1.from_dict(
                _mapping(value, field_name="field-period denominator cell")
            )
            for value in _array(
                item["field_period_cells"],
                field_name="field_period_cells",
            )
        )
        return cls(
            authority_generation_sha256=cast("str", item["authority_generation_sha256"]),
            candidate_generation_sha256=cast("str", item["candidate_generation_sha256"]),
            checkpoint_identity_sha256=cast("str", item["checkpoint_identity_sha256"]),
            request_closure_receipt_sha256=cast("str", item["request_closure_receipt_sha256"]),
            w2_authority_identity_sha256=cast("str", item["w2_authority_identity_sha256"]),
            parent_field_period_inventory_sha256=cast(
                "str", item["parent_field_period_inventory_sha256"]
            ),
            field_period_cells=cells,
            field_period_inventory_sha256=cast("str", item["field_period_inventory_sha256"]),
            field_period_count=cast("int", item["field_period_count"]),
            receipt_sha256=cast("str", item["receipt_sha256"]),
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw))
        if result.canonical_bytes != raw:
            raise RequestUniverseSourceAdmissionError(
                "temporal-field denominator is not exact canonical JSON"
            )
        return result


@dataclass(frozen=True, slots=True)
class RequestUniverseFinalAuthorityV1:
    """Receipt joining both compilers to one exact terminal request denominator."""

    authority_generation_sha256: str
    candidate_source_sha256: str
    candidate_generation_sha256: str
    candidate_independent_proof_sha256: str
    source_admission_sha256: str
    checkpoint_identity_sha256: str
    request_closure_receipt_sha256: str
    w2_authority_identity_sha256: str
    temporal_field_denominator_sha256: str
    committed_observation_generation_sha256: str
    finalization_source_sha256: str
    request_universe_sha256: str
    primary_empty_delta_receipt_sha256: str
    independent_proof_sha256: str
    independent_empty_delta_receipt_sha256: str
    logical_call_inventory_sha256: str
    terminal_classification_inventory_sha256: str
    shard_inventory_sha256: str
    logical_call_count: int
    terminal_classification_count: int
    shard_count: int
    primary_independent_compilers_equal: Literal[True]
    empty_delta_agreement: Literal[True]
    exact_request_denominator: Literal[True]
    terminal_classification_complete: Literal[True]
    shard_partition_exact: Literal[True]
    least_fixed_point_proven: Literal[True]
    request_universe_terminal: Literal[True]
    overall_release_eligible: Literal[False]
    authority_sha256: str

    schema_version: ClassVar[int] = REQUEST_UNIVERSE_FINAL_AUTHORITY_SCHEMA_VERSION
    kind: ClassVar[str] = "request_universe_final_authority_v1"

    def __post_init__(self) -> None:
        for field_name in (
            "authority_generation_sha256",
            "candidate_source_sha256",
            "candidate_generation_sha256",
            "candidate_independent_proof_sha256",
            "source_admission_sha256",
            "checkpoint_identity_sha256",
            "request_closure_receipt_sha256",
            "w2_authority_identity_sha256",
            "temporal_field_denominator_sha256",
            "committed_observation_generation_sha256",
            "finalization_source_sha256",
            "request_universe_sha256",
            "primary_empty_delta_receipt_sha256",
            "independent_proof_sha256",
            "independent_empty_delta_receipt_sha256",
            "logical_call_inventory_sha256",
            "terminal_classification_inventory_sha256",
            "shard_inventory_sha256",
        ):
            _sha(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "logical_call_count",
            "terminal_classification_count",
            "shard_count",
        ):
            _count(getattr(self, field_name), field_name=field_name)
        if (
            self.logical_call_count < 1
            or self.terminal_classification_count != self.logical_call_count
            or self.shard_count < 1
            or self.shard_count > self.logical_call_count
        ):
            raise RequestUniverseSourceAdmissionError(
                "final request-universe counts do not form an exact nonempty denominator"
            )
        if (
            self.primary_independent_compilers_equal is not True
            or self.empty_delta_agreement is not True
            or self.exact_request_denominator is not True
            or self.terminal_classification_complete is not True
            or self.shard_partition_exact is not True
            or self.least_fixed_point_proven is not True
            or self.request_universe_terminal is not True
            or self.overall_release_eligible is not False
        ):
            raise RequestUniverseSourceAdmissionError(
                "final request-universe authority flags are invalid"
            )
        if self.authority_sha256 != _canonical_sha256(self._body()):
            raise RequestUniverseSourceAdmissionError(
                "final request-universe authority digest differs"
            )

    def _body(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "kind": self.kind,
            **{
                field_name: getattr(self, field_name)
                for field_name in (
                    "authority_generation_sha256",
                    "candidate_source_sha256",
                    "candidate_generation_sha256",
                    "candidate_independent_proof_sha256",
                    "source_admission_sha256",
                    "checkpoint_identity_sha256",
                    "request_closure_receipt_sha256",
                    "w2_authority_identity_sha256",
                    "temporal_field_denominator_sha256",
                    "committed_observation_generation_sha256",
                    "finalization_source_sha256",
                    "request_universe_sha256",
                    "primary_empty_delta_receipt_sha256",
                    "independent_proof_sha256",
                    "independent_empty_delta_receipt_sha256",
                    "logical_call_inventory_sha256",
                    "terminal_classification_inventory_sha256",
                    "shard_inventory_sha256",
                    "logical_call_count",
                    "terminal_classification_count",
                    "shard_count",
                    "primary_independent_compilers_equal",
                    "empty_delta_agreement",
                    "exact_request_denominator",
                    "terminal_classification_complete",
                    "shard_partition_exact",
                    "least_fixed_point_proven",
                    "request_universe_terminal",
                    "overall_release_eligible",
                )
            },
        }

    def to_dict(self) -> dict[str, object]:
        return {**self._body(), "authority_sha256": self.authority_sha256}

    @property
    def canonical_bytes(self) -> bytes:
        return _canonical_bytes(self.to_dict())

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> Self:
        fields = frozenset(
            {
                "authority_generation_sha256",
                "candidate_source_sha256",
                "candidate_generation_sha256",
                "candidate_independent_proof_sha256",
                "source_admission_sha256",
                "checkpoint_identity_sha256",
                "request_closure_receipt_sha256",
                "w2_authority_identity_sha256",
                "temporal_field_denominator_sha256",
                "committed_observation_generation_sha256",
                "finalization_source_sha256",
                "request_universe_sha256",
                "primary_empty_delta_receipt_sha256",
                "independent_proof_sha256",
                "independent_empty_delta_receipt_sha256",
                "logical_call_inventory_sha256",
                "terminal_classification_inventory_sha256",
                "shard_inventory_sha256",
                "logical_call_count",
                "terminal_classification_count",
                "shard_count",
                "primary_independent_compilers_equal",
                "empty_delta_agreement",
                "exact_request_denominator",
                "terminal_classification_complete",
                "shard_partition_exact",
                "least_fixed_point_proven",
                "request_universe_terminal",
                "overall_release_eligible",
                "authority_sha256",
            }
        )
        item = _mapping(payload, field_name="final request-universe authority")
        if frozenset(item) != frozenset({"schema_version", "kind", *fields}):
            raise RequestUniverseSourceAdmissionError(
                "final request-universe authority has missing or unexpected fields"
            )
        if (
            type(item["schema_version"]) is not int
            or item["schema_version"] != cls.schema_version
            or item["kind"] != cls.kind
        ):
            raise RequestUniverseSourceAdmissionError(
                "final request-universe authority schema identity is invalid"
            )
        return cls(**cast("Any", {field: item[field] for field in fields}))

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> Self:
        result = cls.from_dict(_decode_canonical_mapping(raw))
        if result.canonical_bytes != raw:
            raise RequestUniverseSourceAdmissionError(
                "final request-universe authority is not exact canonical JSON"
            )
        return result


def _strict_final_authority_inputs(
    *,
    temporal_field_denominator: RequestUniverseTemporalFieldDenominatorV1,
    finalization_source: RequestUniverseFinalizationSourceV1,
    request_universe: RequestUniverseV1,
    final_independent_proof: RequestUniverseIndependentProofV1,
    independent_empty_delta_receipt: RequestUniverseIndependentEmptyDeltaReceiptV1,
) -> tuple[
    RequestUniverseTemporalFieldDenominatorV1,
    RequestUniverseFinalizationSourceV1,
    RequestUniverseV1,
    RequestUniverseIndependentProofV1,
    RequestUniverseIndependentEmptyDeltaReceiptV1,
]:
    try:
        rebuilt_temporal = RequestUniverseTemporalFieldDenominatorV1.from_canonical_bytes(
            temporal_field_denominator.canonical_bytes
        )
        rebuilt_source = RequestUniverseFinalizationSourceV1.from_canonical_bytes(
            _canonical_bytes(finalization_source.to_dict())
        )
        rebuilt_universe = RequestUniverseV1.from_canonical_bytes(request_universe.canonical_bytes)
        rebuilt_proof = RequestUniverseIndependentProofV1.from_canonical_bytes(
            final_independent_proof.canonical_bytes
        )
        rebuilt_receipt = RequestUniverseIndependentEmptyDeltaReceiptV1.from_canonical_bytes(
            independent_empty_delta_receipt.canonical_bytes
        )
    except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "final request-universe inputs fail strict DTO reconstruction"
        ) from exc
    supplied = (
        temporal_field_denominator,
        finalization_source,
        request_universe,
        final_independent_proof,
        independent_empty_delta_receipt,
    )
    rebuilt = (
        rebuilt_temporal,
        rebuilt_source,
        rebuilt_universe,
        rebuilt_proof,
        rebuilt_receipt,
    )
    if any(
        not _exact_typed_equal(first, second)
        for first, second in zip(supplied, rebuilt, strict=True)
    ):
        raise RequestUniverseSourceAdmissionError(
            "final request-universe inputs differ after strict DTO reconstruction"
        )
    return rebuilt


def compile_request_universe_final_authority_v1(
    *,
    source: RequestUniverseCandidateSourceV1,
    candidate: RequestUniverseCandidateGenerationV1,
    candidate_independent_proof: RequestUniverseCandidateIndependentProofV1,
    source_admission: RequestUniverseSourceAdmissionV1,
    checkpoint_transaction: CheckpointTransaction,
    request_closure_receipt: RequestClosureRuntimeReceipt,
    temporal_field_denominator: RequestUniverseTemporalFieldDenominatorV1,
    finalization_source: RequestUniverseFinalizationSourceV1,
    request_universe: RequestUniverseV1,
    final_independent_proof: RequestUniverseIndependentProofV1,
    independent_empty_delta_receipt: RequestUniverseIndependentEmptyDeltaReceiptV1,
) -> RequestUniverseFinalAuthorityV1:
    """Join primary and independent fixed-point evidence without provider access."""

    from nbadb.orchestrate.checkpoint_contract import (
        CheckpointState,
    )
    from nbadb.orchestrate.checkpoint_contract import (
        CheckpointTransaction as RuntimeCheckpointTransaction,
    )
    from nbadb.orchestrate.request_closure_runtime import (
        RequestClosureRuntimeReceipt as RuntimeRequestClosureReceipt,
    )

    exact_types = (
        (source, RequestUniverseCandidateSourceV1, "source"),
        (candidate, RequestUniverseCandidateGenerationV1, "candidate"),
        (
            candidate_independent_proof,
            RequestUniverseCandidateIndependentProofV1,
            "candidate_independent_proof",
        ),
        (source_admission, RequestUniverseSourceAdmissionV1, "source_admission"),
        (
            checkpoint_transaction,
            RuntimeCheckpointTransaction,
            "checkpoint_transaction",
        ),
        (
            request_closure_receipt,
            RuntimeRequestClosureReceipt,
            "request_closure_receipt",
        ),
        (
            temporal_field_denominator,
            RequestUniverseTemporalFieldDenominatorV1,
            "temporal_field_denominator",
        ),
        (
            finalization_source,
            RequestUniverseFinalizationSourceV1,
            "finalization_source",
        ),
        (request_universe, RequestUniverseV1, "request_universe"),
        (
            final_independent_proof,
            RequestUniverseIndependentProofV1,
            "final_independent_proof",
        ),
        (
            independent_empty_delta_receipt,
            RequestUniverseIndependentEmptyDeltaReceiptV1,
            "independent_empty_delta_receipt",
        ),
    )
    for value, expected_type, label in exact_types:
        if type(value) is not expected_type:
            raise RequestUniverseSourceAdmissionError(f"{label} must be the exact contract DTO")
    try:
        rebuilt_checkpoint = RuntimeCheckpointTransaction.from_dict(
            checkpoint_transaction.to_dict()
        )
        rebuilt_closure = RuntimeRequestClosureReceipt.from_canonical_bytes(
            request_closure_receipt.canonical_bytes
        )
    except (AttributeError, KeyError, RecursionError, TypeError, ValueError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "typed upstream authorities fail exact replay"
        ) from exc
    if not _exact_typed_equal(checkpoint_transaction, rebuilt_checkpoint) or not _exact_typed_equal(
        request_closure_receipt, rebuilt_closure
    ):
        raise RequestUniverseSourceAdmissionError(
            "typed upstream authorities differ after exact replay"
        )
    checkpoint_transaction = rebuilt_checkpoint
    request_closure_receipt = rebuilt_closure
    if (
        checkpoint_transaction.state is not CheckpointState.COMMITTED
        or checkpoint_transaction.build is None
        or checkpoint_transaction.receipt is None
    ):
        raise RequestUniverseSourceAdmissionError(
            "final request authority requires a committed checkpoint transaction"
        )
    admitted = validate_request_universe_source_admission_v1(
        observed=source_admission,
        source=source,
        candidate=candidate,
        independent_proof=candidate_independent_proof,
    )
    (
        temporal_field_denominator,
        finalization_source,
        request_universe,
        final_independent_proof,
        independent_empty_delta_receipt,
    ) = _strict_final_authority_inputs(
        temporal_field_denominator=temporal_field_denominator,
        finalization_source=finalization_source,
        request_universe=request_universe,
        final_independent_proof=final_independent_proof,
        independent_empty_delta_receipt=independent_empty_delta_receipt,
    )
    if source.unintegrated_cume_values:
        raise RequestUniverseSourceAdmissionError(
            "unintegrated cumulative values forbid final request authority"
        )
    if (
        len(candidate.blockers) != 1
        or candidate.blockers[0].blocker_code != "candidate_not_fixed_point"
    ):
        raise RequestUniverseSourceAdmissionError(
            "candidate retains an unresolved denominator or workload blocker"
        )
    checkpoint_identity_sha256 = _canonical_sha256(checkpoint_transaction.identity.to_dict())
    w2_authority = checkpoint_transaction.build.w2_authority
    request_closure_sha256 = request_closure_receipt.artifact_sha256
    if (
        w2_authority.expected_call_count != len(candidate.logical_calls)
        or w2_authority.expected_call_inventory_sha256 != candidate.logical_call_inventory_sha256
    ):
        raise RequestUniverseSourceAdmissionError(
            "committed checkpoint W2 authority differs from the logical denominator"
        )
    if request_closure_receipt.green is not True:
        raise RequestUniverseSourceAdmissionError(
            "request-closure runtime receipt is not independently terminal"
        )
    expected_temporal = RequestUniverseTemporalFieldDenominatorV1.build(
        candidate=candidate,
        checkpoint_identity_sha256=checkpoint_identity_sha256,
        request_closure_receipt_sha256=request_closure_sha256,
        w2_authority_identity_sha256=w2_authority.identity_sha256,
    )
    if not _exact_typed_equal(temporal_field_denominator, expected_temporal):
        raise RequestUniverseSourceAdmissionError(
            "temporal-field denominator differs from typed upstream authorities"
        )
    expected_bindings = {
        "authority_generation_sha256": source.authority_generation_sha256,
        "checkpoint_identity_sha256": checkpoint_identity_sha256,
        "request_closure_receipt_sha256": request_closure_sha256,
        "w2_authority_identity_sha256": w2_authority.identity_sha256,
        "candidate_source_sha256": source.source_inputs_sha256,
        "candidate_generation_sha256": candidate.identity_sha256,
        "candidate_independent_proof_sha256": candidate_independent_proof.identity_sha256,
        "source_admission_sha256": admitted.admission_sha256,
        "temporal_field_denominator_sha256": temporal_field_denominator.receipt_sha256,
    }
    if any(
        getattr(finalization_source, field_name) != expected
        for field_name, expected in expected_bindings.items()
    ):
        raise RequestUniverseSourceAdmissionError(
            "finalization source is stale or foreign to the candidate authorities"
        )
    if (
        finalization_source.logical_calls != source.logical_calls
        or finalization_source.logical_calls != candidate.logical_calls
    ):
        raise RequestUniverseSourceAdmissionError(
            "final logical request denominator differs from the admitted candidate"
        )
    from nbadb.core.nba_api_request_surface import materialize_provider_request

    authorities = _current_authorities()
    route_contracts = authorities["routes"].by_route_id
    request_surface = authorities["request"]
    members_by_call: dict[str, list[RouteRequestMemberV1]] = {}
    for member in source.route_members:
        members_by_call.setdefault(member.physical_call_id, []).append(member)
    expected_provider_requests: dict[str, tuple[str, tuple[str, ...]]] = {}
    expected_route_ids_by_provider_request: dict[str, set[str]] = {}
    for call in source.logical_calls:
        members = members_by_call[call.physical_call_id]
        current_routes = tuple(route_contracts[member.route_id] for member in members)
        source_families = {route.source_family for route in current_routes}
        provider_endpoint_ids = {route.provider_endpoint_id for route in current_routes}
        if source_families == {"static"}:
            raise RequestUniverseSourceAdmissionError(
                "static request finality requires its typed static closure authority"
            )
        if len(source_families) != 1 or len(provider_endpoint_ids) != 1:
            raise RequestUniverseSourceAdmissionError(
                "logical call maps to an ambiguous provider request authority"
            )
        source_family = next(iter(source_families))
        endpoint_id = next(iter(provider_endpoint_ids))
        endpoint = request_surface.endpoint(source_family, endpoint_id)
        provider_request = materialize_provider_request(
            endpoint,
            dict(call.parameter_items),
            request_surface_sha256=request_surface.surface_sha256,
            runtime_contract_payload_sha256=(request_surface.runtime_contract_payload_sha256),
        )
        expected_provider_requests[call.physical_call_id] = (
            provider_request.provider_request_sha256,
            tuple(sorted(member.route_id for member in members)),
        )
        expected_route_ids_by_provider_request.setdefault(
            provider_request.provider_request_sha256,
            set(),
        ).update(member.route_id for member in members)
    closure_fixed_point_provider_requests = tuple(
        request_closure_receipt.closure.iterations[-1].output_units
    )
    observation_generation = finalization_source.committed_observation_generation
    committed_fixed_point_provider_requests = (
        observation_generation.closure_fixed_point_provider_request_sha256s
    )
    expected_provider_request_set = {
        provider_request_sha256
        for provider_request_sha256, _route_ids in expected_provider_requests.values()
    }
    if (
        closure_fixed_point_provider_requests != committed_fixed_point_provider_requests
        or set(closure_fixed_point_provider_requests) != expected_provider_request_set
    ):
        raise RequestUniverseSourceAdmissionError(
            "committed observation generation differs from the typed closure fixed point"
        )
    observations_by_request: dict[str, list[Any]] = {}
    for observation in request_closure_receipt.observations:
        observations_by_request.setdefault(
            observation.provider_request_sha256,
            [],
        ).append(observation)
    terminal_evidence = {
        item.physical_call_id: item
        for item in finalization_source.committed_observation_generation.terminal_evidence
    }
    if set(terminal_evidence) != {item.physical_call_id for item in source.logical_calls}:
        raise RequestUniverseSourceAdmissionError(
            "committed observation evidence differs from the exact request denominator"
        )
    observed_provider_requests: set[str] = set()
    for call in source.logical_calls:
        evidence = terminal_evidence[call.physical_call_id]
        provider_request_sha256, route_ids = expected_provider_requests[call.physical_call_id]
        matches = observations_by_request.get(provider_request_sha256, [])
        if len(matches) != 1:
            raise RequestUniverseSourceAdmissionError(
                "request-closure receipt lacks one exact observation per provider request"
            )
        observation = matches[0]
        observed_provider_requests.add(provider_request_sha256)
        if (
            evidence.source_family != call.source_family
            or evidence.endpoint_name != call.endpoint_name
            or evidence.request_call != call
            or evidence.provider_request_sha256 != provider_request_sha256
            or evidence.request_observation_sha256 != _canonical_sha256(observation.to_dict())
            or tuple(observation.route_ids)
            != tuple(sorted(expected_route_ids_by_provider_request[provider_request_sha256]))
        ):
            raise RequestUniverseSourceAdmissionError(
                "typed terminal evidence is rebound from its request-closure observation"
            )
        if evidence.disposition.value.startswith("captured_"):
            expected_disposition = (
                "captured_nonempty"
                if observation.state == "success_nonempty"
                else "captured_present_empty"
                if observation.state == "success_empty"
                else None
            )
            if (
                expected_disposition != evidence.disposition.value
                or evidence.captured_row_count != observation.total_result_rows
                or evidence.result_receipt_count != len(observation.result_sets)
                or evidence.staging_receipt_count != len(observation.staging_receipts)
                or evidence.result_receipt_inventory_sha256
                != _canonical_sha256([item.to_dict() for item in observation.result_sets])
                or evidence.staging_receipt_inventory_sha256
                != _canonical_sha256([item.to_dict() for item in observation.staging_receipts])
            ):
                raise RequestUniverseSourceAdmissionError(
                    "typed capture evidence differs from exact row/result/staging receipts"
                )
        else:
            unavailable = observation.upstream_unavailable_evidence
            support = None if unavailable is None else unavailable.support_authority
            if (
                observation.state != "upstream_unavailable"
                or unavailable is None
                or support is None
                or evidence.typed_upstream_unavailable_evidence_sha256
                != unavailable.unavailable_evidence_sha256
                or evidence.upstream_support_authority_sha256 != support.support_binding_sha256
                or evidence.safe_probe_receipt_sha256 != support.support_cell_sha256
                or evidence.unavailable_reason_code != support.reason_code
                or evidence.validity_scope_start != support.scope_sha256
                or evidence.validity_scope_end != support.scope_sha256
                or evidence.independent_verifier_id != support.independent_verifier_id
                or evidence.independent_verifier_sha256 != support.independent_verifier_sha256
                or evidence.revalidation_policy != "on_authority_or_scope_change"
            ):
                raise RequestUniverseSourceAdmissionError(
                    "typed upstream-unavailable evidence differs from exact support authority"
                )
    if observed_provider_requests != set(observations_by_request):
        raise RequestUniverseSourceAdmissionError(
            "request-closure receipt contains extra or foreign observations"
        )
    try:
        expected_universe = compile_request_universe_v1(finalization_source)
        expected_proof, expected_independent_receipt = verify_request_universe_v1_independently(
            finalization_source_payload=finalization_source.to_dict(),
            request_universe_payload=request_universe.to_dict(),
            request_closure_payload=request_closure_receipt.to_dict(),
        )
    except (RecursionError, TypeError, ValueError) as exc:
        raise RequestUniverseSourceAdmissionError(
            "final request-universe compilers rejected the supplied evidence"
        ) from exc
    if not _exact_typed_equal(request_universe, expected_universe):
        raise RequestUniverseSourceAdmissionError(
            "primary request universe differs from final source recompilation"
        )
    if not _exact_typed_equal(final_independent_proof, expected_proof) or not _exact_typed_equal(
        independent_empty_delta_receipt,
        expected_independent_receipt,
    ):
        raise RequestUniverseSourceAdmissionError(
            "independent final proof or empty-delta receipt differs"
        )
    primary_receipt = request_universe.primary_empty_delta_receipt
    agreement = (
        primary_receipt.authority_generation_sha256
        == independent_empty_delta_receipt.authority_generation_sha256
        == request_universe.authority_generation_sha256
        and primary_receipt.finalization_source_sha256
        == independent_empty_delta_receipt.finalization_source_sha256
        == request_universe.finalization_source_sha256
        and primary_receipt.committed_observation_generation_sha256
        == independent_empty_delta_receipt.committed_observation_generation_sha256
        == request_universe.committed_observation_generation_sha256
        and primary_receipt.logical_call_inventory_sha256
        == independent_empty_delta_receipt.logical_call_inventory_sha256
        == request_universe.logical_call_inventory_sha256
        and primary_receipt.logical_call_count
        == independent_empty_delta_receipt.logical_call_count
        == len(request_universe.logical_calls)
        and primary_receipt.derivation_input_sha256
        == independent_empty_delta_receipt.derivation_input_sha256
        == finalization_source.committed_observation_generation.generation_sha256
        and primary_receipt.admitted_call_inventory_sha256
        == independent_empty_delta_receipt.admitted_call_inventory_sha256
        == request_universe.logical_call_inventory_sha256
        and primary_receipt.derived_call_inventory_sha256
        == independent_empty_delta_receipt.derived_call_inventory_sha256
        == (
            finalization_source.committed_observation_generation.next_generation_call_inventory_sha256
        )
        and primary_receipt.derived_call_count
        == independent_empty_delta_receipt.derived_call_count
        == len(finalization_source.committed_observation_generation.next_generation_calls)
        and primary_receipt.delta_inventory_sha256
        == independent_empty_delta_receipt.delta_inventory_sha256
        == canonical_request_universe_sha256([])
        and primary_receipt.delta_count == independent_empty_delta_receipt.delta_count == 0
        and final_independent_proof.request_universe_sha256
        == independent_empty_delta_receipt.request_universe_sha256
        == request_universe.identity_sha256
        and final_independent_proof.proof_sha256
        == independent_empty_delta_receipt.independent_proof_sha256
    )
    if not agreement:
        raise RequestUniverseSourceAdmissionError(
            "primary and independent compilers disagree on the fixed point"
        )
    body: dict[str, object] = {
        "schema_version": REQUEST_UNIVERSE_FINAL_AUTHORITY_SCHEMA_VERSION,
        "kind": RequestUniverseFinalAuthorityV1.kind,
        "authority_generation_sha256": request_universe.authority_generation_sha256,
        "candidate_source_sha256": source.source_inputs_sha256,
        "candidate_generation_sha256": candidate.identity_sha256,
        "candidate_independent_proof_sha256": candidate_independent_proof.identity_sha256,
        "source_admission_sha256": admitted.admission_sha256,
        "checkpoint_identity_sha256": request_universe.checkpoint_identity_sha256,
        "request_closure_receipt_sha256": (request_universe.request_closure_receipt_sha256),
        "w2_authority_identity_sha256": request_universe.w2_authority_identity_sha256,
        "temporal_field_denominator_sha256": (request_universe.temporal_field_denominator_sha256),
        "committed_observation_generation_sha256": (
            request_universe.committed_observation_generation_sha256
        ),
        "finalization_source_sha256": request_universe.finalization_source_sha256,
        "request_universe_sha256": request_universe.identity_sha256,
        "primary_empty_delta_receipt_sha256": primary_receipt.receipt_sha256,
        "independent_proof_sha256": final_independent_proof.proof_sha256,
        "independent_empty_delta_receipt_sha256": (independent_empty_delta_receipt.receipt_sha256),
        "logical_call_inventory_sha256": request_universe.logical_call_inventory_sha256,
        "terminal_classification_inventory_sha256": (
            request_universe.terminal_classification_inventory_sha256
        ),
        "shard_inventory_sha256": request_universe.shard_inventory_sha256,
        "logical_call_count": len(request_universe.logical_calls),
        "terminal_classification_count": len(request_universe.terminal_classifications),
        "shard_count": len(request_universe.shards),
        "primary_independent_compilers_equal": True,
        "empty_delta_agreement": True,
        "exact_request_denominator": True,
        "terminal_classification_complete": True,
        "shard_partition_exact": True,
        "least_fixed_point_proven": True,
        "request_universe_terminal": True,
        "overall_release_eligible": False,
    }
    return RequestUniverseFinalAuthorityV1.from_dict(
        {**body, "authority_sha256": _canonical_sha256(body)}
    )


def validate_request_universe_final_authority_v1(
    *,
    observed: RequestUniverseFinalAuthorityV1 | Mapping[str, object] | bytes,
    source: RequestUniverseCandidateSourceV1,
    candidate: RequestUniverseCandidateGenerationV1,
    candidate_independent_proof: RequestUniverseCandidateIndependentProofV1,
    source_admission: RequestUniverseSourceAdmissionV1,
    checkpoint_transaction: CheckpointTransaction,
    request_closure_receipt: RequestClosureRuntimeReceipt,
    temporal_field_denominator: RequestUniverseTemporalFieldDenominatorV1,
    finalization_source: RequestUniverseFinalizationSourceV1,
    request_universe: RequestUniverseV1,
    final_independent_proof: RequestUniverseIndependentProofV1,
    independent_empty_delta_receipt: RequestUniverseIndependentEmptyDeltaReceiptV1,
) -> RequestUniverseFinalAuthorityV1:
    """Recompile the complete W3 authority and reject self-resealed receipts."""

    if type(observed) is RequestUniverseFinalAuthorityV1:
        parsed = RequestUniverseFinalAuthorityV1.from_canonical_bytes(observed.canonical_bytes)
    elif type(observed) is bytes:
        parsed = RequestUniverseFinalAuthorityV1.from_canonical_bytes(observed)
    elif type(observed) is dict:
        parsed = RequestUniverseFinalAuthorityV1.from_dict(observed)
    else:
        raise RequestUniverseSourceAdmissionError(
            "observed final request authority has an unsupported representation"
        )
    expected = compile_request_universe_final_authority_v1(
        source=source,
        candidate=candidate,
        candidate_independent_proof=candidate_independent_proof,
        source_admission=source_admission,
        checkpoint_transaction=checkpoint_transaction,
        request_closure_receipt=request_closure_receipt,
        temporal_field_denominator=temporal_field_denominator,
        finalization_source=finalization_source,
        request_universe=request_universe,
        final_independent_proof=final_independent_proof,
        independent_empty_delta_receipt=independent_empty_delta_receipt,
    )
    if parsed != expected:
        raise RequestUniverseSourceAdmissionError(
            "observed final request authority differs from exact recompilation"
        )
    return expected
