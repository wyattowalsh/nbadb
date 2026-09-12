from __future__ import annotations

import hashlib
import inspect
import json
from copy import copy
from dataclasses import replace
from datetime import datetime, timedelta, tzinfo
from functools import cache
from typing import Any, cast

import polars as pl
import pytest
from pandera.errors import SchemaError

from nbadb.contracts import raw_result_cell_authority
from nbadb.contracts.raw_request_authority import (
    RawRequestAuthorityBundleV2,
    RequestObservationV2,
    ResultOccurrenceV2,
    decode_parser_input_object,
)
from nbadb.contracts.raw_result_cell_authority import (
    RawNbaApiResultCellV2,
    RawResultCellAuthorityError,
    RawResultCellAuthorityReceiptV2,
    RawResultCellPublicTableProofV2,
    validate_raw_result_cell_authority,
    validate_raw_result_cell_authority_receipt,
    validate_raw_result_cell_public_table,
)
from nbadb.core.nba_api_runtime_contract import pinned_runtime_contracts
from nbadb.extract.nba_api_adapter import (
    fetch_static_packet,
    rederive_raw_authority_stats_rows,
    rederive_raw_authority_stats_wide_rows,
)
from nbadb.schemas.raw import nba_api_result_cell as result_cell_schema
from nbadb.schemas.raw.nba_api_result_cell import RawNbaApiResultCellSchema
from tests.unit.contracts.test_raw_request_authority import (
    _live_occurrence_reseal_bundle,
    _static_bundle,
    _stats_fallback_bundle,
    _strict_stats_bundle,
)

_SHA_A = "a" * 64
_SHA_B = "b" * 64


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _cell(
    *,
    observation_sha256: str = _SHA_A,
    occurrence_sha256: str = _SHA_B,
    cell_ordinal: int = 0,
    row_ordinal: int = 0,
    header_ordinal: int = 0,
    header_name: str = "FIELD",
    value: object = 1,
) -> RawNbaApiResultCellV2:
    return RawNbaApiResultCellV2.build(
        observation_sha256=observation_sha256,
        occurrence_sha256=occurrence_sha256,
        cell_ordinal=cell_ordinal,
        row_ordinal=row_ordinal,
        header_ordinal=header_ordinal,
        header_name=header_name,
        value=value,
    )


def _canonical_cells(
    bundle: RawRequestAuthorityBundleV2,
    cells: list[RawNbaApiResultCellV2],
) -> tuple[RawNbaApiResultCellV2, ...]:
    ordered_observations = sorted(
        bundle.observations,
        key=lambda item: (
            *raw_result_cell_authority._observation_semantic_order_key(item),
            item.attempt.observation_sha256,
        ),
    )
    observation_order = {
        item.attempt.observation_sha256: ordinal
        for ordinal, item in enumerate(ordered_observations)
    }
    occurrence_order = {
        item.occurrence_sha256: (
            observation_order[item.observation_sha256],
            item.occurrence_ordinal,
        )
        for item in bundle.occurrences
    }
    return tuple(
        sorted(
            cells,
            key=lambda item: (
                *occurrence_order[item.occurrence_sha256],
                item.cell_ordinal,
            ),
        )
    )


@cache
def _stats_case() -> tuple[RawRequestAuthorityBundleV2, tuple[RawNbaApiResultCellV2, ...]]:
    bundle = _strict_stats_bundle()
    observation = bundle.observations[0]
    body = bundle.objects[0]
    derivations = rederive_raw_authority_stats_rows(
        endpoint_id=observation.attempt.endpoint_id,
        parser_input=decode_parser_input_object(body),
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
    )
    by_ordinal = {item.result_set.canonical_index: item for item in derivations}
    cells: list[RawNbaApiResultCellV2] = []
    for occurrence in bundle.occurrences:
        derivation = by_ordinal[occurrence.canonical_result_ordinal]
        for row_ordinal, row in enumerate(derivation.rows):
            for header_ordinal, provider_cell in enumerate(row):
                cells.append(
                    _cell(
                        observation_sha256=occurrence.observation_sha256,
                        occurrence_sha256=occurrence.occurrence_sha256,
                        cell_ordinal=(row_ordinal * occurrence.header_count + header_ordinal),
                        row_ordinal=row_ordinal,
                        header_ordinal=header_ordinal,
                        header_name=derivation.ordered_headers[header_ordinal],
                        value=json.loads(provider_cell.canonical_json),
                    )
                )
    return bundle, _canonical_cells(bundle, cells)


@cache
def _wide_plus_lossless_case() -> tuple[
    RawRequestAuthorityBundleV2,
    tuple[RawNbaApiResultCellV2, ...],
]:
    bundle, observation, occurrences, _landings = _stats_fallback_bundle("additive_result")
    body = bundle.objects[0]
    derivations = rederive_raw_authority_stats_wide_rows(
        endpoint_id=observation.attempt.endpoint_id,
        parser_input=decode_parser_input_object(body),
        provider_authority_sha256=observation.attempt.provider_authority_sha256,
        endpoint_contract_sha256_value=observation.attempt.endpoint_contract_sha256,
    )
    by_provider_identity = {
        (item.result_set.provider_index, item.result_set.name): item for item in derivations
    }
    cells: list[RawNbaApiResultCellV2] = []
    for occurrence in occurrences:
        if occurrence.landing_disposition != "wide_plus_lossless":
            continue
        derivation = by_provider_identity[
            (occurrence.provider_result_ordinal, occurrence.result_name)
        ]
        for row_ordinal, row in enumerate(derivation.rows):
            for header_ordinal, provider_cell in enumerate(row):
                cells.append(
                    _cell(
                        observation_sha256=occurrence.observation_sha256,
                        occurrence_sha256=occurrence.occurrence_sha256,
                        cell_ordinal=(row_ordinal * occurrence.header_count + header_ordinal),
                        row_ordinal=row_ordinal,
                        header_ordinal=header_ordinal,
                        header_name=derivation.ordered_headers[header_ordinal],
                        value=json.loads(provider_cell.canonical_json),
                    )
                )
    return bundle, _canonical_cells(bundle, cells)


@cache
def _static_case() -> tuple[RawRequestAuthorityBundleV2, tuple[RawNbaApiResultCellV2, ...]]:
    bundle, observation, occurrence, _landing = _static_bundle()
    packet = fetch_static_packet(observation.attempt.endpoint_id)
    cells: list[RawNbaApiResultCellV2] = []
    for row_ordinal, row in enumerate(packet.frame.rows()):
        for header_ordinal, value in enumerate(row):
            cells.append(
                _cell(
                    observation_sha256=observation.attempt.observation_sha256,
                    occurrence_sha256=occurrence.occurrence_sha256,
                    cell_ordinal=(row_ordinal * occurrence.header_count + header_ordinal),
                    row_ordinal=row_ordinal,
                    header_ordinal=header_ordinal,
                    header_name=packet.headers[header_ordinal],
                    value=value,
                )
            )
    return bundle, _canonical_cells(bundle, cells)


@cache
def _combined_case() -> tuple[RawRequestAuthorityBundleV2, tuple[RawNbaApiResultCellV2, ...]]:
    stats_bundle, stats_cells = _stats_case()
    static_bundle, static_cells = _static_case()
    bundle = RawRequestAuthorityBundleV2.build(
        objects=(*stats_bundle.objects, *static_bundle.objects),
        observations=(*stats_bundle.observations, *static_bundle.observations),
        occurrences=(*stats_bundle.occurrences, *static_bundle.occurrences),
        landings=tuple(
            sorted(
                (*stats_bundle.landings, *static_bundle.landings),
                key=lambda item: (item.observation_sha256, item.route_ordinal),
            )
        ),
    )
    return bundle, _canonical_cells(bundle, [*stats_cells, *static_cells])


@pytest.mark.parametrize("case", [_stats_case, _static_case])
def test_stats_and_static_cell_authority_round_trip_and_schema(
    case: Any,
) -> None:
    bundle, cells = case()
    receipt = validate_raw_result_cell_authority(bundle, cells)
    proof = receipt.public_table_proof

    assert receipt.raw_authority_bundle_sha256 == bundle.bundle_sha256
    assert receipt.public_table_proof_sha256 == proof.proof_sha256
    assert proof.cell_count == len(cells)
    assert proof.cells == cells
    assert tuple(RawNbaApiResultCellV2.from_row(item.to_row()) for item in cells) == cells

    frame = pl.DataFrame([item.to_row() for item in cells])
    assert RawNbaApiResultCellSchema.validate(frame).shape == frame.shape


@pytest.mark.parametrize(
    ("value", "presence_kind", "value_kind", "canonical_json"),
    [
        (None, "null", "null", "null"),
        (True, "present", "boolean", "true"),
        (7, "present", "integer", "7"),
        (1.25, "present", "number", "1.25"),
        ("value", "present", "string", '"value"'),
        ([], "empty_array", "array", "[]"),
        ({}, "empty_object", "object", "{}"),
        ([1], "present", "array", "[1]"),
        ({"z": 1, "a": 2}, "present", "object", '{"a":2,"z":1}'),
    ],
)
def test_cell_value_and_presence_projection_is_one_to_one(
    value: object,
    presence_kind: str,
    value_kind: str,
    canonical_json: str,
) -> None:
    cell = _cell(value=value)
    assert cell.presence_kind == presence_kind
    assert cell.value_kind == value_kind
    assert cell.canonical_json == canonical_json
    assert cell.canonical_json_sha256 == _sha256(canonical_json.encode("utf-8"))


@pytest.mark.parametrize(
    "canonical_json",
    [
        "",
        " 1",
        "1.00",
        "NaN",
        "Infinity",
        "-0.0",
        "9223372036854775808",
        '"\\u0061"',
        '{"a":1,"a":2}',
    ],
)
def test_cell_row_rejects_noncanonical_or_hostile_json(canonical_json: str) -> None:
    row = _cell().to_row()
    row["canonical_json"] = canonical_json
    with pytest.raises(RawResultCellAuthorityError):
        RawNbaApiResultCellV2.from_row(row)


@pytest.mark.parametrize(
    "canonical_json",
    [
        "[" * (raw_result_cell_authority._MAX_DEPTH + 1)
        + "0"
        + "]" * (raw_result_cell_authority._MAX_DEPTH + 1),
        "1" * (raw_result_cell_authority._MAX_NUMBER_TOKEN_BYTES + 1),
    ],
)
def test_canonical_json_byte_preflight_rejects_before_decoder_allocation(
    canonical_json: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def poison_loads(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("JSON decoder ran before byte-level admission")

    monkeypatch.setattr(raw_result_cell_authority.json, "loads", poison_loads)
    with pytest.raises(RawResultCellAuthorityError, match="structure|number token"):
        raw_result_cell_authority._decode_canonical_value(canonical_json)


def test_canonical_json_decode_errors_are_sanitized_without_secret_cause(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "do-not-echo-json-secret"
    with pytest.raises(RawResultCellAuthorityError) as exc_info:
        raw_result_cell_authority._decode_canonical_value(f'["{secret}",]')
    assert secret not in str(exc_info.value)
    assert exc_info.value.__cause__ is None

    def recursive_decoder(*_args: object, **_kwargs: object) -> object:
        raise RecursionError(secret)

    monkeypatch.setattr(raw_result_cell_authority.json, "loads", recursive_decoder)
    with pytest.raises(RawResultCellAuthorityError) as recursive_info:
        raw_result_cell_authority._decode_canonical_value("[]")
    assert secret not in str(recursive_info.value)
    assert recursive_info.value.__cause__ is None


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("cell_sha256", "0" * 64),
        ("canonical_json_sha256", "0" * 64),
        ("presence_kind", "null"),
        ("value_kind", "string"),
    ],
)
def test_cell_row_rejects_forged_digests_or_type_projections(
    field_name: str,
    value: object,
) -> None:
    row = _cell().to_row()
    row[field_name] = value
    with pytest.raises(RawResultCellAuthorityError):
        RawNbaApiResultCellV2.from_row(row)


def test_cell_row_requires_exact_contract_column_order() -> None:
    row = _cell().to_row()
    reordered = {key: row[key] for key in reversed(row)}
    with pytest.raises(RawResultCellAuthorityError, match="ordered contract columns"):
        RawNbaApiResultCellV2.from_row(reordered)


def test_cell_row_checks_schema_version_type_before_hostile_equality() -> None:
    class PoisonEquality:
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("schema-version equality was invoked before exact type admission")

    row = _cell().to_row()
    row["schema_version"] = PoisonEquality()
    with pytest.raises(RawResultCellAuthorityError, match="exact integer 2"):
        RawNbaApiResultCellV2.from_row(row)


def test_cell_row_rejects_foreign_string_subclass_keys() -> None:
    class ForeignStr(str):
        pass

    row = _cell().to_row()
    foreign_key_row = {
        ForeignStr(key) if ordinal == 0 else key: value
        for ordinal, (key, value) in enumerate(row.items())
    }
    with pytest.raises(RawResultCellAuthorityError, match="ordered contract columns"):
        RawNbaApiResultCellV2.from_row(foreign_key_row)


def test_cell_builder_rejects_subclasses_and_negative_zero_recursively() -> None:
    class ForeignInt(int):
        pass

    with pytest.raises(RawResultCellAuthorityError, match="foreign JSON type"):
        _cell(value=ForeignInt(1))
    with pytest.raises(RawResultCellAuthorityError, match="negative zero"):
        _cell(value={"nested": [-0.0]})


def test_direct_cell_dto_rejects_hostile_string_subclass_before_encoding() -> None:
    class PoisonStr(str):
        def encode(self, *_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("foreign canonical JSON text was encoded")

    cell = _cell()
    with pytest.raises(RawResultCellAuthorityError, match="exact text"):
        RawNbaApiResultCellV2(
            cell_sha256=cell.cell_sha256,
            observation_sha256=cell.observation_sha256,
            occurrence_sha256=cell.occurrence_sha256,
            cell_ordinal=cell.cell_ordinal,
            row_ordinal=cell.row_ordinal,
            header_ordinal=cell.header_ordinal,
            header_name=cell.header_name,
            presence_kind=cell.presence_kind,
            value_kind=cell.value_kind,
            canonical_json=PoisonStr(cell.canonical_json),
            canonical_json_sha256=cell.canonical_json_sha256,
        )


@pytest.mark.parametrize(
    "value",
    [
        {"nested": [f"ghp_{'A' * 20}"]},
        {"clientSecret": "opaque"},
        {"privateKey": "opaque"},
        {"secretKey": "opaque"},
        {"githubToken": "opaque"},
        {"authToken": "opaque"},
        {"session": "opaque"},
        {"proxyUrl": "opaque"},
        {"vpnServer": "opaque"},
        {"workspacePath": "opaque"},
        {"nested": ["/Users/private-name/result.json"]},
        {"nested": ["/Users/private-name"]},
        {"nested": ["/home/private-name"]},
        {"nested": ["/private/var"]},
        {"nested": ["prefix /Users/private-name suffix"]},
        {"nested": ["prefix /home/private-name suffix"]},
        {"nested": ["prefix /private/var suffix"]},
        {"nested": ["prefix /private/var: suffix"]},
        {"nested": ["prefix /private/var, suffix"]},
        {"nested": ["prefix /private/var. suffix"]},
        {"nested": ["prefix /private/var) suffix"]},
        ["Bearer ABCDEFGHIJKLMNOPQRST"],
        ["Basic ABCDEFGHIJKL"],
        ["public", "Authorization: Bearer abcdefghijklmnop1234"],
        ["public", "prefix Authorization: Bearer abcdefghijklmnop1234 suffix"],
        ["public", "prefix Bearer abcdefghijklmnopqrst"],
        ["public", "prefix Basic abcdefghij12"],
        ["public", "prefix Bearer abcdefghijklmnop1234 suffix"],
    ],
)
def test_cell_builder_rejects_nested_secret_shaped_public_values_without_redaction(
    value: object,
) -> None:
    rendered_secret = json.dumps(value, ensure_ascii=False)
    with pytest.raises(RawResultCellAuthorityError, match="secret-shaped") as exc_info:
        _cell(value=value)
    assert rendered_secret not in str(exc_info.value)


def test_bodyless_static_cells_receive_the_same_intrinsic_secret_gate() -> None:
    bundle, cells = _static_case()
    assert bundle.objects == ()
    exemplar = cells[0]
    secret = f"ghp_{'B' * 20}"

    with pytest.raises(RawResultCellAuthorityError, match="secret-shaped") as exc_info:
        _cell(
            observation_sha256=exemplar.observation_sha256,
            occurrence_sha256=exemplar.occurrence_sha256,
            header_name=exemplar.header_name,
            value={"nested": [secret]},
        )
    assert secret not in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    [
        "Basic Basketball",
        "Bearer of the scoring load",
        "Authorization is required for League Pass",
        "The secret weapon was transition defense",
        "Nikola Jokić — basic basketball excellence",
    ],
)
def test_secret_gate_preserves_benign_nba_text(value: str) -> None:
    assert _cell(value=value).value() == value


@pytest.mark.parametrize(
    "header_name",
    [
        "clientSecret",
        "privateKey",
        "secretKey",
        "githubToken",
        "authToken",
        "sessionKey",
        "proxyUrl",
        "vpnServer",
        "localPath",
        "workspacePath",
        "filePath",
        "Authorization",
        f"ghp_{'H' * 20}",
    ],
)
def test_cell_builder_rejects_secret_shaped_headers_without_echo(
    header_name: str,
) -> None:
    with pytest.raises(RawResultCellAuthorityError, match="secret-shaped") as exc_info:
        _cell(header_name=header_name)
    assert header_name not in str(exc_info.value)


def test_cell_and_receipt_hashes_require_exact_builtin_strings() -> None:
    class ForeignStr(str):
        pass

    cell = _cell()
    for field_name in (
        "cell_sha256",
        "observation_sha256",
        "occurrence_sha256",
        "canonical_json_sha256",
    ):
        with pytest.raises(RawResultCellAuthorityError, match="lowercase full SHA-256"):
            replace(cell, **{field_name: ForeignStr(getattr(cell, field_name))})

    bundle, cells = _stats_case()
    receipt = validate_raw_result_cell_authority(bundle, cells)
    for field_name in (
        "authority_sha256",
        "raw_authority_bundle_sha256",
        "public_table_proof_sha256",
    ):
        with pytest.raises(RawResultCellAuthorityError, match="lowercase full SHA-256"):
            replace(receipt, **{field_name: ForeignStr(getattr(receipt, field_name))})

    proof = receipt.public_table_proof
    for field_name in (
        "proof_sha256",
        "observation_inventory_sha256",
        "occurrence_inventory_sha256",
        "eligible_occurrence_inventory_sha256",
        "cell_inventory_sha256",
        "cell_rows_sha256",
    ):
        with pytest.raises(RawResultCellAuthorityError, match="lowercase full SHA-256"):
            replace(proof, **{field_name: ForeignStr(getattr(proof, field_name))})


def test_public_table_verifier_is_pure_structured_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()

    def poison(*_args: object, **_kwargs: object) -> None:
        raise ValueError("non-public authority dependency was invoked")

    monkeypatch.setattr(
        raw_result_cell_authority,
        "validate_raw_request_authority_bundle",
        poison,
    )
    source = inspect.getsource(validate_raw_result_cell_public_table)
    assert "validate_raw_request_authority_bundle" not in source
    assert "decode_parser_input_object" not in source
    assert "rederive_raw_authority_stats_rows" not in source
    assert "STAGING_MAP" not in source

    proof = validate_raw_result_cell_public_table(
        observations=bundle.observations,
        occurrences=bundle.occurrences,
        cells=cells,
    )
    assert proof.cells == cells
    assert isinstance(proof, RawResultCellPublicTableProofV2)
    with pytest.raises(RawResultCellAuthorityError, match="invalid raw request bundle"):
        validate_raw_result_cell_authority(bundle, cells)


def test_public_table_proof_cannot_claim_an_arbitrary_raw_bundle_root() -> None:
    bundle, cells = _stats_case()
    signature = inspect.signature(validate_raw_result_cell_public_table)
    assert "raw_authority_bundle_sha256" not in signature.parameters

    proof = validate_raw_result_cell_public_table(
        observations=bundle.observations,
        occurrences=bundle.occurrences,
        cells=cells,
    )
    assert not hasattr(proof, "raw_authority_bundle_sha256")
    with pytest.raises(TypeError):
        cast("Any", validate_raw_result_cell_public_table)(
            raw_authority_bundle_sha256="f" * 64,
            observations=bundle.observations,
            occurrences=bundle.occurrences,
            cells=cells,
        )

    receipt = validate_raw_result_cell_authority(bundle, cells)
    assert receipt.raw_authority_bundle_sha256 == bundle.bundle_sha256
    assert receipt.public_table_proof_sha256 == proof.proof_sha256


def test_composite_receipt_requires_explicit_bundle_join_revalidation() -> None:
    bundle, cells = _stats_case()
    receipt = validate_raw_result_cell_authority(bundle, cells)
    assert validate_raw_result_cell_authority_receipt(bundle, receipt) == receipt

    foreign_bundle_sha256 = "f" * 64
    forged_authority_sha256 = raw_result_cell_authority._canonical_sha256(
        {
            "schema_version": 2,
            "kind": RawResultCellAuthorityReceiptV2.kind,
            "raw_authority_bundle_sha256": foreign_bundle_sha256,
            "public_table_proof_sha256": receipt.public_table_proof_sha256,
        }
    )
    forged = RawResultCellAuthorityReceiptV2(
        authority_sha256=forged_authority_sha256,
        raw_authority_bundle_sha256=foreign_bundle_sha256,
        public_table_proof_sha256=receipt.public_table_proof_sha256,
        public_table_proof=receipt.public_table_proof,
    )
    with pytest.raises(RawResultCellAuthorityError, match="does not bind"):
        validate_raw_result_cell_authority_receipt(bundle, forged)


def test_public_table_roots_are_invariant_to_observation_and_occurrence_input_order() -> None:
    bundle, cells = _combined_case()
    canonical = validate_raw_result_cell_public_table(
        observations=bundle.observations,
        occurrences=bundle.occurrences,
        cells=cells,
    )
    reordered = validate_raw_result_cell_public_table(
        observations=tuple(reversed(bundle.observations)),
        occurrences=tuple(reversed(bundle.occurrences)),
        cells=cells,
    )

    assert reordered == canonical
    assert reordered.proof_sha256 == canonical.proof_sha256
    assert reordered.observation_inventory_sha256 == canonical.observation_inventory_sha256
    assert reordered.occurrence_inventory_sha256 == canonical.occurrence_inventory_sha256
    assert reordered.cell_rows_sha256 == canonical.cell_rows_sha256


def test_public_table_rejects_semantic_observation_order_collisions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _combined_case()
    monkeypatch.setattr(
        raw_result_cell_authority,
        "_observation_semantic_order_key",
        lambda _observation: ("collision",),
    )

    with pytest.raises(RawResultCellAuthorityError, match="semantic order coordinates"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=bundle.occurrences,
            cells=cells,
        )


def test_public_table_verifier_checks_cell_tuple_and_list_length_before_elements() -> None:
    bundle, cells = _stats_case()
    assert len(cells) != 1

    class PoisonCell:
        def __getattribute__(self, _name: str) -> object:
            raise AssertionError("wrong-length cell element was inspected")

    poison = PoisonCell()
    for wrong_length_rows in ((poison,), [poison]):
        with pytest.raises(RawResultCellAuthorityError, match="Cartesian denominator"):
            validate_raw_result_cell_public_table(
                observations=bundle.observations,
                occurrences=bundle.occurrences,
                cells=wrong_length_rows,
            )


def test_public_table_dict_preflight_rejects_hostile_keys_before_lookup() -> None:
    bundle, cells = _stats_case()

    class PoisonKey(str):
        armed = False

        def __hash__(self) -> int:
            if self.armed:
                raise AssertionError("foreign row key was hashed before exact key admission")
            return str.__hash__(self)

        def __eq__(self, other: object) -> bool:
            if self.armed:
                raise AssertionError("foreign row key was compared before exact key admission")
            return str.__eq__(self, other)

    row = cells[0].to_row()
    hostile_row = {
        PoisonKey(key) if key == "canonical_json" else key: value for key, value in row.items()
    }
    PoisonKey.armed = True
    with pytest.raises(RawResultCellAuthorityError, match="ordered contract columns"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=bundle.occurrences,
            cells=(hostile_row, *cells[1:]),
        )


def test_header_count_bound_precedes_ordered_header_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    occurrence = bundle.occurrences[0].model_copy(
        update={"header_count": raw_result_cell_authority._MAX_RESULT_HEADERS + 1}
    )

    def poison(_self: ResultOccurrenceV2) -> tuple[str, ...]:
        raise AssertionError("ordered headers were decoded before their count bound")

    monkeypatch.setattr(ResultOccurrenceV2, "ordered_headers", poison)
    with pytest.raises(RawResultCellAuthorityError, match="header bound"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=(occurrence, *bundle.occurrences[1:]),
            cells=(),
        )
    with pytest.raises(RawResultCellAuthorityError, match="header bound"):
        raw_result_cell_authority._occurrence_output_sha256(occurrence, ())


def test_header_byte_bound_precedes_ordered_header_decoding(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _stats_case()
    occurrence = bundle.occurrences[0].model_copy(update={"ordered_headers_json": '["ABCDE"]'})
    monkeypatch.setattr(raw_result_cell_authority, "MAX_PARSER_INPUT_BYTES", 4)

    def poison(_self: ResultOccurrenceV2) -> tuple[str, ...]:
        raise AssertionError("ordered headers were decoded before their byte bound")

    monkeypatch.setattr(ResultOccurrenceV2, "ordered_headers", poison)
    with pytest.raises(RawResultCellAuthorityError, match="header byte bound"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=(occurrence, *bundle.occurrences[1:]),
            cells=(),
        )
    with pytest.raises(RawResultCellAuthorityError, match="header byte bound"):
        raw_result_cell_authority._occurrence_output_sha256(occurrence, ())


def test_public_table_reconstructs_model_copy_bypasses_before_authorizing() -> None:
    bundle, cells = _stats_case()
    forged_observation = bundle.observations[0].model_copy(
        update={"observation_record_sha256": "0" * 64}
    )
    with pytest.raises(RawResultCellAuthorityError, match="observation.*DTO reconstruction"):
        validate_raw_result_cell_public_table(
            observations=(forged_observation,),
            occurrences=bundle.occurrences,
            cells=cells,
        )

    forged_occurrence = bundle.occurrences[0].model_copy(update={"output_sha256": "0" * 64})
    with pytest.raises(RawResultCellAuthorityError, match="occurrence.*DTO reconstruction"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=(forged_occurrence, *bundle.occurrences[1:]),
            cells=cells,
        )

    forged_cell = copy(cells[0])
    object.__setattr__(forged_cell, "canonical_json_sha256", "0" * 64)
    with pytest.raises(RawResultCellAuthorityError):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=bundle.occurrences,
            cells=(forged_cell, *cells[1:]),
        )


def test_composite_wrapper_reconstructs_bundle_root_objects_and_landings() -> None:
    bundle, cells = _stats_case()
    forged_root = bundle.model_copy(update={"bundle_sha256": "0" * 64})
    forged_object = bundle.objects[0].model_copy(update={"object_sha256": "0" * 64})
    forged_object_bundle = bundle.model_copy(
        update={"objects": (forged_object, *bundle.objects[1:])}
    )
    forged_landing = bundle.landings[0].model_copy(update={"landing_sha256": "0" * 64})
    forged_landing_bundle = bundle.model_copy(
        update={"landings": (forged_landing, *bundle.landings[1:])}
    )

    for forged_bundle in (forged_root, forged_object_bundle, forged_landing_bundle):
        with pytest.raises(RawResultCellAuthorityError, match="invalid raw request bundle"):
            validate_raw_result_cell_authority(forged_bundle, cells)


def test_structured_and_bundle_preflights_reject_hostile_nested_values_before_use() -> None:
    bundle, cells = _stats_case()

    class PoisonAttempt:
        def to_dict(self) -> dict[str, object]:
            raise AssertionError("foreign nested attempt was invoked")

    class PoisonStr(str):
        def __eq__(self, _other: object) -> bool:
            raise AssertionError("foreign string equality was invoked")

        def __hash__(self) -> int:
            raise AssertionError("foreign string hash was invoked")

        def encode(self, *_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("foreign string encoding was invoked")

    class PoisonTuple(tuple[object, ...]):
        def __len__(self) -> int:
            raise AssertionError("foreign bundle sequence length was inspected")

        def __iter__(self):  # type: ignore[no-untyped-def]
            raise AssertionError("foreign bundle sequence was iterated")

    forged_observation = bundle.observations[0].model_copy(update={"attempt": PoisonAttempt()})
    with pytest.raises(RawResultCellAuthorityError, match="request attempt.*foreign exact DTO"):
        validate_raw_result_cell_public_table(
            observations=(forged_observation,),
            occurrences=bundle.occurrences,
            cells=cells,
        )

    forged_occurrence = bundle.occurrences[0].model_copy(
        update={"landing_disposition": PoisonStr(bundle.occurrences[0].landing_disposition)}
    )
    with pytest.raises(RawResultCellAuthorityError, match="occurrence.*foreign nested value"):
        validate_raw_result_cell_public_table(
            observations=bundle.observations,
            occurrences=(forged_occurrence, *bundle.occurrences[1:]),
            cells=cells,
        )

    forged_object = bundle.objects[0].model_copy(
        update={"representation": PoisonStr(bundle.objects[0].representation)}
    )
    forged_object_bundle = bundle.model_copy(
        update={"objects": (forged_object, *bundle.objects[1:])}
    )
    with pytest.raises(RawResultCellAuthorityError, match="parser-input.*foreign nested value"):
        validate_raw_result_cell_authority(forged_object_bundle, cells)

    forged_landing = bundle.landings[0].model_copy(
        update={"staging_key": PoisonStr(bundle.landings[0].staging_key)}
    )
    forged_landing_bundle = bundle.model_copy(
        update={"landings": (forged_landing, *bundle.landings[1:])}
    )
    with pytest.raises(RawResultCellAuthorityError, match="route landing.*foreign nested value"):
        validate_raw_result_cell_authority(forged_landing_bundle, cells)

    forged_sequence_bundle = bundle.model_copy(update={"objects": PoisonTuple(bundle.objects)})
    with pytest.raises(RawResultCellAuthorityError, match="objects sequence is invalid"):
        validate_raw_result_cell_authority(forged_sequence_bundle, cells)


def test_observation_and_route_timestamps_require_exact_trusted_utc_before_callbacks() -> None:
    class PoisonTimezone(tzinfo):
        def utcoffset(self, _value: datetime | None) -> timedelta:
            raise AssertionError("hostile timestamp callback was invoked")

        def dst(self, _value: datetime | None) -> timedelta:
            return timedelta(0)

    hostile = datetime(2026, 8, 28, tzinfo=PoisonTimezone())
    bundle, cells = _stats_case()
    for field_name in ("started_at", "finished_at"):
        forged_observation = bundle.observations[0].model_copy(update={field_name: hostile})
        with pytest.raises(RawResultCellAuthorityError, match="timestamp.*trusted UTC"):
            validate_raw_result_cell_public_table(
                observations=(forged_observation,),
                occurrences=bundle.occurrences,
                cells=cells,
            )

    live_bundle = _live_occurrence_reseal_bundle(tamper_occurrence=False)
    assert live_bundle.landings[0].live_snapshot_at is not None
    forged_landing = live_bundle.landings[0].model_copy(update={"live_snapshot_at": hostile})
    forged_bundle = live_bundle.model_copy(
        update={"landings": (forged_landing, *live_bundle.landings[1:])}
    )
    with pytest.raises(RawResultCellAuthorityError, match="snapshot timestamp.*trusted UTC"):
        validate_raw_result_cell_authority(forged_bundle, ())


def test_cell_authority_rejects_missing_additive_duplicate_or_reordered_rows() -> None:
    bundle, cells = _stats_case()
    with pytest.raises(RawResultCellAuthorityError, match="Cartesian denominator"):
        validate_raw_result_cell_authority(bundle, cells[:-1])
    with pytest.raises(RawResultCellAuthorityError, match="Cartesian denominator"):
        validate_raw_result_cell_authority(bundle, (*cells, cells[0]))
    with pytest.raises(RawResultCellAuthorityError, match="duplicate"):
        validate_raw_result_cell_authority(bundle, (cells[0], cells[0], *cells[2:]))
    with pytest.raises(RawResultCellAuthorityError, match="canonical occurrence order"):
        validate_raw_result_cell_authority(bundle, tuple(reversed(cells)))


def test_cell_authority_rejects_coordinate_header_and_value_reseals() -> None:
    bundle, cells = _stats_case()
    original = cells[0]

    wrong_coordinate = _cell(
        observation_sha256=original.observation_sha256,
        occurrence_sha256=original.occurrence_sha256,
        cell_ordinal=original.cell_ordinal,
        row_ordinal=original.row_ordinal + 1,
        header_ordinal=original.header_ordinal,
        header_name=original.header_name,
        value=original.value(),
    )
    with pytest.raises(RawResultCellAuthorityError, match="Cartesian ordinal"):
        validate_raw_result_cell_authority(
            bundle,
            (wrong_coordinate, *cells[1:]),
        )

    wrong_header = _cell(
        observation_sha256=original.observation_sha256,
        occurrence_sha256=original.occurrence_sha256,
        cell_ordinal=original.cell_ordinal,
        row_ordinal=original.row_ordinal,
        header_ordinal=original.header_ordinal,
        header_name=f"{original.header_name}_FORGED",
        value=original.value(),
    )
    with pytest.raises(RawResultCellAuthorityError, match="header join"):
        validate_raw_result_cell_authority(
            bundle,
            (wrong_header, *cells[1:]),
        )

    wrong_value = _cell(
        observation_sha256=original.observation_sha256,
        occurrence_sha256=original.occurrence_sha256,
        cell_ordinal=original.cell_ordinal,
        row_ordinal=original.row_ordinal,
        header_ordinal=original.header_ordinal,
        header_name=original.header_name,
        value="forged",
    )
    with pytest.raises(RawResultCellAuthorityError, match="output digest"):
        validate_raw_result_cell_authority(
            bundle,
            (wrong_value, *cells[1:]),
        )


def test_cell_authority_rejects_cross_observation_and_foreign_occurrence_joins() -> None:
    bundle, cells = _stats_case()
    original = cells[0]
    foreign_observation = _cell(
        observation_sha256="f" * 64,
        occurrence_sha256=original.occurrence_sha256,
        cell_ordinal=original.cell_ordinal,
        row_ordinal=original.row_ordinal,
        header_ordinal=original.header_ordinal,
        header_name=original.header_name,
        value=original.value(),
    )
    with pytest.raises(RawResultCellAuthorityError, match="cross-observation"):
        validate_raw_result_cell_authority(
            bundle,
            (foreign_observation, *cells[1:]),
        )

    foreign_occurrence = _cell(
        observation_sha256=original.observation_sha256,
        occurrence_sha256="f" * 64,
        cell_ordinal=original.cell_ordinal,
        row_ordinal=original.row_ordinal,
        header_ordinal=original.header_ordinal,
        header_name=original.header_name,
        value=original.value(),
    )
    with pytest.raises(RawResultCellAuthorityError, match="missing or cross-observation"):
        validate_raw_result_cell_authority(
            bundle,
            (foreign_occurrence, *cells[1:]),
        )


def test_live_occurrences_are_excluded_and_live_cell_injection_fails() -> None:
    bundle = _live_occurrence_reseal_bundle(tamper_occurrence=False)
    receipt = validate_raw_result_cell_authority(bundle, ())
    assert receipt.public_table_proof.cell_count == 0

    occurrence = bundle.occurrences[0]
    cell = _cell(
        observation_sha256=occurrence.observation_sha256,
        occurrence_sha256=occurrence.occurrence_sha256,
    )
    with pytest.raises(RawResultCellAuthorityError, match="Cartesian denominator"):
        validate_raw_result_cell_authority(bundle, (cell,))


def test_wide_plus_lossless_selects_lossless_output_and_rejects_cell_assignment() -> None:
    bundle, cells = _wide_plus_lossless_case()
    wide_occurrences = tuple(
        item for item in bundle.occurrences if item.landing_disposition == "wide_plus_lossless"
    )
    lossless_occurrences = tuple(
        item for item in bundle.occurrences if item.landing_disposition == "lossless_only"
    )
    assert wide_occurrences
    assert lossless_occurrences

    proof = validate_raw_result_cell_authority(bundle, ()).public_table_proof
    assert proof.eligible_occurrence_count == 0
    assert proof.cell_count == 0

    wide = wide_occurrences[0]
    wide_cells = tuple(item for item in cells if item.occurrence_sha256 == wide.occurrence_sha256)
    wide_values = [item.value() for item in wide_cells]
    wide_rows = [
        wide_values[index : index + wide.header_count]
        for index in range(0, len(wide_values), wide.header_count)
    ]
    rectangular_output_sha256 = _sha256(
        _canonical({"headers": list(wide.ordered_headers()), "rows": wide_rows})
    )
    assert rectangular_output_sha256 != wide.output_sha256
    with pytest.raises(RawResultCellAuthorityError, match="not assigned.*rectangular-cell"):
        raw_result_cell_authority._occurrence_output_sha256(wide, wide_cells)
    with pytest.raises(RawResultCellAuthorityError, match="Cartesian denominator"):
        validate_raw_result_cell_authority(bundle, cells)


@pytest.mark.parametrize(
    ("bound_name", "measure"),
    [
        ("_MAX_RESULT_OCCURRENCES", lambda rows: len(rows)),
        ("_MAX_GLOBAL_RESULT_ROWS", lambda rows: sum(item.row_count for item in rows)),
        ("_MAX_GLOBAL_RESULT_HEADERS", lambda rows: sum(item.header_count for item in rows)),
        (
            "_MAX_GLOBAL_HEADER_BYTES",
            lambda rows: sum(len(item.ordered_headers_json.encode("utf-8")) for item in rows),
        ),
        ("_MAX_RESULT_CELLS", lambda rows: sum(item.cell_count for item in rows)),
    ],
)
def test_lossless_assignments_still_consume_every_global_dimension_bound(
    bound_name: str,
    measure: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, _cells = _wide_plus_lossless_case()
    selected_stats = tuple(
        item
        for item in bundle.occurrences
        if item.observation_sha256 == bundle.observations[0].attempt.observation_sha256
    )
    assert selected_stats
    assert all(item.landing_disposition != "wide_only" for item in selected_stats)
    exact_total = measure(selected_stats)
    assert exact_total > 0
    monkeypatch.setattr(raw_result_cell_authority, bound_name, exact_total - 1)
    with pytest.raises(RawResultCellAuthorityError, match="bound"):
        validate_raw_result_cell_authority(bundle, ())


def test_lossless_only_rectangular_looking_missing_result_remains_excluded() -> None:
    bundle, observation, occurrences, _landings = _stats_fallback_bundle("missing_result")
    missing = next(item for item in occurrences if item.presence == "missing")
    contract = pinned_runtime_contracts()[observation.attempt.endpoint_id]
    expected_headers = next(
        item.expected_columns
        for item in contract.result_sets
        if item.result_set_name == missing.result_name
    )
    assert missing.landing_disposition == "lossless_only"
    assert missing.cell_count == 0
    assert missing.output_sha256 == _sha256(
        _canonical({"headers": list(expected_headers), "rows": []})
    )

    proof = validate_raw_result_cell_authority(bundle, ()).public_table_proof
    assert proof.eligible_occurrence_count == 0
    assert proof.cell_count == 0


def _dimension_occurrence(
    *,
    headers: list[str],
    row_count: int,
    occurrence_ordinal: int = 0,
    observation_sha256: str = _SHA_A,
    output_sha256: str = _SHA_A,
) -> ResultOccurrenceV2:
    return ResultOccurrenceV2.build(
        observation_sha256=observation_sha256,
        occurrence_ordinal=occurrence_ordinal,
        result_name="Result",
        duplicate_name_ordinal=0,
        provider_result_ordinal=0,
        canonical_result_ordinal=0,
        json_path=None,
        container_kind="nba_api_result_set",
        presence="present" if row_count else "present_empty",
        ordered_headers=headers,
        row_count=row_count,
        cell_count=row_count * len(headers),
        node_count=0,
        container_count=1,
        missing_count=0,
        null_count=0,
        parent_state_sha256=_SHA_B,
        output_sha256=output_sha256,
        canonical_route_ids=["route_1"],
        committed_staging_receipts=[{"route_id": "route_1", "receipt_sha256": _SHA_B}],
        landing_disposition="wide_only",
    )


def test_zero_width_and_zero_row_packets_hash_without_sentinel_cells() -> None:
    zero_width = _dimension_occurrence(headers=[], row_count=3)
    assert raw_result_cell_authority._occurrence_output_sha256(zero_width, ()) == _sha256(
        _canonical({"headers": [], "rows": [[], [], []]})
    )

    zero_rows = _dimension_occurrence(headers=["A", "B"], row_count=0)
    assert raw_result_cell_authority._occurrence_output_sha256(zero_rows, ()) == _sha256(
        _canonical({"headers": ["A", "B"], "rows": []})
    )

    duplicate_headers = _dimension_occurrence(headers=["H", "H"], row_count=1)
    duplicate_cells = (
        _cell(
            observation_sha256=duplicate_headers.observation_sha256,
            occurrence_sha256=duplicate_headers.occurrence_sha256,
            header_name="H",
            value=1,
        ),
        _cell(
            observation_sha256=duplicate_headers.observation_sha256,
            occurrence_sha256=duplicate_headers.occurrence_sha256,
            cell_ordinal=1,
            header_ordinal=1,
            header_name="H",
            value=2,
        ),
    )
    assert raw_result_cell_authority._occurrence_output_sha256(
        duplicate_headers, duplicate_cells
    ) == _sha256(_canonical({"headers": ["H", "H"], "rows": [[1, 2]]}))


def test_zero_width_and_zero_row_packets_close_one_full_public_proof() -> None:
    bundle, _cells = _stats_case()
    base = bundle.observations[0]
    observation_sha256 = base.attempt.observation_sha256
    zero_width = _dimension_occurrence(
        headers=[],
        row_count=3,
        observation_sha256=observation_sha256,
        output_sha256=_sha256(_canonical({"headers": [], "rows": [[], [], []]})),
    )
    zero_rows = _dimension_occurrence(
        headers=["A", "B"],
        row_count=0,
        occurrence_ordinal=1,
        observation_sha256=observation_sha256,
        output_sha256=_sha256(_canonical({"headers": ["A", "B"], "rows": []})),
    )
    observation = RequestObservationV2.build(
        attempt=base.attempt,
        transport=base.transport,
        started_at=base.started_at,
        finished_at=base.finished_at,
        elapsed_ns=base.elapsed_ns,
        lifecycle=base.lifecycle,
        outcome=base.outcome,
        failure_class=base.failure_class,
        root_exception_class=base.root_exception_class,
        body_disposition=base.body_disposition,
        body_object_sha256=base.body_object_sha256,
        bodyless_evidence_sha256=base.bodyless_evidence_sha256,
        result_occurrence_sha256s=[
            zero_width.occurrence_sha256,
            zero_rows.occurrence_sha256,
        ],
        route_landing_sha256s=[
            item.landing_sha256
            for item in bundle.landings
            if item.observation_sha256 == observation_sha256
        ],
        capture_response_receipt_sha256=base.capture_response_receipt_sha256,
        logical_receipt_sha256=base.logical_receipt_sha256,
    )

    proof = validate_raw_result_cell_public_table(
        observations=(observation,),
        occurrences=(zero_width, zero_rows),
        cells=(),
    )
    assert proof.observation_count == 1
    assert proof.occurrence_count == 2
    assert proof.eligible_occurrence_count == 2
    assert proof.cell_count == 0


def test_empty_dimension_denominators_have_explicit_bounds() -> None:
    oversized_rows = _dimension_occurrence(
        headers=[],
        row_count=raw_result_cell_authority._MAX_RESULT_ROWS + 1,
    )
    with pytest.raises(RawResultCellAuthorityError, match="row bound"):
        raw_result_cell_authority._occurrence_output_sha256(oversized_rows, ())

    oversized_headers = _dimension_occurrence(
        headers=["H"] * (raw_result_cell_authority._MAX_RESULT_HEADERS + 1),
        row_count=0,
    )
    with pytest.raises(RawResultCellAuthorityError, match="header bound"):
        raw_result_cell_authority._occurrence_output_sha256(oversized_headers, ())

    oversized_product = _dimension_occurrence(
        headers=["H"] * raw_result_cell_authority._MAX_RESULT_HEADERS,
        row_count=raw_result_cell_authority._MAX_RESULT_ROWS,
    )
    with pytest.raises(RawResultCellAuthorityError, match="cell bound"):
        raw_result_cell_authority._occurrence_output_sha256(oversized_product, ())


def test_bundle_global_zero_cell_dimensions_have_exact_aggregate_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _combined_case()
    row_total = sum(item.row_count for item in bundle.occurrences)
    row_max = max(
        sum(
            item.row_count
            for item in bundle.occurrences
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        for observation in bundle.observations
    )
    assert row_total > row_max

    monkeypatch.setattr(raw_result_cell_authority, "_MAX_GLOBAL_RESULT_ROWS", row_total)
    assert validate_raw_result_cell_authority(bundle, cells).public_table_proof.cell_count == len(
        cells
    )
    monkeypatch.setattr(
        raw_result_cell_authority,
        "_MAX_GLOBAL_RESULT_ROWS",
        row_total - 1,
    )
    with pytest.raises(RawResultCellAuthorityError, match="bundle.*shape bound"):
        validate_raw_result_cell_authority(bundle, cells)


def test_bundle_global_canonical_cell_bytes_are_preflight_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _combined_case()
    byte_total = sum(len(item.canonical_json.encode("utf-8")) for item in cells)
    byte_max = max(
        sum(
            len(item.canonical_json.encode("utf-8"))
            for item in cells
            if item.observation_sha256 == observation.attempt.observation_sha256
        )
        for observation in bundle.observations
    )
    assert byte_total > byte_max

    monkeypatch.setattr(raw_result_cell_authority, "_MAX_GLOBAL_CELL_BYTES", byte_total)
    assert validate_raw_result_cell_authority(bundle, cells).public_table_proof.cell_count == len(
        cells
    )
    monkeypatch.setattr(
        raw_result_cell_authority,
        "_MAX_GLOBAL_CELL_BYTES",
        byte_total - 1,
    )
    with pytest.raises(RawResultCellAuthorityError, match="canonical byte bound"):
        validate_raw_result_cell_authority(bundle, cells)


def test_bundle_global_inventory_dimensions_have_exact_aggregate_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _combined_case()
    exact_limits = {
        "_MAX_RESULT_OCCURRENCES": len(bundle.occurrences),
        "_MAX_GLOBAL_RESULT_HEADERS": sum(item.header_count for item in bundle.occurrences),
        "_MAX_GLOBAL_HEADER_BYTES": sum(
            len(item.ordered_headers_json.encode("utf-8")) for item in bundle.occurrences
        ),
        "_MAX_RESULT_CELLS": len(cells),
    }
    max_by_observation = {
        "_MAX_RESULT_OCCURRENCES": max(
            sum(
                item.observation_sha256 == observation.attempt.observation_sha256
                for item in bundle.occurrences
            )
            for observation in bundle.observations
        ),
        "_MAX_GLOBAL_RESULT_HEADERS": max(
            sum(
                item.header_count
                for item in bundle.occurrences
                if item.observation_sha256 == observation.attempt.observation_sha256
            )
            for observation in bundle.observations
        ),
        "_MAX_GLOBAL_HEADER_BYTES": max(
            sum(
                len(item.ordered_headers_json.encode("utf-8"))
                for item in bundle.occurrences
                if item.observation_sha256 == observation.attempt.observation_sha256
            )
            for observation in bundle.observations
        ),
        "_MAX_RESULT_CELLS": max(
            sum(
                item.cell_count
                for item in bundle.occurrences
                if item.observation_sha256 == observation.attempt.observation_sha256
            )
            for observation in bundle.observations
        ),
    }
    assert all(exact_limits[name] > max_by_observation[name] for name in exact_limits)

    for name, value in exact_limits.items():
        monkeypatch.setattr(raw_result_cell_authority, name, value)
    assert validate_raw_result_cell_authority(bundle, cells).public_table_proof.cell_count == len(
        cells
    )

    for failing_name, exact_value in exact_limits.items():
        for name, value in exact_limits.items():
            monkeypatch.setattr(raw_result_cell_authority, name, value)
        monkeypatch.setattr(raw_result_cell_authority, failing_name, exact_value - 1)
        with pytest.raises(RawResultCellAuthorityError, match="bound"):
            validate_raw_result_cell_authority(bundle, cells)


def test_receipt_revalidates_ordered_inventory_and_row_roots() -> None:
    bundle, cells = _stats_case()
    receipt = validate_raw_result_cell_authority(bundle, cells)
    proof = receipt.public_table_proof

    with pytest.raises(RawResultCellAuthorityError, match="cell roots"):
        replace(proof, cell_inventory_sha256="0" * 64)
    with pytest.raises(RawResultCellAuthorityError, match="cell roots"):
        replace(proof, cell_rows_sha256="0" * 64)
    with pytest.raises(RawResultCellAuthorityError, match="count"):
        replace(proof, cell_count=proof.cell_count + 1)
    with pytest.raises(RawResultCellAuthorityError, match="proof binding"):
        replace(receipt, public_table_proof_sha256="0" * 64)
    assert isinstance(receipt, RawResultCellAuthorityReceiptV2)


def test_receipt_external_bundle_root_is_checked_before_proof_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    receipt = validate_raw_result_cell_authority(bundle, cells)
    forged_bundle = bundle.model_copy(update={"bundle_sha256": "f" * 64})

    def poison_proof(_value: object) -> RawResultCellPublicTableProofV2:
        raise AssertionError("proof was inspected before the external bundle root")

    monkeypatch.setattr(
        raw_result_cell_authority,
        "_preflight_public_table_proof_members",
        poison_proof,
    )
    with pytest.raises(RawResultCellAuthorityError, match="does not bind.*external raw bundle"):
        validate_raw_result_cell_authority_receipt(forged_bundle, receipt)


def test_receipt_preflights_cell_container_count_and_bytes_before_reconstruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    receipt = validate_raw_result_cell_authority(bundle, cells)

    def poison_rebuild(
        _cls: type[RawNbaApiResultCellV2],
        _row: object,
    ) -> RawNbaApiResultCellV2:
        raise AssertionError("cell reconstruction preceded receipt member admission")

    monkeypatch.setattr(RawNbaApiResultCellV2, "from_row", classmethod(poison_rebuild))

    wrong_count_proof = copy(receipt.public_table_proof)
    object.__setattr__(wrong_count_proof, "cells", cells[:-1])
    wrong_count_receipt = copy(receipt)
    object.__setattr__(wrong_count_receipt, "public_table_proof", wrong_count_proof)
    with pytest.raises(RawResultCellAuthorityError, match="cell container"):
        validate_raw_result_cell_authority_receipt(bundle, wrong_count_receipt)

    canonical_bytes = sum(len(item.canonical_json.encode("utf-8")) for item in cells)
    monkeypatch.setattr(raw_result_cell_authority, "_MAX_GLOBAL_CELL_BYTES", canonical_bytes - 1)
    with pytest.raises(RawResultCellAuthorityError, match="cumulative byte bound"):
        validate_raw_result_cell_authority_receipt(bundle, receipt)


def test_public_table_proof_constructor_preflights_row_and_cumulative_byte_bounds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle, cells = _stats_case()
    proof = validate_raw_result_cell_authority(bundle, cells).public_table_proof

    class PoisonCell:
        def __getattribute__(self, _name: str) -> object:
            raise AssertionError("over-bound proof cell was inspected")

    with pytest.raises(RawResultCellAuthorityError, match="total row bound"):
        replace(
            proof,
            cell_count=raw_result_cell_authority._MAX_RESULT_CELLS + 1,
            cells=cast("Any", (PoisonCell(),)),
        )

    canonical_bytes = sum(len(item.canonical_json.encode("utf-8")) for item in cells)
    assert canonical_bytes > 0
    monkeypatch.setattr(
        raw_result_cell_authority,
        "_MAX_GLOBAL_CELL_BYTES",
        canonical_bytes - 1,
    )

    def poison_rebuild(
        _cls: type[RawNbaApiResultCellV2],
        _row: object,
    ) -> RawNbaApiResultCellV2:
        raise AssertionError("proof rebuilt a DTO before cumulative byte admission")

    monkeypatch.setattr(
        RawNbaApiResultCellV2,
        "from_row",
        classmethod(poison_rebuild),
    )
    with pytest.raises(RawResultCellAuthorityError, match="cumulative canonical byte"):
        replace(proof)


@pytest.mark.parametrize(
    "updates, message",
    [
        ({"observation_count": raw_result_cell_authority._MAX_RESULT_OCCURRENCES + 1}, "bound"),
        ({"occurrence_count": raw_result_cell_authority._MAX_RESULT_OCCURRENCES + 1}, "bound"),
        (
            {"eligible_occurrence_count": raw_result_cell_authority._MAX_RESULT_OCCURRENCES + 1},
            "bound",
        ),
        ({"observation_count": 0}, "inconsistent"),
        ({"occurrence_count": 0}, "inconsistent"),
        ({"eligible_occurrence_count": 0}, "inconsistent"),
    ],
)
def test_public_table_proof_rejects_resealed_impossible_denominators(
    updates: dict[str, int],
    message: str,
) -> None:
    bundle, cells = _stats_case()
    proof = validate_raw_result_cell_authority(bundle, cells).public_table_proof
    payload = {**proof.identity_payload(), **updates}
    with pytest.raises(RawResultCellAuthorityError, match=message):
        replace(
            proof,
            proof_sha256=raw_result_cell_authority._canonical_sha256(payload),
            **updates,
        )

    impossible_eligible = proof.occurrence_count + 1
    payload = {
        **proof.identity_payload(),
        "eligible_occurrence_count": impossible_eligible,
    }
    with pytest.raises(RawResultCellAuthorityError, match="inconsistent"):
        replace(
            proof,
            proof_sha256=raw_result_cell_authority._canonical_sha256(payload),
            eligible_occurrence_count=impossible_eligible,
        )


def test_schema_rejects_column_order_and_ordinal_bounds() -> None:
    row = _cell().to_row()
    frame = pl.DataFrame([row])
    reordered = frame.select(list(reversed(frame.columns)))
    with pytest.raises(SchemaError):
        RawNbaApiResultCellSchema.validate(reordered)

    negative = frame.with_columns(pl.lit(-1).alias("row_ordinal"))
    with pytest.raises(SchemaError):
        RawNbaApiResultCellSchema.validate(negative)


@pytest.mark.parametrize(
    "header_name",
    [
        "clientSecret",
        "privateKey",
        "secretKey",
        "githubToken",
        "authToken",
        "sessionKey",
        "proxyUrl",
        "vpnServer",
        "localPath",
        "workspacePath",
        "filePath",
        "Authorization",
        f"ghp_{'S' * 20}",
        "Bearer abcdefghijklmnop1234",
        "Basic abcdefghij12",
        "eyJabcdefgh.abcdefgh.abcdefgh",
    ],
)
def test_schema_rejects_secret_shaped_headers_without_echo(header_name: str) -> None:
    frame = pl.DataFrame([_cell().to_row()]).with_columns(pl.lit(header_name).alias("header_name"))
    with pytest.raises(SchemaError) as exc_info:
        RawNbaApiResultCellSchema.validate(frame)
    assert header_name not in str(exc_info.value)


@pytest.mark.parametrize(
    "value, secret_fragment",
    [
        (f"ghp_{'V' * 20}", f"ghp_{'V' * 20}"),
        ({"nested": [f"ghp_{'N' * 20}"]}, f"ghp_{'N' * 20}"),
        ({"clientSecret": "opaque"}, "clientSecret"),
        ({"privateKey": "opaque"}, "privateKey"),
        ({"githubToken": "opaque"}, "githubToken"),
        ({"authToken": "opaque"}, "authToken"),
        ({"session": "opaque"}, "session"),
        ({"proxyUrl": "opaque"}, "proxyUrl"),
        ({"nested": ["/Users/private-name/result.json"]}, "private-name"),
        ({"nested": ["/Users/private-name"]}, "private-name"),
        ({"nested": ["/home/private-name"]}, "private-name"),
        ({"nested": ["/private/var"]}, "private/var"),
        ({"nested": ["prefix /Users/private-name suffix"]}, "private-name"),
        ({"nested": ["prefix /home/private-name suffix"]}, "private-name"),
        ({"nested": ["prefix /private/var suffix"]}, "private/var"),
        ({"nested": ["prefix /private/var: suffix"]}, "private/var"),
        ({"nested": ["prefix /private/var, suffix"]}, "private/var"),
        ({"nested": ["prefix /private/var. suffix"]}, "private/var"),
        ({"nested": ["prefix /private/var) suffix"]}, "private/var"),
        (
            ["public", "prefix Authorization: Bearer abcdefghijklmnop1234 suffix"],
            "abcdefghijklmnop1234",
        ),
        (["public", "prefix Bearer abcdefghijklmnopqrst"], "abcdefghijklmnopqrst"),
        (["public", "prefix Basic abcdefghij12"], "abcdefghij12"),
        (
            ["public", "prefix Bearer abcdefghijklmnop1234 suffix"],
            "abcdefghijklmnop1234",
        ),
    ],
)
def test_schema_rejects_nested_secret_shaped_canonical_values_without_echo(
    value: object,
    secret_fragment: str,
) -> None:
    row = _cell().to_row()
    canonical_json = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    canonical_json_sha256 = _sha256(canonical_json.encode("utf-8"))
    row.update(
        {
            "presence_kind": raw_result_cell_authority._presence_kind(value),
            "value_kind": raw_result_cell_authority._value_kind(value),
            "canonical_json": canonical_json,
            "canonical_json_sha256": canonical_json_sha256,
        }
    )
    row["cell_sha256"] = raw_result_cell_authority._canonical_sha256(
        raw_result_cell_authority._cell_identity_payload(
            observation_sha256=cast("str", row["observation_sha256"]),
            occurrence_sha256=cast("str", row["occurrence_sha256"]),
            cell_ordinal=cast("int", row["cell_ordinal"]),
            row_ordinal=cast("int", row["row_ordinal"]),
            header_ordinal=cast("int", row["header_ordinal"]),
            header_name=cast("str", row["header_name"]),
            presence_kind=cast("Any", row["presence_kind"]),
            value_kind=cast("Any", row["value_kind"]),
            canonical_json=canonical_json,
            canonical_json_sha256=canonical_json_sha256,
        )
    )
    with pytest.raises(SchemaError) as exc_info:
        RawNbaApiResultCellSchema.validate(pl.DataFrame([row]))
    assert secret_fragment not in str(exc_info.value)


@pytest.mark.parametrize(
    "canonical_json",
    [
        " 1",
        "1.00",
        "1e0",
        "NaN",
        "Infinity",
        "-0.0",
        "9223372036854775808",
        '{"z":1,"a":2}',
    ],
)
def test_schema_rejects_noncanonical_or_nonfinite_canonical_json(
    canonical_json: str,
) -> None:
    row = _cell().to_row()
    row["canonical_json"] = canonical_json
    row["canonical_json_sha256"] = _sha256(canonical_json.encode("utf-8"))
    with pytest.raises(SchemaError):
        RawNbaApiResultCellSchema.validate(pl.DataFrame([row]))


def test_schema_enforces_exact_utf8_byte_boundary_for_multibyte_json(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(result_cell_schema, "MAX_PARSER_INPUT_BYTES", 4)
    row = _cell(value="é").to_row()
    assert row["canonical_json"] == '"é"'
    at_boundary = pl.DataFrame([row])
    assert RawNbaApiResultCellSchema.validate(at_boundary).shape == at_boundary.shape

    over_boundary = at_boundary.with_columns(pl.lit('"éa"').alias("canonical_json"))
    with pytest.raises(SchemaError):
        RawNbaApiResultCellSchema.validate(over_boundary)
