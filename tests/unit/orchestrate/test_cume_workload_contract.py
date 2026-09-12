from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from nbadb.orchestrate.cume_workload_contract import (
    CumeEntityKind,
    CumeWorkloadContractError,
    CumeWorkloadDisposition,
    CumeWorkloadValue,
    encode_cume_game_ids,
    normalize_cume_game_ids,
)

_GAME_IDS = ("0022400001", "0022400002", "0022400003")


def _complete(**overrides: object) -> CumeWorkloadValue:
    values: dict[str, object] = {
        "entity_kind": CumeEntityKind.PLAYER,
        "entity_id": 201939,
        "season": "2024-25",
        "season_type": "Regular Season",
        "game_ids": _GAME_IDS,
        "foundation_receipt_sha256": "a" * 64,
        "provider_authority_sha256": "b" * 64,
    }
    values.update(overrides)
    return CumeWorkloadValue.complete(**values)  # type: ignore[arg-type]


def test_game_ids_preserve_exact_order_and_pipe_encoding() -> None:
    assert normalize_cume_game_ids(_GAME_IDS) == _GAME_IDS
    assert normalize_cume_game_ids("0022400001|0022400002|0022400003") == _GAME_IDS
    assert encode_cume_game_ids(_GAME_IDS) == "0022400001|0022400002|0022400003"


@pytest.mark.parametrize(
    "game_ids, message",
    [
        ((), "nonempty"),
        (set(_GAME_IDS), "ordered sequence"),
        (("0022400001", "0022400001"), "duplicates"),
        (("0022400001", 224000002), "ten-digit string"),
        ("0022400001|", "ten-digit string"),
        ("0022400001,0022400002", "ten-digit string"),
        (" 0022400001", "ten-digit string"),
        ("002240001", "ten-digit string"),
    ],
)
def test_game_ids_reject_empty_unordered_duplicate_or_nonexact_values(
    game_ids: object,
    message: str,
) -> None:
    with pytest.raises(CumeWorkloadContractError, match=message):
        normalize_cume_game_ids(game_ids)


def test_complete_value_binds_scope_order_receipt_and_provider_authority() -> None:
    workload = _complete()

    assert workload.entity_kind is CumeEntityKind.PLAYER
    assert workload.disposition is CumeWorkloadDisposition.COMPLETE
    assert workload.game_ids == _GAME_IDS
    assert workload.encoded_game_ids == "0022400001|0022400002|0022400003"
    assert len(workload.content_sha256) == 64
    assert workload.generation_basename == f"cume-workload.{workload.content_sha256}.json"
    assert workload.to_payload() == {
        "content_sha256": workload.content_sha256,
        "schema_version": 1,
        "kind": "nbadb_cume_workload",
        "entity_kind": "player",
        "entity_id": 201939,
        "season": "2024-25",
        "season_type": "Regular Season",
        "game_ids": list(_GAME_IDS),
        "disposition": "complete",
        "typed_zero_reason": None,
        "foundation_receipt_sha256": "a" * 64,
        "provider_authority_sha256": "b" * 64,
    }


def test_value_is_immutable_deterministic_and_dropped_or_reordered_game_sensitive() -> None:
    first = _complete()
    second = _complete()
    dropped = _complete(game_ids=_GAME_IDS[:-1])
    reordered = _complete(game_ids=tuple(reversed(_GAME_IDS)))
    drifted_receipt = _complete(foundation_receipt_sha256="c" * 64)

    assert first.canonical_bytes == second.canonical_bytes
    assert first.content_sha256 == second.content_sha256
    assert dropped.canonical_bytes != first.canonical_bytes
    assert dropped.content_sha256 != first.content_sha256
    assert reordered.content_sha256 != first.content_sha256
    assert drifted_receipt.content_sha256 != first.content_sha256
    with pytest.raises(FrozenInstanceError):
        first.entity_id = 1  # type: ignore[misc]


@pytest.mark.parametrize(
    ("factory", "missing_authority"),
    [
        (
            lambda: _complete(
                foundation_receipt_sha256=None,
                provider_authority_sha256=None,
            ),
            "foundation_receipt_sha256",
        ),
        (lambda: _complete(foundation_receipt_sha256=None), "foundation_receipt_sha256"),
        (lambda: _complete(provider_authority_sha256=None), "provider_authority_sha256"),
        (
            lambda: CumeWorkloadValue.typed_zero(
                entity_kind=CumeEntityKind.TEAM,
                entity_id=1610612744,
                season="2024-25",
                season_type="Playoffs",
                reason_code="foundation_complete_no_games",
            ),
            "foundation_receipt_sha256",
        ),
        (
            lambda: CumeWorkloadValue.typed_zero(
                entity_kind=CumeEntityKind.TEAM,
                entity_id=1610612744,
                season="2024-25",
                season_type="Playoffs",
                reason_code="foundation_complete_no_games",
                foundation_receipt_sha256="c" * 64,
            ),
            "provider_authority_sha256",
        ),
        (
            lambda: CumeWorkloadValue.typed_zero(
                entity_kind=CumeEntityKind.TEAM,
                entity_id=1610612744,
                season="2024-25",
                season_type="Playoffs",
                reason_code="foundation_complete_no_games",
                provider_authority_sha256="d" * 64,
            ),
            "foundation_receipt_sha256",
        ),
    ],
)
def test_complete_and_typed_zero_require_both_exact_authorities(
    factory: object,
    missing_authority: str,
) -> None:
    with pytest.raises(CumeWorkloadContractError, match=missing_authority):
        factory()  # type: ignore[operator]


@pytest.mark.parametrize(
    "factory",
    [
        _complete,
        lambda: CumeWorkloadValue.typed_zero(
            entity_kind=CumeEntityKind.TEAM,
            entity_id=1610612744,
            season="2024-25",
            season_type="Playoffs",
            reason_code="foundation_complete_no_games",
            foundation_receipt_sha256="c" * 64,
            provider_authority_sha256="d" * 64,
        ),
    ],
)
def test_strict_codec_roundtrips_complete_and_typed_zero(factory: object) -> None:
    workload = factory()  # type: ignore[operator]
    decoded = CumeWorkloadValue.from_canonical_bytes(workload.canonical_bytes)

    assert decoded == workload
    assert CumeWorkloadValue.from_dict(json.loads(workload.canonical_bytes)) == workload


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda payload: payload.__setitem__("schema_version", True), "schema identity"),
        (lambda payload: payload.__setitem__("schema_version", 1.0), "schema identity"),
        (lambda payload: payload.__setitem__("entity_id", True), "positive integer"),
        (lambda payload: payload.__setitem__("game_ids", tuple(_GAME_IDS)), "must be a list"),
        (
            lambda payload: payload.__setitem__("foundation_receipt_sha256", None),
            "foundation_receipt_sha256",
        ),
        (
            lambda payload: payload.__setitem__("provider_authority_sha256", None),
            "provider_authority_sha256",
        ),
        (lambda payload: payload.__setitem__("unknown", "value"), "fields are invalid"),
        (lambda payload: payload.pop("foundation_receipt_sha256"), "fields are invalid"),
        (lambda payload: payload.pop("provider_authority_sha256"), "fields are invalid"),
        (lambda payload: payload.pop("season"), "fields are invalid"),
    ],
)
def test_strict_dict_decoder_rejects_aliases_and_field_drift(
    mutate: object,
    message: str,
) -> None:
    payload = json.loads(_complete().canonical_bytes)
    mutate(payload)  # type: ignore[operator]

    with pytest.raises(CumeWorkloadContractError, match=message):
        CumeWorkloadValue.from_dict(payload)


@pytest.mark.parametrize(
    "encoded, message",
    [
        (b" {}", "not canonical"),
        (b"{}\n", "not canonical"),
        (b'{"kind":"nbadb_cume_workload","kind":"logical_call"}', "duplicate"),
        (b'{"schema_version":NaN}', "non-finite"),
        (b"[]", "root must be an object"),
        (b"\xff", "not valid JSON"),
    ],
)
def test_strict_canonical_decoder_rejects_noncanonical_or_unsafe_json(
    encoded: bytes,
    message: str,
) -> None:
    with pytest.raises(CumeWorkloadContractError, match=message):
        CumeWorkloadValue.from_canonical_bytes(encoded)


def test_strict_canonical_decoder_requires_exact_bytes_and_current_body() -> None:
    workload = _complete()
    payload = json.loads(workload.canonical_bytes)
    encoded = json.dumps(payload, sort_keys=False, separators=(",", ":")).encode()
    if encoded == workload.canonical_bytes:
        encoded = json.dumps(payload, sort_keys=True, indent=2).encode()

    with pytest.raises(CumeWorkloadContractError, match="not canonical"):
        CumeWorkloadValue.from_canonical_bytes(encoded)
    with pytest.raises(CumeWorkloadContractError, match="canonical input must be bytes"):
        CumeWorkloadValue.from_canonical_bytes("not-bytes")  # type: ignore[arg-type]


def test_typed_zero_is_content_addressed_complete_zero_evidence_but_not_executable() -> None:
    workload = CumeWorkloadValue.typed_zero(
        entity_kind=CumeEntityKind.TEAM,
        entity_id=1610612744,
        season="2024-25",
        season_type="Playoffs",
        reason_code="foundation_complete_no_games",
        foundation_receipt_sha256="c" * 64,
        provider_authority_sha256="d" * 64,
    )

    assert workload.disposition is CumeWorkloadDisposition.TYPED_ZERO
    assert workload.game_ids == ()
    assert workload.foundation_receipt_sha256 == "c" * 64
    assert workload.provider_authority_sha256 == "d" * 64
    assert workload.to_payload() == {
        "content_sha256": workload.content_sha256,
        "schema_version": 1,
        "kind": "nbadb_cume_workload",
        "entity_kind": "team",
        "entity_id": 1610612744,
        "season": "2024-25",
        "season_type": "Playoffs",
        "game_ids": [],
        "disposition": "typed_zero",
        "typed_zero_reason": "foundation_complete_no_games",
        "foundation_receipt_sha256": "c" * 64,
        "provider_authority_sha256": "d" * 64,
    }
    assert CumeWorkloadValue.from_canonical_bytes(workload.canonical_bytes) == workload
    with pytest.raises(CumeWorkloadContractError, match="not executable"):
        _ = workload.encoded_game_ids


def test_typed_zero_requires_empty_ids_and_a_stable_reason() -> None:
    with pytest.raises(CumeWorkloadContractError, match="stable reason"):
        CumeWorkloadValue.typed_zero(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            reason_code="has spaces",
        )
    with pytest.raises(CumeWorkloadContractError, match="must not contain"):
        CumeWorkloadValue(
            entity_kind=CumeEntityKind.PLAYER,
            entity_id=201939,
            season="2024-25",
            season_type="Regular Season",
            game_ids=("0022400001",),
            disposition=CumeWorkloadDisposition.TYPED_ZERO,
            typed_zero_reason="foundation_complete_no_games",
        )


@pytest.mark.parametrize(
    "overrides, message",
    [
        ({"entity_id": 0}, "positive integer"),
        ({"season": "2024-24"}, "consecutive"),
        ({"season_type": "regular season"}, "supported value"),
        ({"foundation_receipt_sha256": "A" * 64}, "lowercase SHA-256"),
        ({"provider_authority_sha256": "short"}, "lowercase SHA-256"),
    ],
)
def test_value_rejects_invalid_scope_or_authority(
    overrides: dict[str, object],
    message: str,
) -> None:
    with pytest.raises(CumeWorkloadContractError, match=message):
        _complete(**overrides)
