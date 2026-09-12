"""Production adapter from Raw Authority V2 to central public-value ownership.

The adapter is the sole layer allowed to join the exact Raw Authority V2
bundle with the three public value relations.  It rebuilds bundle-scoped unit,
assignment, partition, and binding coordinates; stats/live side coordinates
remain local proof and are never promoted into the central denominator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from typing import Final, Literal, Never, cast

from nbadb.contracts.live_lossless_value_authority import (
    LiveLosslessNodeRecordV1,
    LiveLosslessValueAuthorityError,
    LiveLosslessValueAuthorityReceiptV1,
    LiveLosslessValueAuthorityV1,
)
from nbadb.contracts.lossless_ownership import (
    MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS,
    LosslessObservationOwnershipV1,
    LosslessOwnershipAuthorityV1,
    LosslessOwnershipBindingV1,
    LosslessOwnershipError,
    LosslessOwnershipPartitionV1,
    build_lossless_ownership_authority,
)
from nbadb.contracts.public_value_types import (
    ExpectedValueUnitInventoryV1,
    ExpectedValueUnitV1,
    PublicValueRepresentationKindV1,
    PublicValueSourceInputKindV1,
    PublicValueTypesError,
    ValueRepresentationAssignmentV1,
)
from nbadb.contracts.raw_request_authority import (
    ObservationRouteLandingV2,
    ParserInputObjectV2,
    RawRequestAuthorityBundleV2,
    RawRequestAuthorityError,
    RequestObservationV2,
    ResultOccurrenceV2,
    validate_raw_request_authority_bundle,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellAuthorityError,
    RawResultCellAuthorityReceiptV2,
    validate_raw_result_cell_authority_receipt,
)
from nbadb.contracts.stats_lossless_value_authority import (
    StatsLosslessManifestV1,
    StatsLosslessRecordV1,
    StatsLosslessResultV1,
    StatsLosslessValueAuthorityError,
    StatsLosslessValueAuthorityReceiptV1,
    StatsLosslessValueAuthorityV1,
)

__all__ = [
    "PublicValueAuthorityAdapterError",
    "build_public_value_ownership_authority",
]


_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z")
_RESULT_REPRESENTATIONS: Final = frozenset(
    {
        "rectangular_result_cells_v1",
        "stats_lossless_records_v1",
        "live_lossless_nodes_v1",
    }
)

_SourceOwnerKind = Literal["result_occurrence", "response_residual"]


class PublicValueAuthorityAdapterError(ValueError):
    """One public-value input cannot form the exact central ownership closure."""


def _fail(message: str) -> Never:
    raise PublicValueAuthorityAdapterError(message)


def _exact_sha256(value: object, *, label: str) -> str:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be one lowercase full SHA-256")
    return value


def _observation_semantic_key(observation: RequestObservationV2) -> tuple[object, ...]:
    attempt = observation.attempt
    page_discriminator = 0 if attempt.page_ordinal is None else 1
    page_ordinal = 0 if attempt.page_ordinal is None else attempt.page_ordinal
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        attempt.provider_call_ordinal,
        page_discriminator,
        page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        attempt.retry_ordinal,
        attempt.request_ordinal,
    )


def _ordered_selected_observations(
    bundle: RawRequestAuthorityBundleV2,
) -> tuple[RequestObservationV2, ...]:
    selected = tuple(
        observation
        for observation in bundle.observations
        if observation.lifecycle == "selected_terminal"
    )
    if len(selected) > MAX_LOSSLESS_OWNERSHIP_OBSERVATIONS:
        _fail("selected public-value observation inventory exceeds its bound")
    semantic_owners: dict[tuple[object, ...], str] = {}
    for observation in selected:
        key = _observation_semantic_key(observation)
        prior = semantic_owners.get(key)
        if prior is not None and prior != observation.attempt.observation_sha256:
            _fail("selected observations collide on semantic order coordinates")
        semantic_owners[key] = observation.attempt.observation_sha256
    return tuple(
        sorted(
            selected,
            key=lambda item: (
                *_observation_semantic_key(item),
                item.attempt.observation_sha256,
            ),
        )
    )


def _index_occurrences_by_observation(
    observations: tuple[RequestObservationV2, ...],
    occurrences: tuple[ResultOccurrenceV2, ...],
) -> dict[str, tuple[ResultOccurrenceV2, ...]]:
    indexed: dict[str, list[ResultOccurrenceV2 | None]] = {
        observation.attempt.observation_sha256: [None] * observation.result_occurrence_count
        for observation in observations
    }
    for occurrence in occurrences:
        owned = indexed.get(occurrence.observation_sha256)
        if owned is not None:
            ordinal = occurrence.occurrence_ordinal
            if ordinal < 0 or ordinal >= len(owned) or owned[ordinal] is not None:
                _fail("selected occurrence index is duplicate or outside its Raw V2 denominator")
            owned[ordinal] = occurrence
    result: dict[str, tuple[ResultOccurrenceV2, ...]] = {}
    for observation in observations:
        observation_sha256 = observation.attempt.observation_sha256
        owned = indexed[observation_sha256]
        if any(item is None for item in owned):
            _fail("selected occurrence index differs from its Raw V2 denominator")
        result[observation_sha256] = tuple(cast("ResultOccurrenceV2", item) for item in owned)
    return result


def _index_landings_by_observation(
    observations: tuple[RequestObservationV2, ...],
    landings: tuple[ObservationRouteLandingV2, ...],
) -> dict[str, tuple[ObservationRouteLandingV2, ...]]:
    indexed: dict[str, list[ObservationRouteLandingV2 | None]] = {
        observation.attempt.observation_sha256: [None] * observation.route_landing_count
        for observation in observations
    }
    for landing in landings:
        owned = indexed.get(landing.observation_sha256)
        if owned is not None:
            ordinal = landing.route_ordinal
            if ordinal < 0 or ordinal >= len(owned) or owned[ordinal] is not None:
                _fail("selected landing index is duplicate or outside its Raw V2 denominator")
            owned[ordinal] = landing
    result: dict[str, tuple[ObservationRouteLandingV2, ...]] = {}
    for observation in observations:
        observation_sha256 = observation.attempt.observation_sha256
        owned = indexed[observation_sha256]
        if any(item is None for item in owned):
            _fail("selected landing index differs from its Raw V2 denominator")
        result[observation_sha256] = tuple(
            cast("ObservationRouteLandingV2", item) for item in owned
        )
    return result


def _index_parser_inputs_by_object_sha(
    objects: tuple[ParserInputObjectV2, ...],
) -> dict[str, ParserInputObjectV2]:
    indexed: dict[str, ParserInputObjectV2] = {}
    for item in objects:
        if type(item) is not ParserInputObjectV2:
            _fail("Raw parser-input object index contains a foreign exact type")
        if item.object_sha256 in indexed:
            _fail("Raw parser-input object index duplicates one physical identity")
        indexed[item.object_sha256] = item
    return indexed


def _source_input_kind(observation: RequestObservationV2) -> PublicValueSourceInputKindV1:
    if observation.body_disposition == "public_parser_input":
        return "parser_input_body"
    if observation.body_disposition == "declared_bodyless":
        return "declared_bodyless_packet"
    _fail("selected observation lacks an exact public parser-input or bodyless source")


def _occurrence_representation(
    *,
    observation: RequestObservationV2,
    occurrence: ResultOccurrenceV2,
) -> PublicValueRepresentationKindV1:
    source_family = observation.attempt.source_family
    disposition = occurrence.landing_disposition
    if source_family in {"stats", "static"} and disposition == "wide_only":
        return "rectangular_result_cells_v1"
    if source_family == "stats" and disposition in {
        "lossless_only",
        "wide_plus_lossless",
    }:
        return "stats_lossless_records_v1"
    if source_family == "live" and disposition in {
        "wide_only",
        "lossless_only",
        "wide_plus_lossless",
    }:
        return "live_lossless_nodes_v1"
    _fail("selected occurrence has no closed public-value representation")


def _preflight_stats_authority_children(value: StatsLosslessValueAuthorityV1) -> None:
    if (
        type(value.receipt) is not StatsLosslessValueAuthorityReceiptV1
        or type(value.manifest) is not StatsLosslessManifestV1
        or type(value.expected_unit_inventory) is not ExpectedValueUnitInventoryV1
        or type(value.representation_assignments) is not tuple
        or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in value.representation_assignments
        )
        or type(value.results) is not tuple
        or any(type(item) is not StatsLosslessResultV1 for item in value.results)
        or type(value.records) is not tuple
        or any(type(item) is not StatsLosslessRecordV1 for item in value.records)
    ):
        _fail("stats-lossless authority contains a foreign exact child type")


def _preflight_live_authority_children(value: LiveLosslessValueAuthorityV1) -> None:
    if (
        type(value.receipt) is not LiveLosslessValueAuthorityReceiptV1
        or type(value.records) is not tuple
        or any(type(item) is not LiveLosslessNodeRecordV1 for item in value.records)
        or type(value.expected_units) is not ExpectedValueUnitInventoryV1
        or type(value.representation_assignments) is not tuple
        or any(
            type(item) is not ValueRepresentationAssignmentV1
            for item in value.representation_assignments
        )
    ):
        _fail("live-lossless authority contains a foreign exact child type")


def _replay_stats_authority(
    value: StatsLosslessValueAuthorityV1,
) -> StatsLosslessValueAuthorityV1:
    _preflight_stats_authority_children(value)
    manifest = StatsLosslessManifestV1.from_row(value.manifest.to_row())
    receipt = StatsLosslessValueAuthorityReceiptV1.from_verified_manifest(manifest)
    return StatsLosslessValueAuthorityV1(
        receipt=receipt,
        manifest=manifest,
        expected_unit_inventory=ExpectedValueUnitInventoryV1.from_row(
            value.expected_unit_inventory.to_row()
        ),
        representation_assignments=tuple(
            ValueRepresentationAssignmentV1.from_row(item.to_row())
            for item in value.representation_assignments
        ),
        results=tuple(StatsLosslessResultV1.from_row(item.to_row()) for item in value.results),
        records=tuple(StatsLosslessRecordV1.from_row(item.to_row()) for item in value.records),
    )


def _replay_live_authority(
    value: LiveLosslessValueAuthorityV1,
) -> LiveLosslessValueAuthorityV1:
    _preflight_live_authority_children(value)
    receipt = LiveLosslessValueAuthorityReceiptV1(
        **{
            item.name: getattr(value.receipt, item.name)
            for item in fields(LiveLosslessValueAuthorityReceiptV1)
        }
    )
    return LiveLosslessValueAuthorityV1(
        receipt=receipt,
        records=tuple(LiveLosslessNodeRecordV1.from_row(item.to_row()) for item in value.records),
        expected_units=ExpectedValueUnitInventoryV1.from_row(value.expected_units.to_row()),
        representation_assignments=tuple(
            ValueRepresentationAssignmentV1.from_row(item.to_row())
            for item in value.representation_assignments
        ),
    )


@dataclass(frozen=True, slots=True)
class _SourceRecord:
    source_record_sha256: str
    owner_kind: _SourceOwnerKind
    occurrence_sha256: str | None
    representation_kind: PublicValueRepresentationKindV1


def _unit_assignment_vector(
    units: tuple[ExpectedValueUnitV1, ...],
    assignments: tuple[ValueRepresentationAssignmentV1, ...],
) -> tuple[tuple[object, ...], ...]:
    if len(units) != len(assignments):
        _fail("side authority unit and assignment denominators differ")
    vector: list[tuple[object, ...]] = []
    for unit, assignment in zip(units, assignments, strict=True):
        try:
            assignment.validate_for_unit(unit)
        except PublicValueTypesError:
            _fail("side authority assignment differs from its exact unit")
        vector.append(
            (
                unit.observation_sha256,
                unit.unit_kind,
                unit.occurrence_sha256,
                unit.occurrence_ordinal,
                assignment.source_input_kind,
                assignment.representation_kind,
            )
        )
    return tuple(vector)


def _stats_source_records(
    authority: StatsLosslessValueAuthorityV1,
) -> tuple[_SourceRecord, ...]:
    return tuple(
        _SourceRecord(
            source_record_sha256=record.record_sha256,
            owner_kind=record.owner_kind,
            occurrence_sha256=record.occurrence_sha256,
            representation_kind=cast("PublicValueRepresentationKindV1", record.representation_kind),
        )
        for record in authority.records
    )


def _live_source_record_index(
    authority: LiveLosslessValueAuthorityV1,
) -> dict[str, tuple[_SourceRecord, ...]]:
    indexed: dict[str, list[_SourceRecord]] = {}
    for record in authority.records:
        indexed.setdefault(record.observation_sha256, []).append(
            _SourceRecord(
                source_record_sha256=record.source_item_sha256,
                owner_kind=record.ownership_kind,
                occurrence_sha256=record.raw_occurrence_sha256,
                representation_kind=cast(
                    "PublicValueRepresentationKindV1",
                    record.representation_kind,
                ),
            )
        )
    return {observation_sha256: tuple(records) for observation_sha256, records in indexed.items()}


def _result_cell_source_index(
    cells: tuple[RawNbaApiResultCellV2, ...],
) -> dict[str, tuple[_SourceRecord, ...]]:
    indexed: dict[str, list[_SourceRecord]] = {}
    for cell in cells:
        indexed.setdefault(cell.occurrence_sha256, []).append(
            _SourceRecord(
                source_record_sha256=cell.cell_sha256,
                owner_kind="result_occurrence",
                occurrence_sha256=cell.occurrence_sha256,
                representation_kind="rectangular_result_cells_v1",
            )
        )
    return {occurrence_sha256: tuple(records) for occurrence_sha256, records in indexed.items()}


def _source_owner_index(
    records: tuple[_SourceRecord, ...],
) -> dict[tuple[_SourceOwnerKind, str | None], tuple[_SourceRecord, ...]]:
    indexed: dict[tuple[_SourceOwnerKind, str | None], list[_SourceRecord]] = {}
    for record in records:
        indexed.setdefault((record.owner_kind, record.occurrence_sha256), []).append(record)
    return {owner: tuple(owned) for owner, owned in indexed.items()}


def _validate_stats_authority_join(
    *,
    authority: StatsLosslessValueAuthorityV1,
    bundle_sha256: str,
    observation: RequestObservationV2,
    occurrences: tuple[ResultOccurrenceV2, ...],
    conditional_landing: ObservationRouteLandingV2,
    parser_input_sha256: str,
) -> None:
    manifest = authority.manifest
    if (
        manifest.raw_authority_bundle_sha256 != bundle_sha256
        or manifest.observation_record_sha256 != observation.observation_record_sha256
        or manifest.observation_sha256 != observation.attempt.observation_sha256
        or manifest.provider_authority_sha256 != observation.attempt.provider_authority_sha256
        or manifest.endpoint_contract_sha256 != observation.attempt.endpoint_contract_sha256
        or manifest.parameters_sha256 != observation.attempt.safe_parameters_sha256
        or manifest.endpoint_id != observation.attempt.endpoint_id
        or manifest.response_receipt_sha256 != observation.capture_response_receipt_sha256
        or manifest.route_id != conditional_landing.route_id
        or manifest.route_authority_sha256 != conditional_landing.route_authority_sha256
        or manifest.committed_receipt_sha256 != conditional_landing.receipt_root_sha256
    ):
        _fail("stats-lossless authority differs from its exact Raw observation")
    expected_occurrence_sha256s = tuple(
        item.occurrence_sha256
        for item in occurrences
        if _occurrence_representation(observation=observation, occurrence=item)
        == "stats_lossless_records_v1"
    )
    if tuple(item.occurrence_sha256 for item in authority.results) != (expected_occurrence_sha256s):
        _fail("stats-lossless authority occurrence denominator differs from Raw V2")
    if any(item.parser_input_sha256 != parser_input_sha256 for item in authority.records):
        _fail("stats-lossless authority differs from its exact Raw parser input")
    expected_occurrence_set = set(expected_occurrence_sha256s)
    if any(
        (
            item.owner_kind == "result_occurrence"
            and item.occurrence_sha256 not in expected_occurrence_set
        )
        or (item.owner_kind == "response_residual" and item.occurrence_sha256 is not None)
        for item in authority.records
    ):
        _fail("stats-lossless source record belongs to a foreign Raw owner")


def _validate_live_authority_join(
    *,
    authority: LiveLosslessValueAuthorityV1,
    bundle_sha256: str,
    observations: tuple[RequestObservationV2, ...],
    occurrences_by_observation: dict[str, tuple[ResultOccurrenceV2, ...]],
) -> None:
    if authority.receipt.raw_authority_bundle_sha256 != bundle_sha256:
        _fail("live-lossless authority differs from its exact Raw bundle")
    live_observations = tuple(item for item in observations if item.attempt.source_family == "live")
    if authority.receipt.selected_observation_count != len(live_observations):
        _fail("live-lossless selected-observation denominator differs from Raw V2")
    record_observation_order: list[str] = []
    completed_record_observations: set[str] = set()
    for record in authority.records:
        if (
            not record_observation_order
            or record_observation_order[-1] != record.observation_sha256
        ):
            if record.observation_sha256 in completed_record_observations:
                _fail("live-lossless records reopen a completed observation")
            completed_record_observations.add(record.observation_sha256)
            record_observation_order.append(record.observation_sha256)
    live_observation_positions = {
        item.attempt.observation_sha256: ordinal for ordinal, item in enumerate(live_observations)
    }
    prior_record_observation_position = -1
    for observation_sha256 in record_observation_order:
        record_observation_position = live_observation_positions.get(observation_sha256)
        if (
            record_observation_position is None
            or record_observation_position <= prior_record_observation_position
        ):
            _fail("live-lossless observation order differs from Raw V2")
        prior_record_observation_position = record_observation_position
    by_observation = {item.attempt.observation_sha256: item for item in live_observations}
    for record in authority.records:
        observation = by_observation.get(record.observation_sha256)
        if (
            observation is None
            or record.observation_record_sha256 != observation.observation_record_sha256
        ):
            _fail("live-lossless source record belongs to a foreign Raw observation")
    side_occurrences = tuple(
        unit.occurrence_sha256
        for unit in authority.expected_units.units
        if unit.unit_kind == "result_occurrence"
    )
    expected_occurrences = tuple(
        occurrence.occurrence_sha256
        for observation in live_observations
        for occurrence in occurrences_by_observation[observation.attempt.observation_sha256]
    )
    if side_occurrences != expected_occurrences:
        _fail("live-lossless occurrence denominator differs from Raw V2")


def _build_authority(
    *,
    bundle: RawRequestAuthorityBundleV2,
    observations: tuple[RequestObservationV2, ...],
    occurrences_by_observation: dict[str, tuple[ResultOccurrenceV2, ...]],
    landings_by_observation: dict[str, tuple[ObservationRouteLandingV2, ...]],
    result_cells: tuple[RawNbaApiResultCellV2, ...],
    stats_by_observation: dict[str, StatsLosslessValueAuthorityV1],
    live_authority: LiveLosslessValueAuthorityV1,
) -> LosslessOwnershipAuthorityV1:
    units: list[ExpectedValueUnitV1] = []
    assignments: list[ValueRepresentationAssignmentV1] = []
    ownership_observations: list[LosslessObservationOwnershipV1] = []
    partitions: list[LosslessOwnershipPartitionV1] = []
    bindings: list[LosslessOwnershipBindingV1] = []
    seen_source_records: set[str] = set()
    result_sources_by_occurrence = _result_cell_source_index(result_cells)
    live_sources_by_observation = _live_source_record_index(live_authority)
    live_source_owners_by_observation = {
        observation_sha256: _source_owner_index(records)
        for observation_sha256, records in live_sources_by_observation.items()
    }
    stats_sources_by_observation = {
        observation_sha256: _stats_source_records(authority)
        for observation_sha256, authority in stats_by_observation.items()
    }
    stats_source_owners_by_observation = {
        observation_sha256: _source_owner_index(records)
        for observation_sha256, records in stats_sources_by_observation.items()
    }

    for observation_ordinal, observation in enumerate(observations):
        observation_sha256 = observation.attempt.observation_sha256
        source_input_kind = _source_input_kind(observation)
        occurrences = occurrences_by_observation[observation_sha256]
        stats_authority = stats_by_observation.get(observation_sha256)
        stats_sources = stats_sources_by_observation.get(observation_sha256, ())
        stats_source_owners = stats_source_owners_by_observation.get(observation_sha256, {})
        live_sources = live_sources_by_observation.get(observation_sha256, ())
        live_source_owners = live_source_owners_by_observation.get(observation_sha256, {})

        occurrence_units: dict[str, ExpectedValueUnitV1] = {}
        occurrence_assignments: dict[str, ValueRepresentationAssignmentV1] = {}
        observation_sources: list[_SourceRecord] = []
        for occurrence in occurrences:
            representation_kind = _occurrence_representation(
                observation=observation,
                occurrence=occurrence,
            )
            unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="result_occurrence",
                occurrence_sha256=occurrence.occurrence_sha256,
                occurrence_ordinal=occurrence.occurrence_ordinal,
            )
            assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=unit,
                source_input_kind=source_input_kind,
                representation_kind=representation_kind,
            )
            units.append(unit)
            assignments.append(assignment)
            occurrence_units[occurrence.occurrence_sha256] = unit
            occurrence_assignments[occurrence.occurrence_sha256] = assignment
            if representation_kind == "rectangular_result_cells_v1":
                sources = result_sources_by_occurrence.get(occurrence.occurrence_sha256, ())
            elif representation_kind == "stats_lossless_records_v1":
                sources = stats_source_owners.get(
                    ("result_occurrence", occurrence.occurrence_sha256),
                    (),
                )
            else:
                sources = live_source_owners.get(
                    ("result_occurrence", occurrence.occurrence_sha256),
                    (),
                )
            if any(item.representation_kind != representation_kind for item in sources):
                _fail("occurrence source rows disagree with the Raw-owned representation")
            observation_sources.extend(sources)

        if observation.attempt.source_family == "live":
            # Live rows have one authoritative physical order that may interleave
            # ownership categories; preserve it rather than grouping by owner.
            observation_sources = list(live_sources)
        response_source_owners = (
            live_source_owners
            if observation.attempt.source_family == "live"
            else stats_source_owners
        )
        residual_sources = response_source_owners.get(("response_residual", None), ())
        if observation.attempt.source_family != "live":
            observation_sources.extend(residual_sources)
        if stats_authority is not None and tuple(observation_sources) != stats_sources:
            _fail("stats-lossless source record inventory is orphaned or reordered")
        if (
            observation.attempt.source_family == "live"
            and tuple(observation_sources) != live_sources
        ):
            _fail("live-lossless source record inventory is orphaned or reordered")

        response_unit: ExpectedValueUnitV1 | None = None
        response_assignment: ValueRepresentationAssignmentV1 | None = None
        fixed_zero_landing_sha256: str | None = None
        response_partition_kind: Literal["response_residual", "response_fixed_zero"]
        if residual_sources:
            response_partition_kind = "response_residual"
            response_unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="response_residual",
            )
            response_assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=response_unit,
                source_input_kind=source_input_kind,
                representation_kind="response_lossless_records_v1",
            )
            units.append(response_unit)
            assignments.append(response_assignment)
        elif occurrences:
            response_partition_kind = "response_residual"
        else:
            response_partition_kind = "response_fixed_zero"
            fixed_landings = tuple(
                item
                for item in landings_by_observation[observation_sha256]
                if item.landing_semantic == "response_fixed_zero"
            )
            if len(fixed_landings) != 1:
                _fail("empty observation lacks one unambiguous fixed-zero Raw landing")
            fixed_landing = fixed_landings[0]
            if fixed_landing.source_occurrence_count != 0 or fixed_landing.persisted_row_count != 0:
                _fail("fixed-zero Raw landing contradicts its exact empty proof")
            fixed_zero_landing_sha256 = fixed_landing.landing_sha256
            response_unit = ExpectedValueUnitV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                unit_ordinal=len(units),
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                unit_kind="response_fixed_zero",
            )
            response_assignment = ValueRepresentationAssignmentV1.build(
                expected_unit=response_unit,
                source_input_kind=source_input_kind,
                representation_kind="response_fixed_zero_v1",
            )
            units.append(response_unit)
            assignments.append(response_assignment)

        first_partition_ordinal = len(partitions)
        partition_ordinal_by_owner: dict[tuple[str, str | None], int] = {}
        for occurrence in occurrences:
            partition_ordinal_by_owner[("result_occurrence", occurrence.occurrence_sha256)] = len(
                partitions
            ) + len(partition_ordinal_by_owner)
        response_partition_ordinal = len(partitions) + len(occurrences)
        partition_ordinal_by_owner[("response_residual", None)] = response_partition_ordinal

        observation_bindings: list[LosslessOwnershipBindingV1] = []
        observation_bindings_by_partition: dict[int, list[LosslessOwnershipBindingV1]] = {}
        for observation_record_ordinal, source in enumerate(observation_sources):
            if source.source_record_sha256 in seen_source_records:
                _fail("public source relations duplicate one source-record identity")
            seen_source_records.add(source.source_record_sha256)
            if source.owner_kind == "result_occurrence":
                occurrence_sha256 = source.occurrence_sha256
                if occurrence_sha256 is None or occurrence_sha256 not in occurrence_units:
                    _fail("public source row references a foreign result occurrence")
                expected_unit = occurrence_units[occurrence_sha256]
                assignment = occurrence_assignments[occurrence_sha256]
            else:
                if source.occurrence_sha256 is not None:
                    _fail("response-residual source row fabricates occurrence ownership")
                if response_unit is None or response_assignment is None:
                    _fail("positive response residual lacks its mandatory expected unit")
                expected_unit = response_unit
                assignment = response_assignment
            if source.representation_kind != assignment.representation_kind:
                _fail("public source row representation differs from its central assignment")
            binding = LosslessOwnershipBindingV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                binding_ordinal=len(bindings),
                observation_record_ordinal=observation_record_ordinal,
                partition_ordinal=partition_ordinal_by_owner[
                    (source.owner_kind, source.occurrence_sha256)
                ],
                source_record_sha256=source.source_record_sha256,
                expected_unit=expected_unit,
                assignment=assignment,
            )
            bindings.append(binding)
            observation_bindings.append(binding)
            observation_bindings_by_partition.setdefault(binding.partition_ordinal, []).append(
                binding
            )

        observation_partitions: list[LosslessOwnershipPartitionV1] = []
        for occurrence in occurrences:
            expected_unit = occurrence_units[occurrence.occurrence_sha256]
            assignment = occurrence_assignments[occurrence.occurrence_sha256]
            partition_ordinal = partition_ordinal_by_owner[
                ("result_occurrence", occurrence.occurrence_sha256)
            ]
            owned = tuple(observation_bindings_by_partition.get(partition_ordinal, ()))
            partition = LosslessOwnershipPartitionV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                partition_ordinal=partition_ordinal,
                observation_partition_ordinal=len(observation_partitions),
                partition_kind="result_occurrence",
                bindings=owned,
                expected_unit=expected_unit,
                assignment=assignment,
            )
            partitions.append(partition)
            observation_partitions.append(partition)

        response_owned = tuple(
            observation_bindings_by_partition.get(response_partition_ordinal, ())
        )
        response_partition = LosslessOwnershipPartitionV1.build(
            raw_authority_bundle_sha256=bundle.bundle_sha256,
            observation_record_sha256=observation.observation_record_sha256,
            observation_sha256=observation_sha256,
            observation_ordinal=observation_ordinal,
            partition_ordinal=response_partition_ordinal,
            observation_partition_ordinal=len(observation_partitions),
            partition_kind=response_partition_kind,
            bindings=response_owned,
            expected_unit=response_unit,
            assignment=response_assignment,
            fixed_zero_landing_sha256=fixed_zero_landing_sha256,
        )
        partitions.append(response_partition)
        observation_partitions.append(response_partition)
        if first_partition_ordinal != observation_partitions[0].partition_ordinal:
            _fail("ownership partition allocation drifted")
        ownership_observations.append(
            LosslessObservationOwnershipV1.build(
                raw_authority_bundle_sha256=bundle.bundle_sha256,
                observation_record_sha256=observation.observation_record_sha256,
                observation_sha256=observation_sha256,
                observation_ordinal=observation_ordinal,
                source_input_kind=source_input_kind,
                partitions=tuple(observation_partitions),
                bindings=tuple(observation_bindings),
            )
        )

    inventory = ExpectedValueUnitInventoryV1.build(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        units=tuple(units),
    )
    authority = build_lossless_ownership_authority(
        raw_authority_bundle_sha256=bundle.bundle_sha256,
        expected_unit_inventory=inventory,
        representation_assignments=tuple(assignments),
        observations=tuple(ownership_observations),
        partitions=tuple(partitions),
        bindings=tuple(bindings),
    )

    central_vector = _unit_assignment_vector(
        authority.expected_unit_inventory.units,
        authority.representation_assignments,
    )
    central_vector_by_observation: dict[str, list[tuple[object, ...]]] = {}
    for owner in central_vector:
        central_vector_by_observation.setdefault(cast("str", owner[0]), []).append(owner)
    for stats_authority in stats_by_observation.values():
        observation_sha256 = stats_authority.manifest.observation_sha256
        side_vector = _unit_assignment_vector(
            stats_authority.expected_unit_inventory.units,
            stats_authority.representation_assignments,
        )
        if side_vector != tuple(central_vector_by_observation.get(observation_sha256, ())):
            _fail("stats-lossless side assignments differ from central semantic owners")
    live_observation_sha256s = {
        item.attempt.observation_sha256
        for item in observations
        if item.attempt.source_family == "live"
    }
    if _unit_assignment_vector(
        live_authority.expected_units.units,
        live_authority.representation_assignments,
    ) != tuple(
        item
        for item in central_vector
        if item[0] in live_observation_sha256s and item[1] != "response_fixed_zero"
    ):
        _fail("live-lossless side assignments differ from central semantic owners")
    return authority


def build_public_value_ownership_authority(
    raw_bundle: object,
    *,
    expected_raw_authority_bundle_sha256: str,
    result_cell_authority_receipt: object,
    expected_result_cell_authority_sha256: str,
    stats_lossless_authorities: object,
    expected_stats_lossless_authority_sha256s: tuple[str, ...],
    live_lossless_authority: object,
    expected_live_lossless_authority_receipt_sha256: str,
) -> LosslessOwnershipAuthorityV1:
    """Build one normalized, bundle-scoped public-value ownership authority."""

    # Trust pins and exact outer types are checked before any member inventory
    # is replayed or allocated.
    raw_pin = _exact_sha256(
        expected_raw_authority_bundle_sha256,
        label="expected Raw Authority bundle",
    )
    result_cell_pin = _exact_sha256(
        expected_result_cell_authority_sha256,
        label="expected result-cell authority",
    )
    live_pin = _exact_sha256(
        expected_live_lossless_authority_receipt_sha256,
        label="expected live-lossless authority",
    )
    if type(expected_stats_lossless_authority_sha256s) is not tuple:
        _fail("expected stats-lossless authority pins must be one exact tuple")
    stats_pins = tuple(
        _exact_sha256(item, label="expected stats-lossless authority")
        for item in expected_stats_lossless_authority_sha256s
    )
    if type(raw_bundle) is not RawRequestAuthorityBundleV2:
        _fail("public-value source must be exact Raw Authority V2")
    if type(result_cell_authority_receipt) is not RawResultCellAuthorityReceiptV2:
        _fail("result-cell authority receipt has a foreign DTO type")
    if type(stats_lossless_authorities) is not tuple or any(
        type(item) is not StatsLosslessValueAuthorityV1 for item in stats_lossless_authorities
    ):
        _fail("stats-lossless authority inventory has a foreign exact type")
    if type(live_lossless_authority) is not LiveLosslessValueAuthorityV1:
        _fail("live-lossless authority has a foreign DTO type")

    try:
        if raw_bundle.bundle_sha256 != raw_pin:
            _fail("Raw Authority bundle differs from its external pin")
        if result_cell_authority_receipt.authority_sha256 != result_cell_pin:
            _fail("result-cell authority differs from its external pin")
        for stats_authority in cast(
            "tuple[StatsLosslessValueAuthorityV1, ...]",
            stats_lossless_authorities,
        ):
            _preflight_stats_authority_children(stats_authority)
        _preflight_live_authority_children(live_lossless_authority)
        if live_lossless_authority.receipt.receipt_sha256 != live_pin:
            _fail("live-lossless authority differs from its external pin")
        bundle = validate_raw_request_authority_bundle(raw_bundle)
        bundle.require_complete_terminal_selection()
        result_cell_receipt = validate_raw_result_cell_authority_receipt(
            bundle,
            result_cell_authority_receipt,
        )
        stats_authorities = tuple(
            _replay_stats_authority(item)
            for item in cast(
                "tuple[StatsLosslessValueAuthorityV1, ...]",
                stats_lossless_authorities,
            )
        )
        live_authority = _replay_live_authority(live_lossless_authority)
    except PublicValueAuthorityAdapterError:
        raise
    except (
        LiveLosslessValueAuthorityError,
        LosslessOwnershipError,
        PublicValueTypesError,
        RawRequestAuthorityError,
        RawResultCellAuthorityError,
        StatsLosslessValueAuthorityError,
        AttributeError,
        TypeError,
        ValueError,
        RecursionError,
    ):
        raise PublicValueAuthorityAdapterError(
            "public-value authority input failed exact canonical replay"
        ) from None

    observations = _ordered_selected_observations(bundle)
    occurrences_by_observation = _index_occurrences_by_observation(
        observations,
        bundle.occurrences,
    )
    landings_by_observation = _index_landings_by_observation(
        observations,
        bundle.landings,
    )
    parser_inputs_by_object_sha = _index_parser_inputs_by_object_sha(bundle.objects)
    observation_by_sha = {item.attempt.observation_sha256: item for item in observations}
    expected_stats_observations = tuple(
        observation
        for observation in observations
        if observation.attempt.source_family == "stats"
        and any(
            landing.landing_semantic == "conditional_lossless"
            for landing in landings_by_observation[observation.attempt.observation_sha256]
        )
    )
    stats_by_observation: dict[str, StatsLosslessValueAuthorityV1] = {}
    for authority in stats_authorities:
        observation_sha256 = authority.manifest.observation_sha256
        if observation_sha256 in stats_by_observation:
            _fail("stats-lossless authority inventory duplicates one observation")
        stats_by_observation[observation_sha256] = authority
    expected_stats_sha256s = tuple(
        item.attempt.observation_sha256 for item in expected_stats_observations
    )
    if tuple(stats_by_observation) != expected_stats_sha256s:
        # Accept caller tuple permutation, but never semantic omission/addition.
        if set(stats_by_observation) != set(expected_stats_sha256s):
            _fail("stats-lossless authority denominator differs from Raw V2")
        stats_by_observation = {
            observation_sha256: stats_by_observation[observation_sha256]
            for observation_sha256 in expected_stats_sha256s
        }
    canonical_stats_receipts = tuple(
        item.receipt.authority_sha256 for item in stats_by_observation.values()
    )
    if canonical_stats_receipts != stats_pins:
        _fail("stats-lossless authority sequence differs from its external pins")
    for observation_sha256, authority in stats_by_observation.items():
        observation = observation_by_sha[observation_sha256]
        conditional_landings = tuple(
            item
            for item in landings_by_observation[observation_sha256]
            if item.landing_semantic == "conditional_lossless"
        )
        if len(conditional_landings) != 1:
            _fail("stats-lossless Raw observation lacks one conditional landing")
        body_object_sha256 = observation.body_object_sha256
        parser_input = (
            None
            if body_object_sha256 is None
            else parser_inputs_by_object_sha.get(body_object_sha256)
        )
        if parser_input is None:
            _fail("stats-lossless Raw observation lacks one exact parser input")
        _validate_stats_authority_join(
            authority=authority,
            bundle_sha256=bundle.bundle_sha256,
            observation=observation,
            occurrences=occurrences_by_observation[observation_sha256],
            conditional_landing=conditional_landings[0],
            parser_input_sha256=parser_input.response_sha256,
        )
    _validate_live_authority_join(
        authority=live_authority,
        bundle_sha256=bundle.bundle_sha256,
        observations=observations,
        occurrences_by_observation=occurrences_by_observation,
    )
    return _build_authority(
        bundle=bundle,
        observations=observations,
        occurrences_by_observation=occurrences_by_observation,
        landings_by_observation=landings_by_observation,
        result_cells=result_cell_receipt.public_table_proof.cells,
        stats_by_observation=stats_by_observation,
        live_authority=live_authority,
    )
