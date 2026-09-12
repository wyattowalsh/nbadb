"""Independent raw-byte verifier for transform-output disposition authority.

The verifier accepts one persisted canonical envelope and no caller-owned DTO,
root, count, or verification flag.  It reconstructs every leaf from the raw
JSON graph, recompiles the repository structural authority, replays the exact
source bundle, proves evolution/capability/dependency closure, and invokes the
authority module's private sealed constructor only after those checks pass.

This module authors no disposition and has no filesystem, SQL, extraction, or
publication side effect.  Its sole local file read binds the embedded verifier
source member to the bytes of this implementation currently being executed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Never, cast

from nbadb.contracts import transform_output_disposition_authored as authored_module
from nbadb.contracts import transform_output_disposition_authority as authority_module
from nbadb.contracts import transform_output_disposition_history as history_module
from nbadb.contracts.transform_output_disposition_authored import (
    AuthoredTransformOutputDispositionError,
    CompiledAuthoredTransformOutputDispositionAuthorityV1,
    load_current_transform_output_disposition_authored_authority,
)
from nbadb.contracts.transform_output_disposition_authority import (
    CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND,
    TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND,
    TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION,
    CurrentTransformOutputDispositionV1,
    TransformOutputCapabilityPolicyV1,
    TransformOutputChangeV1,
    TransformOutputDependencyV1,
    TransformOutputDispositionAuthorityError,
    TransformOutputEvidenceReferenceV1,
    TransformOutputRemovedTombstoneV1,
    TransformOutputSemanticClaimV1,
    VerifiedTransformOutputDispositionAuthorityEnvelopeV1,
)
from nbadb.contracts.transform_output_disposition_evidence import (
    DispositionEvidenceError,
    SourceMemberRole,
    TransformOutputDispositionAuditMetadataV1,
    TransformOutputDispositionProofPackV1,
    TransformOutputDispositionSourceMemberV1,
    canonical_json_bytes_v1,
    decode_canonical_json_bytes_v1,
)
from nbadb.contracts.transform_output_disposition_history import (
    TransformOutputDispositionHistoryChainV1,
    TransformOutputDispositionHistoryError,
)
from nbadb.contracts.transform_output_disposition_protected_fields import (
    PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1,
    PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1,
    validate_transform_output_disposition_protected_fields_v1,
)
from nbadb.contracts.transform_output_disposition_structural import (
    TransformOutputDispositionStructuralError,
    TransformOutputStructuralAuthorityV1,
    compile_current_transform_output_structural_authority,
)
from nbadb.contracts.transform_output_staging_input_authority import (
    RegisteredStagingInputContractInventoryV1,
    StagingInputContractAuthorityError,
    compile_registered_staging_input_contract_inventory,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

__all__ = [
    "TransformOutputDispositionVerificationError",
    "verify_transform_output_disposition_envelope",
]

_SCHEMA_VERSION = TRANSFORM_OUTPUT_DISPOSITION_SCHEMA_VERSION
_MAX_ROWS = 65_536

_AUTHORED_ENTRIES_PATH = "transform-output-disposition/authored-entries-v1.json"
_DEPENDENCIES_PATH = "transform-output-disposition/dependencies-v1.json"
_HISTORY_PATH = "transform-output-disposition/prior-or-initial-history-v1.json"
_PROOF_INPUTS_PATH = "transform-output-disposition/proof-inputs-v1.json"
_STAR_PROJECTION_PATH = "transform-output-disposition/star-projection-v1.json"
_STRUCTURAL_DISCOVERY_PATH = "transform-output-disposition/structural-discovery-v1.json"
_VALIDATION_EVIDENCE_PATH = "transform-output-disposition/validation-evidence-v1.json"
_VERIFIER_SOURCE_PATH = "src/nbadb/contracts/transform_output_disposition_verifier.py"

_DEPENDENCIES_KIND = "nbadb_transform_output_disposition_dependencies"
_HISTORY_KIND = "nbadb_transform_output_disposition_history"
_PROOF_INPUTS_KIND = "nbadb_transform_output_disposition_proof_inputs"
_STAR_PROJECTION_KIND = "nbadb_transform_output_disposition_star_projection"
_VALIDATION_CASES_KIND = "nbadb_transform_output_disposition_validation_cases"

_RESULT_DOMAIN = b"nbadb:transform-output-disposition:verified-result:v1"
_STATE_INVENTORY_DOMAIN = b"nbadb:transform-output-disposition:states:v1"
_CAPABILITY_INVENTORY_DOMAIN = b"nbadb:transform-output-disposition:capabilities:v1"
_DEPENDENCY_GRAPH_DOMAIN = b"nbadb:transform-output-disposition:graph:v1"
_TOPOLOGICAL_ORDER_DOMAIN = b"nbadb:transform-output-disposition:topological-order:v1"

_VALIDATION_CASES: tuple[tuple[str, str, str], ...] = (
    ("01-positive-exact-reconstruction", "positive", "exact_reconstruction"),
    ("02-negative-each-missing-entry", "negative", "drop_each_entry"),
    (
        "03-mutation-each-protected-field",
        "mutation",
        "mutate_each_protected_field",
    ),
)


class TransformOutputDispositionVerificationError(TransformOutputDispositionAuthorityError):
    """Raw evidence does not prove one exact disposition envelope."""


def _fail(message: str) -> Never:
    raise TransformOutputDispositionVerificationError(message)


def _domain_sha256(domain: bytes, value: object) -> str:
    digest = hashlib.sha256()
    digest.update(domain)
    digest.update(b"\x00")
    digest.update(canonical_json_bytes_v1(value))
    return digest.hexdigest()


def _mapping(value: object, *, label: str) -> Mapping[str, object]:
    if type(value) is not dict or any(type(key) is not str for key in cast("dict", value)):
        _fail(f"{label} must be one exact string-keyed object")
    return cast("Mapping[str, object]", value)


def _exact_keys(
    payload: Mapping[str, object],
    expected: frozenset[str],
    *,
    label: str,
) -> None:
    actual = frozenset(payload)
    if actual != expected:
        missing = ",".join(sorted(expected - actual))
        unexpected = ",".join(sorted(actual - expected))
        _fail(f"{label} fields differ (missing={missing}; unexpected={unexpected})")


def _schema_identity(payload: Mapping[str, object], *, kind: str, label: str) -> None:
    if type(payload.get("schema_version")) is not int or payload["schema_version"] != 1:
        _fail(f"{label} schema version is invalid")
    if type(payload.get("kind")) is not str or payload["kind"] != kind:
        _fail(f"{label} kind is invalid")


def _array(value: object, *, label: str, allow_empty: bool) -> list[object]:
    if type(value) is not list:
        _fail(f"{label} must be an exact array")
    rows = cast("list[object]", value)
    if (not allow_empty and not rows) or len(rows) > _MAX_ROWS:
        _fail(f"{label} has an invalid row count")
    return rows


def _string(value: object, *, label: str) -> str:
    if type(value) is not str or not value:
        _fail(f"{label} must be one exact nonempty string")
    return value


def _optional_sha256(value: object, *, label: str) -> str | None:
    if value is None:
        return None
    text = _string(value, label=label)
    if len(text) != 64 or any(char not in "0123456789abcdef" for char in text):
        _fail(f"{label} must be null or one lowercase SHA-256")
    return text


def _exact_reconstructed_dict(value: object, rebuilt: object, *, label: str) -> None:
    to_dict = getattr(rebuilt, "to_dict", None)
    if not callable(to_dict) or value != to_dict():
        _fail(f"{label} differs from its exact typed reconstruction")


def _parse_policy(value: object) -> TransformOutputCapabilityPolicyV1:
    payload = _mapping(value, label="capability policy")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "execute",
                "primary_materialize",
                "stable_load",
                "transform_publication",
                "chat_ceiling",
                "policy_sha256",
            }
        ),
        label="capability policy",
    )
    _schema_identity(
        payload,
        kind=TransformOutputCapabilityPolicyV1.kind,
        label="capability policy",
    )
    policy = TransformOutputCapabilityPolicyV1(
        execute=cast("bool", payload["execute"]),
        primary_materialize=cast("bool", payload["primary_materialize"]),
        stable_load=cast("bool", payload["stable_load"]),
        transform_publication=cast("bool", payload["transform_publication"]),
        chat_ceiling=cast("bool", payload["chat_ceiling"]),
    )
    _exact_reconstructed_dict(value, policy, label="capability policy")
    return policy


def _parse_semantic_claim(value: object) -> TransformOutputSemanticClaimV1:
    payload = _mapping(value, label="semantic claim")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "claim_id",
                "claim_kind",
                "claim_sha256",
                "evidence_sha256s",
            }
        ),
        label="semantic claim",
    )
    _schema_identity(
        payload,
        kind=TransformOutputSemanticClaimV1.kind,
        label="semantic claim",
    )
    evidence = _array(
        payload["evidence_sha256s"],
        label="semantic claim evidence_sha256s",
        allow_empty=False,
    )
    claim = TransformOutputSemanticClaimV1(
        claim_id=cast("str", payload["claim_id"]),
        claim_kind=cast("str", payload["claim_kind"]),
        claim_sha256=cast("str", payload["claim_sha256"]),
        evidence_sha256s=tuple(cast("list[str]", evidence)),
    )
    _exact_reconstructed_dict(value, claim, label="semantic claim")
    return claim


def _parse_evidence_reference(value: object) -> TransformOutputEvidenceReferenceV1:
    payload = _mapping(value, label="evidence reference")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "evidence_class",
                "reference_id",
                "evidence_sha256",
            }
        ),
        label="evidence reference",
    )
    _schema_identity(
        payload,
        kind=TransformOutputEvidenceReferenceV1.kind,
        label="evidence reference",
    )
    reference = TransformOutputEvidenceReferenceV1(
        evidence_class=cast("str", payload["evidence_class"]),
        reference_id=cast("str", payload["reference_id"]),
        evidence_sha256=cast("str", payload["evidence_sha256"]),
    )
    _exact_reconstructed_dict(value, reference, label="evidence reference")
    return reference


def _parse_entry(value: object) -> CurrentTransformOutputDispositionV1:
    payload = _mapping(value, label="current disposition entry")
    expected = frozenset((*CurrentTransformOutputDispositionV1.digest_field_names, "entry_sha256"))
    _exact_keys(payload, expected, label="current disposition entry")
    _schema_identity(
        payload,
        kind=CURRENT_TRANSFORM_OUTPUT_DISPOSITION_KIND,
        label="current disposition entry",
    )
    claims = _array(
        payload["semantic_claims"],
        label="semantic_claims",
        allow_empty=False,
    )
    evidence = _array(
        payload["evidence_references"],
        label="evidence_references",
        allow_empty=False,
    )
    triggers = _array(
        payload["revalidation_triggers"],
        label="revalidation_triggers",
        allow_empty=False,
    )
    entry = CurrentTransformOutputDispositionV1(
        output_name=cast("str", payload["output_name"]),
        family=cast("Literal['fact', 'dim', 'bridge', 'agg', 'analytics']", payload["family"]),
        table_contract_sha256=cast("str", payload["table_contract_sha256"]),
        schema_identity_sha256=cast("str", payload["schema_identity_sha256"]),
        transform_identity_sha256=cast("str", payload["transform_identity_sha256"]),
        ordered_columns_sha256=cast("str", payload["ordered_columns_sha256"]),
        dependency_identity_sha256=cast("str", payload["dependency_identity_sha256"]),
        state=cast(
            "Literal['active', 'observed_only_experimental', 'contract_not_modeled']",
            payload["state"],
        ),
        capability_policy=_parse_policy(payload["capability_policy"]),
        semantic_claims=tuple(_parse_semantic_claim(row) for row in claims),
        reason_code=cast("str", payload["reason_code"]),
        evidence_references=tuple(_parse_evidence_reference(row) for row in evidence),
        revalidation_triggers=tuple(cast("list[str]", triggers)),
    )
    _exact_reconstructed_dict(value, entry, label="current disposition entry")
    return entry


def _parse_tombstone(value: object) -> TransformOutputRemovedTombstoneV1:
    payload = _mapping(value, label="removed tombstone")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "output_name",
                "family",
                "last_entry_sha256",
                "removal_change_sha256",
                "first_tombstone_generation_sequence",
                "prior_envelope_sha256",
                "removal_reason_code",
                "removal_evidence_sha256s",
                "tombstone_sha256",
            }
        ),
        label="removed tombstone",
    )
    _schema_identity(
        payload,
        kind=TransformOutputRemovedTombstoneV1.kind,
        label="removed tombstone",
    )
    evidence = _array(
        payload["removal_evidence_sha256s"],
        label="removal_evidence_sha256s",
        allow_empty=False,
    )
    tombstone = TransformOutputRemovedTombstoneV1(
        output_name=cast("str", payload["output_name"]),
        family=cast("Literal['fact', 'dim', 'bridge', 'agg', 'analytics']", payload["family"]),
        last_entry_sha256=cast("str", payload["last_entry_sha256"]),
        removal_change_sha256=cast("str", payload["removal_change_sha256"]),
        first_tombstone_generation_sequence=cast(
            "int", payload["first_tombstone_generation_sequence"]
        ),
        prior_envelope_sha256=cast("str", payload["prior_envelope_sha256"]),
        removal_reason_code=cast("str", payload["removal_reason_code"]),
        removal_evidence_sha256s=tuple(cast("list[str]", evidence)),
    )
    _exact_reconstructed_dict(value, tombstone, label="removed tombstone")
    return tombstone


def _parse_change(value: object) -> TransformOutputChangeV1:
    payload = _mapping(value, label="disposition change")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "change_kind",
                "output_name",
                "prior_entry_sha256",
                "current_entry_sha256",
                "prior_state",
                "current_state",
                "prior_table_contract_sha256",
                "current_table_contract_sha256",
                "evidence_sha256s",
                "change_sha256",
            }
        ),
        label="disposition change",
    )
    _schema_identity(
        payload,
        kind=TransformOutputChangeV1.kind,
        label="disposition change",
    )
    evidence = _array(
        payload["evidence_sha256s"],
        label="change evidence_sha256s",
        allow_empty=False,
    )
    change = TransformOutputChangeV1(
        change_kind=cast(
            "Literal['structural_addition', 'state_transition', 'contract_rebind', 'removal']",
            payload["change_kind"],
        ),
        output_name=cast("str", payload["output_name"]),
        prior_entry_sha256=cast("str | None", payload["prior_entry_sha256"]),
        current_entry_sha256=cast("str | None", payload["current_entry_sha256"]),
        prior_state=cast(
            "Literal['active', 'observed_only_experimental', 'contract_not_modeled'] | None",
            payload["prior_state"],
        ),
        current_state=cast(
            "Literal['active', 'observed_only_experimental', 'contract_not_modeled'] | None",
            payload["current_state"],
        ),
        prior_table_contract_sha256=cast("str | None", payload["prior_table_contract_sha256"]),
        current_table_contract_sha256=cast("str | None", payload["current_table_contract_sha256"]),
        evidence_sha256s=tuple(cast("list[str]", evidence)),
    )
    _exact_reconstructed_dict(value, change, label="disposition change")
    return change


def _parse_dependency(value: object) -> TransformOutputDependencyV1:
    payload = _mapping(value, label="dependency row")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "output_name",
                "ordinal",
                "dependency_id",
                "dependency_kind",
                "dependency_contract_sha256",
                "dependency_sha256",
            }
        ),
        label="dependency row",
    )
    _schema_identity(
        payload,
        kind=TransformOutputDependencyV1.kind,
        label="dependency row",
    )
    dependency = TransformOutputDependencyV1(
        output_name=cast("str", payload["output_name"]),
        ordinal=cast("int", payload["ordinal"]),
        dependency_id=cast("str", payload["dependency_id"]),
        dependency_kind=cast(
            "Literal['transform_output', 'staging_input']", payload["dependency_kind"]
        ),
        dependency_contract_sha256=cast("str", payload["dependency_contract_sha256"]),
    )
    _exact_reconstructed_dict(value, dependency, label="dependency row")
    return dependency


@dataclass(frozen=True, slots=True)
class _PriorHistory:
    prior_generation_sequence: int
    prior_envelope_sha256: str | None
    entries: tuple[CurrentTransformOutputDispositionV1, ...]
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...]


@dataclass(frozen=True, slots=True)
class _DerivedAuthority:
    structural_output_names: tuple[str, ...]
    structural_table_authority_sha256s: tuple[str, ...]
    state_inventory: tuple[tuple[str, str], ...]
    capability_inventory: tuple[tuple[str, str], ...]
    executable_output_names: tuple[str, ...]
    active_output_names: tuple[str, ...]
    non_executable_output_names: tuple[str, ...]
    dependency_graph: tuple[tuple[str, tuple[str, ...]], ...]
    topological_order: tuple[str, ...]

    @property
    def state_inventory_sha256(self) -> str:
        return _domain_sha256(
            _STATE_INVENTORY_DOMAIN,
            [list(item) for item in self.state_inventory],
        )

    @property
    def capability_inventory_sha256(self) -> str:
        return _domain_sha256(
            _CAPABILITY_INVENTORY_DOMAIN,
            [list(item) for item in self.capability_inventory],
        )

    @property
    def dependency_graph_sha256(self) -> str:
        return _domain_sha256(
            _DEPENDENCY_GRAPH_DOMAIN,
            [
                {"output_name": output_name, "dependencies": list(dependencies)}
                for output_name, dependencies in self.dependency_graph
            ],
        )

    @property
    def topological_order_sha256(self) -> str:
        return _domain_sha256(_TOPOLOGICAL_ORDER_DOMAIN, list(self.topological_order))


def _single_source_member(
    proof_pack: TransformOutputDispositionProofPackV1,
    *,
    role: SourceMemberRole,
    path: str,
    representation: Literal["embedded_bytes", "typed_projection"],
    media_type: str,
) -> TransformOutputDispositionSourceMemberV1:
    members = proof_pack.source_bundle.members_for_role(role)
    if len(members) != 1:
        _fail(f"source bundle must contain exactly one {role} member")
    member = members[0]
    if (
        member.normalized_path != path
        or member.representation != representation
        or member.media_type != media_type
    ):
        _fail(f"source bundle {role} member has a foreign fixed identity")
    return member


def _typed_source_projection(
    proof_pack: TransformOutputDispositionProofPackV1,
    *,
    role: SourceMemberRole,
    path: str,
) -> object:
    member = _single_source_member(
        proof_pack,
        role=role,
        path=path,
        representation="typed_projection",
        media_type="application/json",
    )
    return member.typed_projection


def _parse_history(value: object) -> _PriorHistory:
    payload = _mapping(value, label="prior-or-initial history projection")
    _exact_keys(
        payload,
        frozenset(
            {
                "schema_version",
                "kind",
                "prior_generation_sequence",
                "prior_envelope_sha256",
                "prior_entries",
                "prior_tombstones",
            }
        ),
        label="prior-or-initial history projection",
    )
    _schema_identity(
        payload,
        kind=_HISTORY_KIND,
        label="prior-or-initial history projection",
    )
    if type(payload["prior_generation_sequence"]) is not int:
        _fail("prior generation sequence must be an exact integer")
    prior_generation_sequence = payload["prior_generation_sequence"]
    if not 0 <= prior_generation_sequence < _MAX_ROWS:
        _fail("prior generation sequence is outside its bound")
    entries = tuple(
        _parse_entry(row)
        for row in _array(
            payload["prior_entries"],
            label="prior entries",
            allow_empty=True,
        )
    )
    tombstones = tuple(
        _parse_tombstone(row)
        for row in _array(
            payload["prior_tombstones"],
            label="prior tombstones",
            allow_empty=True,
        )
    )
    if entries != tuple(sorted(entries, key=lambda item: item.output_name)) or len(
        {item.output_name for item in entries}
    ) != len(entries):
        _fail("prior entries must be sorted and unique by output name")
    if tombstones != tuple(sorted(tombstones, key=lambda item: item.output_name)) or len(
        {item.output_name for item in tombstones}
    ) != len(tombstones):
        _fail("prior tombstones must be sorted and unique by output name")
    if {item.output_name for item in entries} & {item.output_name for item in tombstones}:
        _fail("prior entries and tombstones must be disjoint")
    return _PriorHistory(
        prior_generation_sequence=prior_generation_sequence,
        prior_envelope_sha256=_optional_sha256(
            payload["prior_envelope_sha256"],
            label="prior history envelope SHA-256",
        ),
        entries=entries,
        tombstones=tombstones,
    )


def _star_projection(
    structural: TransformOutputStructuralAuthorityV1,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": _STAR_PROJECTION_KIND,
        "star_model_contract_sha256": structural.star_model_contract_sha256,
        "tables": [
            {
                "output_name": table.output_name,
                "table_contract_sha256": table.table_contract_sha256,
                "schema_sha256": table.schema_sha256,
                "transform_sha256": table.transform_sha256,
                "ordered_column_inventory_sha256": (table.ordered_column_inventory_sha256),
                "dependency_inventory_sha256": table.dependency_inventory_sha256,
                "table_authority_sha256": table.table_authority_sha256,
            }
            for table in structural.tables
        ],
    }


def _expected_authored_source_members(
    compiled: CompiledAuthoredTransformOutputDispositionAuthorityV1,
) -> tuple[TransformOutputDispositionSourceMemberV1, ...]:
    members = [
        TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
            normalized_path=_AUTHORED_ENTRIES_PATH,
            role="authored_entries",
            media_type="application/json",
            content=compiled.corpus.canonical_bytes(),
        ),
        *(
            TransformOutputDispositionSourceMemberV1.from_embedded_bytes(
                normalized_path=projection.source_member_path,
                role="authored_entries",
                media_type="application/json",
                content=projection.projection_bytes,
            )
            for projection in compiled.corpus.evidence_projections
        ),
    ]
    return tuple(sorted(members, key=lambda member: member.normalized_path))


def _compile_embedded_authored_authority(
    *,
    proof_pack: TransformOutputDispositionProofPackV1,
    structural: TransformOutputStructuralAuthorityV1,
) -> CompiledAuthoredTransformOutputDispositionAuthorityV1:
    observed = proof_pack.source_bundle.members_for_role("authored_entries")
    main = tuple(member for member in observed if member.normalized_path == _AUTHORED_ENTRIES_PATH)
    if (
        len(main) != 1
        or main[0].representation != "embedded_bytes"
        or main[0].media_type != "application/json"
    ):
        _fail("authored source bundle has no exact main corpus member")
    try:
        compiled = authored_module._compile_authored_transform_output_disposition_authority(
            main[0].content_bytes,
            structural,
        )
    except AuthoredTransformOutputDispositionError as exc:
        raise TransformOutputDispositionVerificationError(
            "embedded authored corpus is not one exact compiled authority"
        ) from exc
    expected = _expected_authored_source_members(compiled)
    if tuple(member.to_dict() for member in observed) != tuple(
        member.to_dict() for member in expected
    ):
        _fail("authored source members differ from the exact corpus and evidence closure")
    return compiled


def _validate_authored_envelope_projection(
    *,
    compiled: CompiledAuthoredTransformOutputDispositionAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    generation_sequence: int,
    authored_decision_authority_sha256: str,
) -> None:
    corpus = compiled.corpus
    if corpus.generation_sequence != generation_sequence:
        _fail("authored corpus generation differs from the disposition generation")
    if compiled.authority_sha256 != authored_decision_authority_sha256:
        _fail("authored decision authority root differs from the exact authored corpus")
    if compiled.entries != entries:
        _fail("candidate entries differ from the independently compiled authored authority")

    removals = {decision.output_name: decision for decision in corpus.removal_decisions}
    tombstones_by_name = {tombstone.output_name: tombstone for tombstone in tombstones}
    if set(removals) != set(tombstones_by_name):
        _fail("authored removal decisions differ from the exact tombstone inventory")
    changes_by_name = {change.output_name: change for change in changes}
    for output_name, decision in removals.items():
        tombstone = tombstones_by_name[output_name]
        evidence_sha256s = tuple(
            sorted(reference.evidence_sha256 for reference in decision.evidence_references)
        )
        if (
            decision.first_tombstone_generation_sequence
            != tombstone.first_tombstone_generation_sequence
            or decision.removal_reason_code != tombstone.removal_reason_code
            or evidence_sha256s != tombstone.removal_evidence_sha256s
        ):
            _fail(f"authored removal decision differs from its tombstone: {output_name}")
        if decision.first_tombstone_generation_sequence == generation_sequence:
            change = changes_by_name.get(output_name)
            if (
                change is None
                or change.change_kind != "removal"
                or change.evidence_sha256s != evidence_sha256s
            ):
                _fail(f"authored removal decision differs from its exact change: {output_name}")


def _dependencies_projection(
    dependencies: tuple[TransformOutputDependencyV1, ...],
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": _DEPENDENCIES_KIND,
        "dependencies": [dependency.to_dict() for dependency in dependencies],
    }


def _proof_inputs_projection(
    *,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    authored_decision_authority_sha256: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": _PROOF_INPUTS_KIND,
        "generation_sequence": generation_sequence,
        "prior_envelope_sha256": prior_envelope_sha256,
        "authored_decision_authority_sha256": authored_decision_authority_sha256,
        "structural_authority_sha256": structural.authority_sha256,
        "entry_sha256s": [entry.entry_sha256 for entry in entries],
        "tombstone_sha256s": [item.tombstone_sha256 for item in tombstones],
        "change_sha256s": [item.change_sha256 for item in changes],
        "dependency_sha256s": [item.dependency_sha256 for item in dependencies],
    }


def _validation_cases_projection() -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": _VALIDATION_CASES_KIND,
        "protected_entry_fields": list(PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1),
        "protected_capability_fields": list(PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1),
        "cases": [
            {
                "case_id": case_id,
                "validation_class": validation_class,
                "operation": operation,
            }
            for case_id, validation_class, operation in _VALIDATION_CASES
        ],
    }


def _validate_source_bundle_replay(
    *,
    proof_pack: TransformOutputDispositionProofPackV1,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    staging_inventory: RegisteredStagingInputContractInventoryV1,
    current_authored: CompiledAuthoredTransformOutputDispositionAuthorityV1,
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    authored_decision_authority_sha256: str,
) -> _PriorHistory:
    embedded_current_authored = _compile_embedded_authored_authority(
        proof_pack=proof_pack,
        structural=structural,
    )
    if (
        embedded_current_authored.corpus.canonical_bytes()
        != current_authored.corpus.canonical_bytes()
        or embedded_current_authored.entries != current_authored.entries
        or embedded_current_authored.authority_sha256 != current_authored.authority_sha256
    ):
        _fail("embedded authored authority differs from the fresh fixed repository authority")
    _validate_authored_envelope_projection(
        compiled=current_authored,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        generation_sequence=generation_sequence,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
    )

    projections: tuple[tuple[SourceMemberRole, str, object], ...] = (
        ("star_projection", _STAR_PROJECTION_PATH, _star_projection(structural)),
        (
            "structural_discovery",
            _STRUCTURAL_DISCOVERY_PATH,
            structural.to_dict(),
        ),
        (
            "proof_inputs",
            _PROOF_INPUTS_PATH,
            _proof_inputs_projection(
                structural=structural,
                entries=entries,
                tombstones=tombstones,
                changes=changes,
                dependencies=dependencies,
                generation_sequence=generation_sequence,
                prior_envelope_sha256=prior_envelope_sha256,
                authored_decision_authority_sha256=(authored_decision_authority_sha256),
            ),
        ),
        (
            "validation_evidence",
            _VALIDATION_EVIDENCE_PATH,
            _validation_cases_projection(),
        ),
    )
    for role, path, expected in projections:
        observed = _typed_source_projection(proof_pack, role=role, path=path)
        if observed != expected:
            _fail(f"source bundle {role} projection differs from fresh reconstruction")

    staging_member = _single_source_member(
        proof_pack,
        role="dependencies",
        path=_DEPENDENCIES_PATH,
        representation="embedded_bytes",
        media_type="application/json",
    )
    try:
        replayed_staging = RegisteredStagingInputContractInventoryV1.from_canonical_bytes(
            staging_member.content_bytes
        )
    except StagingInputContractAuthorityError as exc:
        raise TransformOutputDispositionVerificationError(
            "current dependency member is not the exact current typed staging authority"
        ) from exc
    if replayed_staging.to_dict() != staging_inventory.to_dict():
        _fail("current dependency member differs from the once-compiled staging authority")

    if generation_sequence == 1:
        history_projection = _typed_source_projection(
            proof_pack,
            role="prior_or_initial_history",
            path=_HISTORY_PATH,
        )
        history = _parse_history(history_projection)
        if (
            current_authored.corpus.generation_sequence != 1
            or current_authored.corpus.prior_authored_authority_sha256 is not None
        ):
            _fail("initial disposition generation does not use an initial authored corpus")
    else:
        prior_member = _single_source_member(
            proof_pack,
            role="prior_or_initial_history",
            path=_HISTORY_PATH,
            representation="embedded_bytes",
            media_type="application/json",
        )
        try:
            chain = TransformOutputDispositionHistoryChainV1.from_canonical_bytes(
                prior_member.content_bytes
            )
        except Exception as exc:
            raise TransformOutputDispositionVerificationError(
                "prior history member is not one complete typed historical chain"
            ) from exc
        if (
            chain.generation_count != generation_sequence - 1
            or chain.terminal_generation_sequence != generation_sequence - 1
            or chain.terminal_envelope_sha256 != prior_envelope_sha256
        ):
            _fail("prior history chain does not terminate at the exact immediate predecessor")
        prior_envelopes = tuple(
            history_module._reconstruct_historical_envelope(
                generation.envelope_member.content_bytes
            )
            for generation in chain.generations
        )
        prior_authored: CompiledAuthoredTransformOutputDispositionAuthorityV1 | None = None
        for prior_envelope in prior_envelopes:
            compiled_prior_authored = _compile_embedded_authored_authority(
                proof_pack=prior_envelope.proof_pack,
                structural=prior_envelope.structural_authority,
            )
            _validate_authored_envelope_projection(
                compiled=compiled_prior_authored,
                entries=prior_envelope.entries,
                tombstones=prior_envelope.tombstones,
                changes=prior_envelope.changes,
                generation_sequence=prior_envelope.generation_sequence,
                authored_decision_authority_sha256=(
                    prior_envelope.authored_decision_authority_sha256
                ),
            )
            if prior_authored is None:
                if (
                    compiled_prior_authored.corpus.generation_sequence != 1
                    or compiled_prior_authored.corpus.prior_authored_authority_sha256 is not None
                ):
                    _fail("historical authored chain does not start at generation one")
            else:
                try:
                    compiled_prior_authored.corpus.validate_successor_of(prior_authored.corpus)
                except AuthoredTransformOutputDispositionError as exc:
                    raise TransformOutputDispositionVerificationError(
                        "historical authored corpus is not the exact immediate successor"
                    ) from exc
            prior_authored = compiled_prior_authored
        if prior_authored is None:  # pragma: no cover - typed history chain is nonempty
            _fail("noninitial disposition generation has no authored history")
        try:
            current_authored.corpus.validate_successor_of(prior_authored.corpus)
        except AuthoredTransformOutputDispositionError as exc:
            raise TransformOutputDispositionVerificationError(
                "current authored corpus is not the exact immediate successor"
            ) from exc
        prior_envelope = prior_envelopes[-1]
        history = _PriorHistory(
            prior_generation_sequence=prior_envelope.generation_sequence,
            prior_envelope_sha256=prior_envelope.envelope_sha256,
            entries=prior_envelope.entries,
            tombstones=prior_envelope.tombstones,
        )

    verifier_member = _single_source_member(
        proof_pack,
        role="verifier_source",
        path=_VERIFIER_SOURCE_PATH,
        representation="embedded_bytes",
        media_type="text/x-python",
    )
    try:
        current_verifier_bytes = Path(__file__).read_bytes()
    except (MemoryError, OSError) as exc:
        raise TransformOutputDispositionVerificationError(
            "current verifier source bytes are unavailable"
        ) from exc
    if verifier_member.content_bytes != current_verifier_bytes:
        _fail("embedded verifier source differs from the current implementation bytes")
    return history


def _validate_entry_structural_bindings(
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
) -> None:
    if tuple(item.output_name for item in entries) != structural.output_names:
        _fail("current entries do not exactly cover the fresh structural denominator")
    table_by_name = {table.output_name: table for table in structural.tables}
    for entry in entries:
        table = table_by_name[entry.output_name]
        exact_bindings = (
            (entry.family, table.table_family),
            (entry.table_contract_sha256, table.table_contract_sha256),
            (entry.schema_identity_sha256, table.schema_sha256),
            (entry.transform_identity_sha256, table.transform_sha256),
            (
                entry.ordered_columns_sha256,
                table.ordered_column_inventory_sha256,
            ),
            (
                entry.dependency_identity_sha256,
                table.dependency_inventory_sha256,
            ),
        )
        if any(observed != expected for observed, expected in exact_bindings):
            _fail(f"entry differs from fresh table-local structure: {entry.output_name}")


def _validate_dependency_rows(
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    staging_inventory: RegisteredStagingInputContractInventoryV1,
) -> None:
    if dependencies != tuple(
        sorted(dependencies, key=lambda item: (item.output_name, item.ordinal))
    ):
        _fail("dependency rows must be sorted by owner and ordinal")
    if len({(item.output_name, item.ordinal) for item in dependencies}) != len(dependencies):
        _fail("dependency rows contain duplicate owner ordinals")

    structural_names = frozenset(structural.output_names)
    table_by_name = {table.output_name: table for table in structural.tables}
    entry_by_name = {entry.output_name: entry for entry in entries}
    rows_by_owner: dict[str, list[TransformOutputDependencyV1]] = {
        name: [] for name in structural.output_names
    }
    staging_contracts = {
        entry.dependency_id: entry.contract_sha256 for entry in staging_inventory.entries
    }
    observed_staging_ids: set[str] = set()
    for dependency in dependencies:
        if dependency.output_name not in structural_names:
            _fail("dependency row has a foreign output owner")
        rows_by_owner[dependency.output_name].append(dependency)
        if dependency.dependency_kind == "transform_output":
            target = table_by_name.get(dependency.dependency_id)
            if target is None:
                _fail("transform dependency is absent from the structural denominator")
            if dependency.dependency_contract_sha256 != target.table_contract_sha256:
                _fail("transform dependency contract differs from fresh structural authority")
            owner_state = entry_by_name[dependency.output_name].state
            dependency_state = entry_by_name[dependency.dependency_id].state
            if owner_state == "active" and dependency_state != "active":
                _fail("active output depends on a non-active transform output")
            if (
                owner_state == "observed_only_experimental"
                and dependency_state == "contract_not_modeled"
            ):
                _fail("experimental output depends on a non-executable transform output")
        else:
            observed_staging_ids.add(dependency.dependency_id)
            if staging_contracts.get(dependency.dependency_id) != (
                dependency.dependency_contract_sha256
            ):
                _fail("staging dependency differs from the exact current typed authority")

    for table in structural.tables:
        rows = rows_by_owner[table.output_name]
        if tuple(item.ordinal for item in rows) != tuple(range(len(rows))):
            _fail(f"dependency ordinals are not exact and contiguous: {table.output_name}")
        if len({item.dependency_id for item in rows}) != len(rows):
            _fail(f"dependency identities are duplicated: {table.output_name}")
        expected_names = table.dependencies
        observed_names = tuple(item.dependency_id for item in rows)
        if observed_names != expected_names:
            _fail(f"dependency rows differ from fresh structure: {table.output_name}")
        for row in rows:
            expected_kind = (
                "transform_output" if row.dependency_id in structural_names else "staging_input"
            )
            if row.dependency_kind != expected_kind:
                _fail(f"dependency classification is invalid: {table.output_name}")
    if observed_staging_ids != set(staging_contracts):
        _fail("staging dependency denominator differs from the exact current typed authority")


def _entry_evidence_sha256s(
    entry: CurrentTransformOutputDispositionV1,
) -> tuple[str, ...]:
    return tuple(sorted(item.evidence_sha256 for item in entry.evidence_references))


def _validate_change_for_difference(
    *,
    change: TransformOutputChangeV1,
    expected_kind: Literal[
        "structural_addition",
        "state_transition",
        "contract_rebind",
        "removal",
    ],
    prior: CurrentTransformOutputDispositionV1 | None,
    current: CurrentTransformOutputDispositionV1 | None,
) -> None:
    expected = (
        expected_kind,
        None if prior is None else prior.entry_sha256,
        None if current is None else current.entry_sha256,
        None if prior is None else prior.state,
        None if current is None else current.state,
        None if prior is None else prior.table_contract_sha256,
        None if current is None else current.table_contract_sha256,
    )
    observed = (
        change.change_kind,
        change.prior_entry_sha256,
        change.current_entry_sha256,
        change.prior_state,
        change.current_state,
        change.prior_table_contract_sha256,
        change.current_table_contract_sha256,
    )
    if observed != expected:
        _fail(f"change row misclassifies the exact difference: {change.output_name}")
    if current is not None and change.evidence_sha256s != _entry_evidence_sha256s(current):
        _fail(f"change evidence differs from the current entry: {change.output_name}")


def _validate_evolution(
    *,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    history: _PriorHistory,
) -> None:
    if type(generation_sequence) is not int or not 1 <= generation_sequence < _MAX_ROWS:
        _fail("generation sequence must be one bounded positive integer")
    if generation_sequence == 1:
        if (
            prior_envelope_sha256 is not None
            or history.prior_generation_sequence != 0
            or history.prior_envelope_sha256 is not None
            or history.entries
            or history.tombstones
            or tombstones
            or changes
        ):
            _fail("initial generation contains foreign prior, change, or tombstone state")
        return

    if (
        prior_envelope_sha256 is None
        or history.prior_generation_sequence != generation_sequence - 1
        or history.prior_envelope_sha256 != prior_envelope_sha256
    ):
        _fail("noninitial generation does not bind its exact immediate prior envelope")
    if not history.entries:
        _fail("noninitial history has no prior current entries")

    current_by_name = {entry.output_name: entry for entry in entries}
    prior_by_name = {entry.output_name: entry for entry in history.entries}
    prior_tombstone_by_name = {item.output_name: item for item in history.tombstones}
    current_tombstone_by_name = {item.output_name: item for item in tombstones}
    change_by_name: dict[str, TransformOutputChangeV1] = {}
    for change in changes:
        if change.output_name in change_by_name:
            _fail("evolution contains duplicate changes for one output")
        change_by_name[change.output_name] = change

    if set(current_by_name) & set(prior_tombstone_by_name):
        _fail("a permanently tombstoned output name reappears in current structure")
    for output_name, prior_tombstone in prior_tombstone_by_name.items():
        if current_tombstone_by_name.get(output_name) != prior_tombstone:
            _fail("a prior tombstone was deleted or mutated")

    expected_changed_names: set[str] = set()
    all_names = sorted(set(prior_by_name) | set(current_by_name))
    for output_name in all_names:
        prior = prior_by_name.get(output_name)
        current = current_by_name.get(output_name)
        if prior is None:
            expected_kind = "structural_addition"
        elif current is None:
            expected_kind = "removal"
        elif prior.entry_sha256 == current.entry_sha256:
            continue
        elif (
            prior.state != current.state
            and prior.table_contract_sha256 == current.table_contract_sha256
            and replace(prior, state=current.state, capability_policy=current.capability_policy)
            == current
        ):
            expected_kind = "state_transition"
        elif prior.state == current.state:
            expected_kind = "contract_rebind"
        else:
            _fail(f"entry combines incompatible state and contract drift: {output_name}")
        expected_changed_names.add(output_name)
        change = change_by_name.get(output_name)
        if change is None:
            _fail(f"evolution is missing one exact change row: {output_name}")
        _validate_change_for_difference(
            change=change,
            expected_kind=expected_kind,
            prior=prior,
            current=current,
        )
        if expected_kind == "removal":
            if prior is None:
                raise AssertionError("removal requires a prior entry")
            tombstone = current_tombstone_by_name.get(output_name)
            if tombstone is None:
                _fail(f"removal has no immutable tombstone: {output_name}")
            if (
                tombstone.family != prior.family
                or tombstone.last_entry_sha256 != prior.entry_sha256
                or tombstone.removal_change_sha256 != change.change_sha256
                or tombstone.first_tombstone_generation_sequence != generation_sequence
                or tombstone.prior_envelope_sha256 != prior_envelope_sha256
                or tombstone.removal_evidence_sha256s != change.evidence_sha256s
            ):
                _fail(f"removal tombstone differs from exact evolution: {output_name}")

    if set(change_by_name) != expected_changed_names:
        _fail("evolution contains extra or missing change identities")
    new_tombstone_names = set(current_tombstone_by_name) - set(prior_tombstone_by_name)
    removed_names = set(prior_by_name) - set(current_by_name)
    if new_tombstone_names != removed_names:
        _fail("tombstone additions differ from exact structural removals")


def _topological_order(
    graph: tuple[tuple[str, tuple[str, ...]], ...],
) -> tuple[str, ...]:
    remaining = {output_name: set(dependencies) for output_name, dependencies in graph}
    result: list[str] = []
    while remaining:
        ready = sorted(name for name, dependencies in remaining.items() if not dependencies)
        if not ready:
            _fail("executable transform dependency graph contains a cycle")
        for output_name in ready:
            result.append(output_name)
            del remaining[output_name]
        ready_set = set(ready)
        for dependencies in remaining.values():
            dependencies.difference_update(ready_set)
    return tuple(result)


def _derive_authority(
    *,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    staging_inventory: RegisteredStagingInputContractInventoryV1,
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    history: _PriorHistory,
) -> _DerivedAuthority:
    _validate_entry_structural_bindings(structural, entries)
    _validate_dependency_rows(structural, entries, dependencies, staging_inventory)
    _validate_evolution(
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
        history=history,
    )
    active_output_names = tuple(entry.output_name for entry in entries if entry.state == "active")
    executable_output_names = tuple(
        entry.output_name for entry in entries if entry.capability_policy.execute
    )
    non_executable_output_names = tuple(
        entry.output_name for entry in entries if not entry.capability_policy.execute
    )
    executable = frozenset(executable_output_names)
    dependency_by_owner: dict[str, list[str]] = {name: [] for name in executable_output_names}
    for dependency in dependencies:
        if (
            dependency.output_name in executable
            and dependency.dependency_kind == "transform_output"
        ):
            if dependency.dependency_id not in executable:
                _fail("executable graph contains a non-executable transform dependency")
            dependency_by_owner[dependency.output_name].append(dependency.dependency_id)
    dependency_graph = tuple(
        (output_name, tuple(dependency_by_owner[output_name]))
        for output_name in executable_output_names
    )
    topological_order = _topological_order(dependency_graph)
    return _DerivedAuthority(
        structural_output_names=structural.output_names,
        structural_table_authority_sha256s=tuple(
            table.table_authority_sha256 for table in structural.tables
        ),
        state_inventory=tuple((entry.output_name, entry.state) for entry in entries),
        capability_inventory=tuple(
            (entry.output_name, entry.capability_policy.policy_sha256) for entry in entries
        ),
        executable_output_names=executable_output_names,
        active_output_names=active_output_names,
        non_executable_output_names=non_executable_output_names,
        dependency_graph=dependency_graph,
        topological_order=topological_order,
    )


def _result_payload(
    *,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    authored_decision_authority_sha256: str,
    derived: _DerivedAuthority,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "nbadb_transform_output_disposition_verified_result",
        "structural_authority_sha256": structural.authority_sha256,
        "star_model_contract_sha256": structural.star_model_contract_sha256,
        "authored_decision_authority_sha256": authored_decision_authority_sha256,
        "generation_sequence": generation_sequence,
        "prior_envelope_sha256": prior_envelope_sha256,
        "entry_sha256s": [entry.entry_sha256 for entry in entries],
        "tombstone_sha256s": [item.tombstone_sha256 for item in tombstones],
        "change_sha256s": [item.change_sha256 for item in changes],
        "dependency_sha256s": [item.dependency_sha256 for item in dependencies],
        "structural_output_names": list(derived.structural_output_names),
        "structural_table_authority_sha256s": list(derived.structural_table_authority_sha256s),
        "state_inventory": [list(item) for item in derived.state_inventory],
        "state_inventory_sha256": derived.state_inventory_sha256,
        "capability_inventory": [list(item) for item in derived.capability_inventory],
        "capability_inventory_sha256": derived.capability_inventory_sha256,
        "executable_output_names": list(derived.executable_output_names),
        "active_output_names": list(derived.active_output_names),
        "non_executable_output_names": list(derived.non_executable_output_names),
        "dependency_graph": [
            {"output_name": owner, "dependencies": list(targets)}
            for owner, targets in derived.dependency_graph
        ],
        "dependency_graph_sha256": derived.dependency_graph_sha256,
        "topological_order": list(derived.topological_order),
        "topological_order_sha256": derived.topological_order_sha256,
    }


def _result_sha256(
    *,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    authored_decision_authority_sha256: str,
    derived: _DerivedAuthority,
) -> str:
    return _domain_sha256(
        _RESULT_DOMAIN,
        _result_payload(
            structural=structural,
            entries=entries,
            tombstones=tombstones,
            changes=changes,
            dependencies=dependencies,
            generation_sequence=generation_sequence,
            prior_envelope_sha256=prior_envelope_sha256,
            authored_decision_authority_sha256=authored_decision_authority_sha256,
            derived=derived,
        ),
    )


def _run_fixed_validation_case(
    operation: str,
    *,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    staging_inventory: RegisteredStagingInputContractInventoryV1,
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    history: _PriorHistory,
) -> Literal["accepted", "rejected"]:
    contract_errors = (
        DispositionEvidenceError,
        TransformOutputDispositionAuthorityError,
        TransformOutputDispositionHistoryError,
        TransformOutputDispositionStructuralError,
        StagingInputContractAuthorityError,
    )

    def _candidate_rejected(
        candidate_entries: tuple[CurrentTransformOutputDispositionV1, ...],
    ) -> bool:
        if candidate_entries != entries:
            return True
        try:
            _derive_authority(
                structural=structural,
                entries=candidate_entries,
                tombstones=tombstones,
                changes=changes,
                dependencies=dependencies,
                staging_inventory=staging_inventory,
                generation_sequence=generation_sequence,
                prior_envelope_sha256=prior_envelope_sha256,
                history=history,
            )
        except contract_errors:
            return True
        return False

    if operation == "exact_reconstruction":
        return "rejected" if _candidate_rejected(entries) else "accepted"
    if operation == "drop_each_entry":
        return (
            "rejected"
            if all(
                _candidate_rejected((*entries[:index], *entries[index + 1 :]))
                for index in range(len(entries))
            )
            else "accepted"
        )
    if operation != "mutate_each_protected_field":
        _fail("validation evidence names an unsupported operation")

    validate_transform_output_disposition_protected_fields_v1()
    expected_mutations = {
        *(
            ("entry", field_name)
            for field_name in PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1
            if field_name != "capability_policy"
        ),
        *(
            ("capability_policy", field_name)
            for field_name in PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1
        ),
    }
    observed_mutations: set[tuple[str, str]] = set()
    for index, entry in enumerate(entries):
        for field_name in PROTECTED_TRANSFORM_OUTPUT_CAPABILITY_FIELDS_V1:
            observed_mutations.add(("capability_policy", field_name))
            try:
                changed_policy = replace(
                    entry.capability_policy,
                    **{field_name: not getattr(entry.capability_policy, field_name)},
                )
                changed_entry = replace(entry, capability_policy=changed_policy)
            except contract_errors:
                continue
            candidate = (*entries[:index], changed_entry, *entries[index + 1 :])
            if not _candidate_rejected(candidate):
                return "accepted"
        for field_name in PROTECTED_TRANSFORM_OUTPUT_DISPOSITION_ENTRY_FIELDS_V1:
            if field_name == "capability_policy":
                continue
            observed_mutations.add(("entry", field_name))
            current = getattr(entry, field_name)
            if field_name == "output_name":
                changed = f"{current}_mutated"
            elif field_name == "family":
                changed = "fact" if current != "fact" else "dim"
            elif field_name.endswith("_sha256"):
                changed = "0" * 64 if current != "0" * 64 else "1" * 64
            elif field_name == "state":
                changed = "contract_not_modeled" if current != "contract_not_modeled" else "active"
            elif field_name == "semantic_claims":
                claims = cast("tuple[TransformOutputSemanticClaimV1, ...]", current)
                first_claim = claims[0]
                changed = (
                    *claims,
                    replace(
                        first_claim,
                        claim_id=f"{first_claim.claim_id}:mutated",
                    ),
                )
            elif field_name == "reason_code":
                changed = f"{current}_mutated"
            elif field_name == "evidence_references":
                refs = cast("tuple[TransformOutputEvidenceReferenceV1, ...]", current)
                changed = (*refs, replace(refs[0], reference_id=f"{refs[0].reference_id}:mutated"))
            elif field_name == "revalidation_triggers":
                changed = (*cast("tuple[str, ...]", current), "mutated_trigger")
            else:
                raise AssertionError(f"unhandled protected field: {field_name}")
            try:
                changed_entry = replace(entry, **{field_name: changed})
            except contract_errors:
                continue
            candidate = (*entries[:index], changed_entry, *entries[index + 1 :])
            if not _candidate_rejected(candidate):
                return "accepted"
    if observed_mutations != expected_mutations:
        _fail("protected-field mutation inventory is incomplete")
    return "rejected"


def _replay_validation_evidence(
    *,
    proof_pack: TransformOutputDispositionProofPackV1,
    structural: TransformOutputStructuralAuthorityV1,
    entries: tuple[CurrentTransformOutputDispositionV1, ...],
    tombstones: tuple[TransformOutputRemovedTombstoneV1, ...],
    changes: tuple[TransformOutputChangeV1, ...],
    dependencies: tuple[TransformOutputDependencyV1, ...],
    staging_inventory: RegisteredStagingInputContractInventoryV1,
    generation_sequence: int,
    prior_envelope_sha256: str | None,
    history: _PriorHistory,
) -> None:
    proof_input_member = _single_source_member(
        proof_pack,
        role="proof_inputs",
        path=_PROOF_INPUTS_PATH,
        representation="typed_projection",
        media_type="application/json",
    )
    evidence_member = _single_source_member(
        proof_pack,
        role="validation_evidence",
        path=_VALIDATION_EVIDENCE_PATH,
        representation="typed_projection",
        media_type="application/json",
    )
    rows = proof_pack.validation_evidence
    if len(rows) != len(_VALIDATION_CASES):
        _fail("proof pack does not contain the exact fixed validation case set")
    for row, (case_id, validation_class, operation) in zip(
        rows,
        _VALIDATION_CASES,
        strict=True,
    ):
        expected_outcome = "accepted" if validation_class == "positive" else "rejected"
        observed_outcome = _run_fixed_validation_case(
            operation,
            structural=structural,
            entries=entries,
            tombstones=tombstones,
            changes=changes,
            dependencies=dependencies,
            staging_inventory=staging_inventory,
            generation_sequence=generation_sequence,
            prior_envelope_sha256=prior_envelope_sha256,
            history=history,
        )
        exact = (
            row.case_id,
            row.validation_class,
            row.proof_input_member_sha256,
            row.evidence_member_sha256s,
            row.expected_outcome,
            row.observed_outcome,
        )
        expected = (
            case_id,
            validation_class,
            proof_input_member.member_sha256,
            (evidence_member.member_sha256,),
            expected_outcome,
            observed_outcome,
        )
        if exact != expected or observed_outcome != expected_outcome:
            _fail(f"validation evidence fails fresh replay: {case_id}")


_ENVELOPE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "structural_authority",
        "proof_pack",
        "audit_metadata",
        "generation_sequence",
        "prior_envelope_sha256",
        "entries",
        "tombstones",
        "changes",
        "dependencies",
        "structural_output_names",
        "entry_inventory",
        "state_inventory",
        "state_counts",
        "capability_inventory",
        "active_output_names",
        "experimental_output_names",
        "non_executable_output_names",
        "executable_output_names",
        "stable_load_output_names",
        "transform_publication_output_names",
        "chat_ceiling_output_names",
        "tombstone_output_names",
        "dependency_graph",
        "topological_order",
        "structural_count",
        "structural_authority_sha256",
        "star_model_contract_sha256",
        "authored_decision_authority_sha256",
        "source_bundle_sha256",
        "proof_pack_sha256",
        "verifier_source_inventory_sha256",
        "audit_metadata_sha256",
        "output_name_inventory_sha256",
        "table_authority_inventory_sha256",
        "entries_sha256",
        "tombstones_sha256",
        "changes_sha256",
        "dependencies_sha256",
        "entry_inventory_sha256",
        "state_inventory_sha256",
        "capability_inventory_sha256",
        "dependency_graph_sha256",
        "topological_order_sha256",
        "proof_result_sha256",
        "generation_identity_sha256",
        "envelope_sha256",
    }
)


def _parse_envelope_rows(
    payload: Mapping[str, object],
) -> tuple[
    tuple[CurrentTransformOutputDispositionV1, ...],
    tuple[TransformOutputRemovedTombstoneV1, ...],
    tuple[TransformOutputChangeV1, ...],
    tuple[TransformOutputDependencyV1, ...],
]:
    entries = tuple(
        _parse_entry(row)
        for row in _array(payload["entries"], label="envelope entries", allow_empty=False)
    )
    tombstones = tuple(
        _parse_tombstone(row)
        for row in _array(
            payload["tombstones"],
            label="envelope tombstones",
            allow_empty=True,
        )
    )
    changes = tuple(
        _parse_change(row)
        for row in _array(payload["changes"], label="envelope changes", allow_empty=True)
    )
    dependencies = tuple(
        _parse_dependency(row)
        for row in _array(
            payload["dependencies"],
            label="envelope dependencies",
            allow_empty=True,
        )
    )
    if entries != tuple(sorted(entries, key=lambda item: item.output_name)) or len(
        {item.output_name for item in entries}
    ) != len(entries):
        _fail("envelope entries must be sorted and unique by output name")
    if tombstones != tuple(sorted(tombstones, key=lambda item: item.output_name)) or len(
        {item.output_name for item in tombstones}
    ) != len(tombstones):
        _fail("envelope tombstones must be sorted and unique by output name")
    if changes != tuple(sorted(changes, key=lambda item: (item.output_name, item.change_kind))):
        _fail("envelope changes must be sorted by output name and change kind")
    if len({item.output_name for item in changes}) != len(changes):
        _fail("envelope changes contain duplicate output identities")
    if dependencies != tuple(
        sorted(dependencies, key=lambda item: (item.output_name, item.ordinal))
    ):
        _fail("envelope dependencies must be sorted by owner and ordinal")
    return entries, tombstones, changes, dependencies


def _verify_transform_output_disposition_envelope(
    raw: bytes,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    decoded = decode_canonical_json_bytes_v1(raw, persisted=True)
    payload = _mapping(decoded, label="transform-output disposition envelope")
    _exact_keys(
        payload,
        _ENVELOPE_KEYS,
        label="transform-output disposition envelope",
    )
    _schema_identity(
        payload,
        kind=TRANSFORM_OUTPUT_DISPOSITION_AUTHORITY_KIND,
        label="transform-output disposition envelope",
    )
    structural = TransformOutputStructuralAuthorityV1.from_dict(payload["structural_authority"])
    proof_pack = TransformOutputDispositionProofPackV1.from_dict(payload["proof_pack"])
    audit_metadata = TransformOutputDispositionAuditMetadataV1.from_dict(payload["audit_metadata"])
    if audit_metadata.proof_pack_root_sha256 != proof_pack.proof_pack_root_sha256:
        _fail("audit metadata differs from the exact proof pack")
    if type(payload["generation_sequence"]) is not int:
        _fail("generation sequence must be an exact integer")
    generation_sequence = payload["generation_sequence"]
    prior_envelope_sha256 = _optional_sha256(
        payload["prior_envelope_sha256"],
        label="prior envelope SHA-256",
    )
    authored_decision_authority_sha256 = _optional_sha256(
        payload["authored_decision_authority_sha256"],
        label="authored decision authority SHA-256",
    )
    if authored_decision_authority_sha256 is None:
        _fail("authored decision authority SHA-256 must be one exact lowercase SHA-256")
    entries, tombstones, changes, dependencies = _parse_envelope_rows(payload)

    fresh_structural = compile_current_transform_output_structural_authority()
    fresh_staging_inventory = compile_registered_staging_input_contract_inventory()
    current_authored = load_current_transform_output_disposition_authored_authority()
    if structural.to_dict() != fresh_structural.to_dict():
        _fail("embedded structural authority differs from a fresh two-source compilation")

    history = _validate_source_bundle_replay(
        proof_pack=proof_pack,
        structural=fresh_structural,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        staging_inventory=fresh_staging_inventory,
        current_authored=current_authored,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
    )
    derived = _derive_authority(
        structural=fresh_structural,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        staging_inventory=fresh_staging_inventory,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
        history=history,
    )
    reconstructed_result_sha256 = _result_sha256(
        structural=fresh_structural,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
        derived=derived,
    )
    if proof_pack.claimed_reconstructed_result_sha256 != reconstructed_result_sha256:
        _fail("proof pack claimed result differs from fresh independent reconstruction")
    _replay_validation_evidence(
        proof_pack=proof_pack,
        structural=fresh_structural,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        staging_inventory=fresh_staging_inventory,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
        history=history,
    )

    envelope = authority_module._construct_verified_envelope(
        token=authority_module._VERIFIED_ENVELOPE_CONSTRUCTION_TOKEN,
        structural_authority=fresh_structural,
        proof_pack=proof_pack,
        audit_metadata=audit_metadata,
        entries=entries,
        tombstones=tombstones,
        changes=changes,
        dependencies=dependencies,
        authored_decision_authority_sha256=authored_decision_authority_sha256,
        generation_sequence=generation_sequence,
        prior_envelope_sha256=prior_envelope_sha256,
    )
    if envelope.canonical_bytes() != raw:
        _fail("sealed envelope differs from the exact independently reconstructed bytes")
    return envelope


def verify_transform_output_disposition_envelope(
    raw: bytes,
) -> VerifiedTransformOutputDispositionAuthorityEnvelopeV1:
    """Strictly replay one persisted canonical envelope from raw bytes only."""

    if type(raw) is not bytes:
        _fail("transform-output disposition envelope input must be exact bytes")
    try:
        return _verify_transform_output_disposition_envelope(raw)
    except TransformOutputDispositionVerificationError:
        raise
    except (
        DispositionEvidenceError,
        TransformOutputDispositionAuthorityError,
        AuthoredTransformOutputDispositionError,
        TransformOutputDispositionStructuralError,
    ) as exc:
        raise TransformOutputDispositionVerificationError(str(exc)) from exc
    except (MemoryError, RecursionError) as exc:
        raise TransformOutputDispositionVerificationError(
            "transform-output disposition replay exceeded its resource bounds"
        ) from exc
