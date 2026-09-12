from __future__ import annotations

import inspect
import json
from collections import Counter
from dataclasses import replace
from typing import TYPE_CHECKING

import pytest

from nbadb.contracts import star_semantic_review_packet as packet_module
from nbadb.contracts.model_candidate_census import ModelCandidateCensusEvidenceV1
from nbadb.contracts.stable_model_disposition import (
    StableModelCandidateV1,
    StableModelDispositionV1,
)
from nbadb.contracts.star_semantic_authoring import (
    StarTableSemanticDecisionV1,
    canonical_star_semantic_authoring_sha256,
)
from nbadb.contracts.star_semantic_inventory import StarTableSemanticAuthorityV1
from nbadb.contracts.star_semantic_review_packet import (
    STAR_SEMANTIC_REVIEW_PACKET_KIND,
    STAR_SEMANTIC_REVIEW_PACKET_SCHEMA_VERSION,
    StarSemanticReviewPacketError,
    StarSemanticReviewPacketV1,
    StarSemanticReviewTableV1,
    compile_current_star_semantic_review_packet,
)

if TYPE_CHECKING:
    from collections.abc import Callable


@pytest.fixture(scope="module")
def sources():
    return packet_module._current_star_semantic_review_sources()  # noqa: SLF001


@pytest.fixture(scope="module")
def packet(sources) -> StarSemanticReviewPacketV1:
    return packet_module._compile_star_semantic_review_packet(sources)  # noqa: SLF001


def test_current_packet_derives_exact_drift_sensitive_family_observation(
    packet: StarSemanticReviewPacketV1,
) -> None:
    # These are characterization assertions for current source bytes, never
    # production denominator constants.
    assert packet.schema_version == STAR_SEMANTIC_REVIEW_PACKET_SCHEMA_VERSION == 1
    assert packet.kind == STAR_SEMANTIC_REVIEW_PACKET_KIND
    assert packet.output_count == 261
    assert dict(packet.family_counts) == {
        "fact": 204,
        "dim": 18,
        "bridge": 6,
        "agg": 19,
        "analytics": 14,
    }
    assert Counter(item.family for item in packet.tables) == dict(packet.family_counts)
    assert packet.output_names == tuple(sorted(packet.output_names))
    assert len(set(packet.output_names)) == packet.output_count
    assert packet.read_only is True
    assert packet.authority_admitted is False
    assert packet.model_green is False


def test_every_table_exact_joins_structural_candidate_evidence_and_authority(
    packet: StarSemanticReviewPacketV1,
) -> None:
    for row in packet.tables:
        candidate_id = f"star:{row.output_name}"
        structural = json.loads(row.structural_observation_json)
        candidate = json.loads(row.candidate_observation_json)
        evidence = json.loads(row.candidate_source_evidence_observation_json)
        disposition = json.loads(row.stable_disposition_inventory_observation_json)
        authority = json.loads(row.semantic_authority_observation_json)

        assert structural["output_name"] == row.output_name
        assert structural["family"] == row.family
        assert structural["structural_table_sha256"] == authority["structural_table_sha256"]
        assert structural["schema"]["sha256"] == authority["schema_sha256"]
        assert structural["transform"]["implementation_sha256"] == authority["transform_sha256"]
        assert structural["transform"]["dependencies"] == authority["transformer_dependencies"]
        assert candidate["candidate_id"] == candidate_id
        assert evidence["candidate_id"] == candidate_id
        assert disposition["candidate_id"] == candidate_id
        assert authority["expected_candidate_id"] == candidate_id
        assert disposition["candidate_sha256"] == authority["candidate_sha256"]
        assert candidate["structural_sha256"] == authority["candidate_structural_sha256"]
        assert disposition["semantic_sha256"] == authority["disposition_semantic_sha256"]


def test_authored_decisions_and_missing_blockers_are_preserved_without_prefill(
    packet: StarSemanticReviewPacketV1,
) -> None:
    authored = tuple(item for item in packet.tables if item.semantic_decision_state == "authored")
    missing = tuple(item for item in packet.tables if item.semantic_decision_state == "missing")

    assert packet.authored_decision_count == len(authored) == 1
    assert packet.missing_decision_count == len(missing) == 260
    assert tuple(item.output_name for item in authored) == ("dim_season_phase",)
    assert authored[0].authored_semantic_decision_json is not None
    assert authored[0].authored_semantic_decision_blockers == ()
    assert json.loads(authored[0].authored_semantic_decision_json)["table_name"] == (
        "dim_season_phase"
    )
    assert all(item.authored_semantic_decision_json is None for item in missing)
    assert all(
        item.authored_semantic_decision_blockers
        == (
            "semantic_decision_not_authored",
            "table_specific_semantic_evidence_unreviewed",
        )
        for item in missing
    )
    assert all("purpose_code" not in item.to_dict() for item in missing)
    assert all("grain_dimensions" not in item.to_dict() for item in missing)


def test_packet_and_rows_are_canonical_deterministic_and_digest_bound(
    packet: StarSemanticReviewPacketV1,
    sources,
) -> None:
    rebuilt = packet_module._compile_star_semantic_review_packet(sources)  # noqa: SLF001
    first_row = packet.tables[0]

    assert rebuilt.canonical_bytes == packet.canonical_bytes
    assert rebuilt.packet_sha256 == packet.packet_sha256
    assert StarSemanticReviewPacketV1.from_canonical_bytes(packet.canonical_bytes) == packet
    assert first_row.to_dict()["row_sha256"] == first_row.row_sha256
    assert (
        json.dumps(
            packet.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        == packet.canonical_bytes
    )

    mutated = packet.to_dict()
    mutated_tables = mutated["tables"]
    assert type(mutated_tables) is list
    first = mutated_tables[0]
    assert type(first) is dict
    first["family"] = "dim" if first["family"] != "dim" else "fact"
    raw = json.dumps(
        mutated,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    with pytest.raises(StarSemanticReviewPacketError):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


def test_public_compiler_has_no_candidate_approval_or_authority_override_seam() -> None:
    signature = inspect.signature(compile_current_star_semantic_review_packet)
    assert tuple(signature.parameters) == ()
    public_names = set(packet_module.__all__)
    assert "_compile_star_semantic_review_packet" not in public_names
    assert "_current_star_semantic_review_sources" not in public_names
    assert "compile_star_semantic_review_packet" not in public_names
    assert not hasattr(StarSemanticReviewPacketV1, "from_dict")
    assert not hasattr(StarSemanticReviewTableV1, "from_dict")
    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compiler"):
        StarSemanticReviewPacketV1()
    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compiler"):
        StarSemanticReviewTableV1()


def _foreign_authority(
    authority: StarTableSemanticAuthorityV1,
) -> StarTableSemanticAuthorityV1:
    prefix_by_family = {
        "aggregate": "agg",
        "analytics": "analytics",
        "bridge": "bridge",
        "dimension": "dim",
        "fact": "fact",
    }
    output_name = f"{prefix_by_family[authority.table_family]}_foreign"
    return replace(
        authority,
        output_name=output_name,
        expected_candidate_id=f"star:{output_name}",
    )


@pytest.mark.parametrize(
    ("mutate", "label"),
    (
        (lambda rows: rows[:-1], "omission"),
        (lambda rows: (*rows, rows[-1]), "extra"),
        (lambda rows: tuple(reversed(rows)), "reorder"),
        (lambda rows: (_foreign_authority(rows[0]), *rows[1:]), "foreign"),
    ),
)
def test_exact_table_join_rejects_omitted_extra_reordered_and_foreign_authorities(
    sources,
    mutate: Callable[
        [tuple[StarTableSemanticAuthorityV1, ...]],
        tuple[StarTableSemanticAuthorityV1, ...],
    ],
    label: str,
) -> None:
    mutated = replace(sources, semantic_authorities=mutate(sources.semantic_authorities))

    with pytest.raises(StarSemanticReviewPacketError, match="semantic authority"):
        packet_module._compile_star_semantic_review_packet(mutated)  # noqa: SLF001
    assert label in {"omission", "extra", "reorder", "foreign"}


def test_stale_root_is_rejected_before_a_review_packet_is_constructed(sources) -> None:
    stale_census = replace(sources.candidate_census, star_model_contract_sha256="f" * 64)
    mutated = replace(sources, candidate_census=stale_census)

    with pytest.raises(StarSemanticReviewPacketError, match="stale structural inventory root"):
        packet_module._compile_star_semantic_review_packet(mutated)  # noqa: SLF001


def test_structural_source_mutation_is_rejected_even_when_name_is_unchanged(sources) -> None:
    first = sources.structural_inventory.tables[0]
    mutated_table = replace(first, purpose="mutated-structural-observation")
    mutated_structural = replace(
        sources.structural_inventory,
        tables=(mutated_table, *sources.structural_inventory.tables[1:]),
    )
    mutated = replace(sources, structural_inventory=mutated_structural)

    with pytest.raises(StarSemanticReviewPacketError, match="source mutation"):
        packet_module._compile_star_semantic_review_packet(mutated)  # noqa: SLF001


def test_missing_semantic_decision_cannot_be_prefilled_from_an_authored_peer(
    packet: StarSemanticReviewPacketV1,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    missing = next(item for item in packet.tables if item.semantic_decision_state == "missing")
    authored = next(item for item in packet.tables if item.semantic_decision_state == "authored")
    assert authored.authored_semantic_decision_json is not None

    payload = json.loads(packet.canonical_bytes)
    table = next(item for item in payload["tables"] if item["output_name"] == missing.output_name)
    table["semantic_decision_state"] = "authored"
    table["authored_semantic_decision"] = json.loads(authored.authored_semantic_decision_json)
    table["authored_semantic_decision_blockers"] = []
    _reseal_table(table)
    raw = _reseal_packet(payload)
    monkeypatch.setattr(
        packet_module,
        "compile_current_star_semantic_review_packet",
        lambda: packet,
    )

    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compilation"):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


def _reseal_table(table: dict[str, object]) -> None:
    table["row_sha256"] = packet_module._sha256(  # noqa: SLF001
        {key: value for key, value in table.items() if key != "row_sha256"}
    )


def _reseal_packet(payload: dict[str, object], *, attack: str = "row-mutation") -> bytes:
    tables = payload["tables"]
    assert type(tables) is list
    payload["output_names"] = [item["output_name"] for item in tables]
    payload["output_count"] = len(tables)
    payload["family_counts"] = {
        family: sum(item["family"] == family for item in tables)
        for family in ("fact", "dim", "bridge", "agg", "analytics")
    }
    payload["authored_decision_count"] = sum(
        item["semantic_decision_state"] == "authored" for item in tables
    )
    payload["missing_decision_count"] = sum(
        item["semantic_decision_state"] == "missing" for item in tables
    )
    row_roots = [item["row_sha256"] for item in tables]
    for field in (
        "structural_inventory_sha256",
        "candidate_census_sha256",
        "candidate_source_authority_sha256",
        "stable_disposition_inventory_sha256",
        "semantic_authority_inventory_sha256",
        "semantic_decision_corpus_sha256",
        "semantic_decision_corpus_source_bytes_sha256",
    ):
        payload[field] = packet_module._sha256(  # noqa: SLF001
            {"attack": attack, "field": field, "row_roots": row_roots}
        )
    payload["packet_sha256"] = packet_module._sha256(  # noqa: SLF001
        {key: value for key, value in payload.items() if key != "packet_sha256"}
    )
    return json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


@pytest.mark.parametrize(
    "mutation",
    ("purpose", "grain", "witness"),
)
def test_public_replay_rejects_coherently_resealed_authored_decision_mutations(
    packet: StarSemanticReviewPacketV1,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payload = json.loads(packet.canonical_bytes)
    table = next(
        item for item in payload["tables"] if item["semantic_decision_state"] == "authored"
    )
    decision = table["authored_semantic_decision"]
    assert type(decision) is dict
    if mutation == "purpose":
        decision["purpose_code"] = "coherently-resealed-purpose"
    elif mutation == "grain":
        decision["grain_dimensions"] = [*decision["grain_dimensions"], "resealed_grain"]
    else:
        decision["positive_witness_sha256s"] = ["e" * 64]
    decision["decision_sha256"] = canonical_star_semantic_authoring_sha256(
        {key: value for key, value in decision.items() if key != "decision_sha256"}
    )
    _reseal_table(table)
    raw = _reseal_packet(payload, attack=f"authored-{mutation}")
    monkeypatch.setattr(
        packet_module,
        "compile_current_star_semantic_review_packet",
        lambda: packet,
    )

    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compilation"):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


@pytest.mark.parametrize(
    ("field", "mutate"),
    (
        (
            "structural_observation",
            lambda value: value.__setitem__(
                "direct_purpose_observation", "coherently-resealed-structural-purpose"
            ),
        ),
        (
            "candidate_observation",
            lambda value: value.__setitem__("structural_sha256", "d" * 64),
        ),
        (
            "stable_disposition_inventory_observation",
            lambda value: value.__setitem__("reason_code", "coherently-resealed-reason"),
        ),
    ),
)
def test_public_replay_rejects_coherently_resealed_observation_mutations(
    packet: StarSemanticReviewPacketV1,
    monkeypatch: pytest.MonkeyPatch,
    field: str,
    mutate: Callable[[dict[str, object]], None],
) -> None:
    payload = json.loads(packet.canonical_bytes)
    table = payload["tables"][0]
    observation = table[field]
    assert type(observation) is dict
    mutate(observation)
    _reseal_table(table)
    raw = _reseal_packet(payload, attack=field)
    monkeypatch.setattr(
        packet_module,
        "compile_current_star_semantic_review_packet",
        lambda: packet,
    )

    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compilation"):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


@pytest.mark.parametrize("mutation", ("omission", "extra", "reorder"))
def test_public_replay_rejects_coherently_resealed_denominator_mutations(
    packet: StarSemanticReviewPacketV1,
    monkeypatch: pytest.MonkeyPatch,
    mutation: str,
) -> None:
    payload = json.loads(packet.canonical_bytes)
    tables = payload["tables"]
    assert type(tables) is list
    if mutation == "omission":
        del tables[-1]
    elif mutation == "extra":
        tables.append(dict(tables[-1]))
    else:
        tables.reverse()
    raw = _reseal_packet(payload, attack=f"denominator-{mutation}")
    monkeypatch.setattr(
        packet_module,
        "compile_current_star_semantic_review_packet",
        lambda: packet,
    )

    with pytest.raises(StarSemanticReviewPacketError, match="fixed-source compilation"):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


def test_compiler_serializes_exact_typed_current_source_projections(
    packet: StarSemanticReviewPacketV1,
    sources,
) -> None:
    structural_by_name = {item.output_name: item for item in sources.structural_inventory.tables}
    for table in packet.tables:
        assert json.loads(table.structural_observation_json) == (
            packet_module._structural_observation(  # noqa: SLF001
                structural_by_name[table.output_name]
            )
        )
        assert StableModelCandidateV1.from_dict(
            json.loads(table.candidate_observation_json)
        ).to_dict() == json.loads(table.candidate_observation_json)
        assert ModelCandidateCensusEvidenceV1.from_dict(
            json.loads(table.candidate_source_evidence_observation_json)
        ).to_dict() == json.loads(table.candidate_source_evidence_observation_json)
        assert StableModelDispositionV1.from_dict(
            json.loads(table.stable_disposition_inventory_observation_json)
        ).to_dict() == json.loads(table.stable_disposition_inventory_observation_json)
        assert StarTableSemanticAuthorityV1.from_dict(
            json.loads(table.semantic_authority_observation_json)
        ).to_dict() == json.loads(table.semantic_authority_observation_json)
    authored = next(item for item in packet.tables if item.semantic_decision_state == "authored")
    assert authored.authored_semantic_decision_json is not None
    assert StarTableSemanticDecisionV1.from_dict(
        json.loads(authored.authored_semantic_decision_json)
    ).to_dict() == json.loads(authored.authored_semantic_decision_json)


@pytest.mark.parametrize(
    "raw",
    (
        b'{"duplicate":1,"duplicate":2}',
        b'{"number":NaN}',
        b'{"number":1e999}',
    ),
)
def test_raw_replay_rejects_duplicate_and_nonfinite_json(raw: bytes) -> None:
    with pytest.raises(StarSemanticReviewPacketError):
        StarSemanticReviewPacketV1.from_canonical_bytes(raw)


def test_raw_replay_rejects_deep_oversized_and_overwide_json() -> None:
    deep: object = None
    for _ in range(packet_module._MAX_JSON_DEPTH + 2):  # noqa: SLF001
        deep = {"nested": deep}
    deep_raw = json.dumps(deep, separators=(",", ":"), sort_keys=True).encode()
    oversized = b'{"value":"' + b"x" * packet_module._MAX_CANONICAL_BYTES + b'"}'  # noqa: SLF001
    overwide = json.dumps(
        {"values": list(range(packet_module._MAX_JSON_CONTAINER_ITEMS + 1))},  # noqa: SLF001
        separators=(",", ":"),
        sort_keys=True,
    ).encode()

    for raw in (deep_raw, oversized, overwide):
        with pytest.raises(StarSemanticReviewPacketError):
            StarSemanticReviewPacketV1.from_canonical_bytes(raw)
