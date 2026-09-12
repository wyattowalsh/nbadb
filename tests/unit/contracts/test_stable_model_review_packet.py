from __future__ import annotations

import ast
import hashlib
import json
import tracemalloc
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

from nbadb.contracts import stable_model_review_packet as review_packet_module
from nbadb.contracts.model_candidate_census import (
    canonical_analytical_needs_authority_v1,
    compile_current_model_candidate_census,
)
from nbadb.contracts.stable_model_disposition import draft_required_model_dispositions
from nbadb.contracts.stable_model_review_packet import (
    GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND,
    STABLE_MODEL_REVIEW_CANDIDATE_COUNT,
    STABLE_MODEL_REVIEW_MAX_SHARD_SIZE,
    STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION,
    STABLE_MODEL_REVIEW_SHARD_COUNT,
    StableModelReviewChallengeV1,
    StableModelReviewContentV1,
    StableModelReviewPacketError,
    StableModelReviewPacketV1,
    StableModelReviewResultSlotV1,
    StableModelReviewShardV1,
    compile_stable_model_review_packet,
)

SOURCE_SHA = "1" * 40
EXPECTED_DEPTH_COUNTS = (431, 439, 219, 17, 11, 8, 3)
EXPECTED_SHARD_COUNTS = (7, 7, 4, 1, 1, 1, 1)
REQUIRED_VALIDATION_CLASSES = ("mutation", "negative", "positive")


@pytest.fixture(scope="module")
def census():
    return compile_current_model_candidate_census(
        analytical_needs=canonical_analytical_needs_authority_v1()
    )


@pytest.fixture(scope="module")
def disposition_drafts(census):
    return draft_required_model_dispositions(
        candidate_source_authority_sha256=census.candidate_source_authority_sha256,
        candidates=census.candidates,
    )


@pytest.fixture(scope="module")
def packet(census, disposition_drafts):
    return compile_stable_model_review_packet(
        source_sha=SOURCE_SHA,
        census=census,
        disposition_drafts=disposition_drafts,
    )


def _all_slots(packet: StableModelReviewPacketV1) -> tuple[StableModelReviewResultSlotV1, ...]:
    return tuple(slot for shard in packet.shards for slot in shard.result_slots)


def test_current_census_recomputation_emits_exact_red_denominator(
    packet: StableModelReviewPacketV1,
) -> None:
    census_bytes = packet.candidate_census_input.canonical_json.encode("utf-8")
    census_payload = json.loads(census_bytes)

    assert packet.schema_version == STABLE_MODEL_REVIEW_PACKET_SCHEMA_VERSION == 1
    assert packet.source_sha == SOURCE_SHA
    assert packet.candidate_count == STABLE_MODEL_REVIEW_CANDIDATE_COUNT == 1_128
    assert packet.shard_count == STABLE_MODEL_REVIEW_SHARD_COUNT == 22
    assert packet.topological_depth_counts == EXPECTED_DEPTH_COUNTS
    assert packet.shard_depth_counts == EXPECTED_SHARD_COUNTS
    assert packet.max_shard_candidate_count == STABLE_MODEL_REVIEW_MAX_SHARD_SIZE == 64
    assert len(census_payload["candidates"]) == 1_128
    assert len(census_payload["evidence"]) == 1_128
    assert hashlib.sha256(census_bytes).hexdigest() == (
        packet.candidate_census_canonical_bytes_sha256
    )
    assert census_payload["census_sha256"] == packet.candidate_census_sha256
    assert census_payload["candidate_inventory_sha256"] == packet.candidate_inventory_sha256
    assert census_payload["candidate_source_authority_sha256"] == (
        packet.candidate_source_authority_sha256
    )
    assert packet.authority_admitted is False
    assert packet.review_gate_green is False
    assert packet.work_state == "pending_external_review"


def test_shards_are_exact_once_bounded_and_never_cross_depths(
    packet: StableModelReviewPacketV1,
) -> None:
    slots = _all_slots(packet)
    slot_ids = tuple(item.candidate_id for item in slots)

    assert len(slots) == 1_128
    assert len(set(slot_ids)) == 1_128
    assert set(slot_ids) == {item.subject_id for item in packet.review_inputs}
    assert Counter(item.topological_depth for item in slots) == dict(
        enumerate(EXPECTED_DEPTH_COUNTS)
    )
    assert Counter(item.topological_depth for item in packet.shards) == dict(
        enumerate(EXPECTED_SHARD_COUNTS)
    )
    assert all(1 <= len(item.result_slots) <= 64 for item in packet.shards)
    assert all(
        {slot.topological_depth for slot in shard.result_slots} == {shard.topological_depth}
        for shard in packet.shards
    )
    assert tuple((item.topological_depth, item.shard_ordinal) for item in packet.shards) == tuple(
        (depth, ordinal)
        for depth, count in enumerate(EXPECTED_SHARD_COUNTS)
        for ordinal in range(count)
    )


def test_every_result_slot_requires_three_receipt_classes_but_contains_none(
    packet: StableModelReviewPacketV1,
) -> None:
    slots = _all_slots(packet)

    assert all(item.required_validation_classes == REQUIRED_VALIDATION_CLASSES for item in slots)
    assert all(item.required_review_input_sha256s for item in slots)
    assert all(item.review_receipt_sha256 is None for item in slots)
    assert all(item.validation_receipt_sha256s == () for item in slots)
    assert all(item.work_state == "pending_external_review" for item in slots)


def test_content_addressed_inputs_bind_candidate_evidence_and_draft(
    packet: StableModelReviewPacketV1,
) -> None:
    slots_by_id = {item.candidate_id: item for item in _all_slots(packet)}

    for content in packet.review_inputs:
        payload = content.content
        candidate_id = payload["candidate"]["candidate_id"]
        slot = slots_by_id[candidate_id]
        assert content.subject_id == candidate_id
        assert content.content_sha256 == slot.review_input_sha256
        assert payload["evidence"]["candidate_id"] == candidate_id
        assert payload["disposition_draft"]["candidate_id"] == candidate_id
        assert payload["candidate_source_authority_sha256"] == (
            packet.candidate_source_authority_sha256
        )
        assert content.content_sha256 in slot.required_review_input_sha256s
        assert packet.candidate_census_sha256 in slot.required_review_input_sha256s
        assert packet.candidate_census_canonical_bytes_sha256 in (
            slot.required_review_input_sha256s
        )
        assert packet.disposition_draft_inventory_sha256 in (slot.required_review_input_sha256s)


def test_challenges_are_exact_fixed_github_review_work_and_remain_red(
    packet: StableModelReviewPacketV1,
) -> None:
    challenges = packet.challenges

    assert len(challenges) == 22
    assert {item.kind for item in challenges} == {GITHUB_PULL_REQUEST_REVIEW_CHALLENGE_KIND}
    assert all(item.work_packet_sha256 == packet.work_packet_sha256 for item in challenges)
    assert all(item.challenge_state == "awaiting_github_pull_request_review" for item in challenges)
    assert all(item.authority_admitted is False for item in challenges)
    assert tuple(item.shard_id for item in challenges) == tuple(
        item.shard_id for item in packet.shards
    )
    assert tuple(item.candidate_count for item in challenges) == tuple(
        len(item.result_slots) for item in packet.shards
    )


def test_packet_and_all_nested_work_dtos_round_trip_canonically(
    packet: StableModelReviewPacketV1,
) -> None:
    slot = packet.shards[0].result_slots[0]
    shard = packet.shards[0]
    challenge = packet.challenges[0]

    assert StableModelReviewResultSlotV1.from_canonical_bytes(slot.canonical_bytes) == slot
    assert StableModelReviewShardV1.from_canonical_bytes(shard.canonical_bytes) == shard
    assert StableModelReviewChallengeV1.from_canonical_bytes(challenge.canonical_bytes) == challenge
    assert StableModelReviewPacketV1.from_canonical_bytes(packet.canonical_bytes) == packet
    assert (
        json.dumps(
            packet.to_dict(),
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        == packet.canonical_bytes
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("review_receipt_sha256", "a" * 64, "cannot contain review or validation receipts"),
        (
            "validation_receipt_sha256s",
            ("b" * 64,),
            "cannot contain review or validation receipts",
        ),
        (
            "required_validation_classes",
            ("positive", "negative", "mutation"),
            "exact mutation, negative, and positive",
        ),
    ],
)
def test_result_slots_reject_self_certified_or_mutated_review_results(
    packet: StableModelReviewPacketV1,
    field: str,
    value: object,
    match: str,
) -> None:
    slot = packet.shards[0].result_slots[0]

    with pytest.raises(StableModelReviewPacketError, match=match):
        replace(slot, **{field: value})


def test_shard_rejects_cross_depth_duplicate_oversized_and_foreign_work(
    packet: StableModelReviewPacketV1,
) -> None:
    shard = packet.shards[0]
    cross_depth = replace(shard.result_slots[0], topological_depth=1)
    with pytest.raises(StableModelReviewPacketError, match="crosses topological depths"):
        replace(shard, result_slots=(cross_depth, *shard.result_slots[1:]))

    duplicate_slots = (*shard.result_slots[:-1], shard.result_slots[-2])
    with pytest.raises(StableModelReviewPacketError, match="duplicated or unsorted"):
        replace(shard, result_slots=duplicate_slots)

    with pytest.raises(StableModelReviewPacketError, match="empty, oversized, or foreign"):
        replace(shard, result_slots=(*shard.result_slots, shard.result_slots[-1]))

    foreign = shard.to_dict()
    foreign["source_sha"] = "2" * 40
    with pytest.raises(StableModelReviewPacketError, match="differs from exact reconstruction"):
        StableModelReviewShardV1.from_dict(foreign)


def test_stale_slot_and_challenge_mutations_fail_digest_reconstruction(
    packet: StableModelReviewPacketV1,
) -> None:
    slot = packet.shards[0].result_slots[0].to_dict()
    slot["candidate_id"] = f"{slot['candidate_id']}:foreign"
    with pytest.raises(StableModelReviewPacketError, match="differs from exact red reconstruction"):
        StableModelReviewResultSlotV1.from_dict(slot)

    challenge = packet.challenges[0].to_dict()
    challenge["work_packet_sha256"] = "e" * 64
    with pytest.raises(StableModelReviewPacketError, match="differs from exact reconstruction"):
        StableModelReviewChallengeV1.from_dict(challenge)


def test_canonical_json_rejects_duplicate_nonfinite_whitespace_and_wrong_types(
    packet: StableModelReviewPacketV1,
) -> None:
    challenge = packet.challenges[0]
    duplicate = challenge.canonical_bytes.replace(
        b'{"authority_admitted"',
        b'{"kind":"duplicate","authority_admitted"',
        1,
    )
    with pytest.raises(StableModelReviewPacketError, match="duplicate key: kind"):
        StableModelReviewChallengeV1.from_canonical_bytes(duplicate)

    with pytest.raises(StableModelReviewPacketError, match="non-finite constant: NaN"):
        StableModelReviewChallengeV1.from_canonical_bytes(b'{"value":NaN}')

    with pytest.raises(StableModelReviewPacketError, match="not canonical"):
        StableModelReviewChallengeV1.from_canonical_bytes(challenge.canonical_bytes + b"\n")

    wrong_type = challenge.to_dict()
    wrong_type["candidate_count"] = True
    with pytest.raises(StableModelReviewPacketError, match="schema is invalid"):
        StableModelReviewChallengeV1.from_dict(wrong_type)


def test_canonical_json_rejects_size_overflow() -> None:
    with pytest.raises(StableModelReviewPacketError, match="empty or exceed their bound"):
        StableModelReviewChallengeV1.from_canonical_bytes(b" " * (1024 * 1024 + 1))


def test_lexical_guard_rejects_depth_before_json_materialization(monkeypatch) -> None:
    raw = b"[" * 65 + b"0" + b"]" * 65
    decoder_called = False

    def forbidden_decoder(*_args, **_kwargs):
        nonlocal decoder_called
        decoder_called = True
        raise AssertionError("materializing decoder must not run")

    monkeypatch.setattr(review_packet_module.json, "loads", forbidden_decoder)
    with pytest.raises(StableModelReviewPacketError, match="JSON depth budget"):
        StableModelReviewChallengeV1.from_canonical_bytes(raw)
    assert decoder_called is False


def test_lexical_guard_rejects_high_node_input_before_materialization(monkeypatch) -> None:
    raw = b"[" + b"0," * review_packet_module._MAX_JSON_NODES + b"0]"
    assert len(raw) < review_packet_module._MAX_PACKET_BYTES
    decoder_called = False

    def forbidden_decoder(*_args, **_kwargs):
        nonlocal decoder_called
        decoder_called = True
        raise AssertionError("materializing decoder must not run")

    monkeypatch.setattr(review_packet_module.json, "loads", forbidden_decoder)
    tracemalloc.start()
    try:
        with pytest.raises(StableModelReviewPacketError, match="JSON node budget"):
            StableModelReviewPacketV1.from_canonical_bytes(raw)
        _current, peak_bytes = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()

    assert decoder_called is False
    assert peak_bytes < 4 * 1024 * 1024


def test_lexical_guard_treats_escaped_structural_string_bytes_as_opaque() -> None:
    opaque = ('[{"key":[],"other":{}}],:' * 100) + '\\"tail'
    canonical_json = json.dumps(
        {"kind": "test", "opaque": opaque, "schema_version": 1},
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    content = StableModelReviewContentV1(
        content_kind="candidate_review_input",
        subject_id="fact:opaque-structure",
        canonical_json=canonical_json,
    )

    assert content.content["opaque"] == opaque


@pytest.mark.parametrize("error_type", [MemoryError, RecursionError])
def test_materializing_decoder_resource_failures_are_contract_rejections(
    monkeypatch,
    error_type: type[BaseException],
) -> None:
    def failed_decoder(*_args, **_kwargs):
        raise error_type("simulated decoder resource exhaustion")

    monkeypatch.setattr(review_packet_module.json, "loads", failed_decoder)
    with pytest.raises(StableModelReviewPacketError, match="decoder resource bounds"):
        StableModelReviewChallengeV1.from_canonical_bytes(b"{}")


def test_lexical_guard_memory_failure_is_a_contract_rejection(monkeypatch) -> None:
    def failed_guard(*_args, **_kwargs):
        raise MemoryError("simulated lexical guard resource exhaustion")

    monkeypatch.setattr(review_packet_module, "_guard_json_lexical_structure", failed_guard)
    with pytest.raises(StableModelReviewPacketError, match="before JSON decoding"):
        StableModelReviewChallengeV1.from_canonical_bytes(b"{}")


def test_content_rejects_digest_mutation_and_noncanonical_json() -> None:
    canonical_json = '{"kind":"test","schema_version":1}'
    content = StableModelReviewContentV1(
        content_kind="candidate_review_input",
        subject_id="fact:test",
        canonical_json=canonical_json,
    )

    with pytest.raises(StableModelReviewPacketError, match="digest differs"):
        replace(content, content_sha256="0" * 64)
    with pytest.raises(StableModelReviewPacketError, match="not canonical"):
        replace(content, canonical_json='{"schema_version": 1, "kind": "test"}')


def test_module_has_no_authority_admission_network_or_review_receipt_constructor() -> None:
    source_path = Path(__file__).parents[3] / "src/nbadb/contracts/stable_model_review_packet.py"
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_roots = {
        node.names[0].name.split(".", maxsplit=1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
    }
    imported_modules = {
        (node.module or "") for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)
    }
    constructed_names = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert imported_roots.isdisjoint({"httpx", "requests", "subprocess", "urllib"})
    assert all("review_evidence" not in module for module in imported_modules)
    assert "ReviewReceiptV1" not in constructed_names
    assert "github.com" not in source
    assert "api.github.com" not in source
