"""Fixed staging contract for successful drifted ``nba_api`` result cells."""

from __future__ import annotations

import pandera.polars as pa

from nbadb.schemas.base import BaseSchema


class StagingNbaApiLosslessResultCellsSchema(BaseSchema):
    """Tagged, ordinal-preserving relational projection of a drifted response.

    Private bronze remains the byte-exact replay authority. This schema makes
    every observed result set, missing expected set, header, row, and JSON cell
    queryable without guessing a new wide-table shape.
    """

    response_receipt_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Exact private-bronze response receipt when capture is enabled"},
    )
    provider_authority_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Pinned provider authority for an unknown response"},
    )
    endpoint_contract_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Exact endpoint contract for an unknown response"},
    )
    response_mode_authority_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Unknown-dynamic response-mode authority"},
    )
    parser_input_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Exact private parser-input body digest"},
    )
    canonical_payload_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Canonical decoded payload digest"},
    )
    parameters_sha256: str | None = pa.Field(
        nullable=True,
        str_matches=r"^[0-9a-f]{64}$",
        metadata={"description": "Exact provider request-parameter digest"},
    )
    endpoint_id: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Pinned provider runtime endpoint identity"},
    )
    endpoint_slug: str = pa.Field(
        metadata={"description": "Pinned nba_api endpoint slug that produced the response"},
    )
    response_state: str | None = pa.Field(
        nullable=True,
        isin=[
            "missing_result_envelope",
            "unknown_result_envelope",
            "generic_nested_json",
            "legacy_present_empty",
            "legacy_present_nonempty",
        ],
        metadata={"description": "Typed unknown-dynamic response state"},
    )
    legacy_envelope_name: str | None = pa.Field(
        nullable=True,
        isin=["resultSet", "resultSets"],
        metadata={"description": "Observed legacy envelope without inferred result identity"},
    )
    record_kind: str = pa.Field(
        isin=[
            "response",
            "result_set",
            "missing_expected",
            "header",
            "row",
            "cell",
            "json_node",
        ],
        metadata={"description": "Tagged fallback record type"},
    )
    result_set_name: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Provider or expected result-set name"},
    )
    result_set_occurrence: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Zero-based occurrence among duplicate result-set names"},
    )
    provider_index: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Zero-based provider result-set ordinal"},
    )
    canonical_index: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Pinned canonical result-set ordinal when matched"},
    )
    header_name: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Provider header name for header and cell records"},
    )
    header_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Zero-based header or cell column ordinal"},
    )
    row_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Zero-based row ordinal within the provider result set"},
    )
    node_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Preorder ordinal of a canonical decoded JSON node"},
    )
    parent_node_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Parent node ordinal for a decoded JSON node"},
    )
    json_path: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Exact canonical JSON path"},
    )
    parent_json_path: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Exact canonical parent JSON path"},
    )
    depth: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "JSON-node depth from the response root"},
    )
    object_key: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Exact object key for a child node"},
    )
    object_key_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Canonical object-key occurrence ordinal"},
    )
    array_ordinal: int | None = pa.Field(
        nullable=True,
        ge=0,
        metadata={"description": "Exact array element ordinal"},
    )
    presence_kind: str | None = pa.Field(
        nullable=True,
        isin=["present", "null", "empty_object", "empty_array"],
        metadata={"description": "Presence state without collapsing empty and null"},
    )
    value_kind: str | None = pa.Field(
        nullable=True,
        isin=["null", "boolean", "integer", "number", "string", "array", "object"],
        metadata={"description": "Canonical JSON scalar or container type for a cell"},
    )
    canonical_json: str | None = pa.Field(
        nullable=True,
        metadata={"description": "Canonical JSON serialization of the exact decoded cell"},
    )
    anomaly_codes_json: str = pa.Field(
        metadata={"description": "Canonical sorted JSON array of response anomaly codes"},
    )


__all__ = ["StagingNbaApiLosslessResultCellsSchema"]
