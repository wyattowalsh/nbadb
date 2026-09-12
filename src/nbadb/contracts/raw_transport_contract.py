"""Strict transport semantics for future raw provider observations.

This module deliberately defines only the transport discriminator and HTTP
status relationship.  Request/attempt identity, body presence, result
occurrences, and durable raw-table adoption belong to later contracts.  In
particular, a static provider snapshot is not an HTTP response and therefore
has no status fields to populate.
"""

from __future__ import annotations

from typing import Annotated, Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

__all__ = [
    "RAW_TRANSPORT_ADAPTER",
    "HTTPStatus",
    "LiveHttpTransportV1",
    "RawTransportV1",
    "SourceFamily",
    "StaticSnapshotTransportV1",
    "StatsHttpTransportV1",
    "canonical_transport_payload",
    "source_family_for_transport",
    "validate_raw_transport",
]

HTTPStatus = Annotated[int, Field(strict=True, ge=100, le=599)]
SourceFamily = Literal["stats", "live", "static"]


class _StrictFrozenTransport(BaseModel):
    """Shared fail-closed Pydantic configuration for transport variants."""

    model_config = ConfigDict(
        extra="forbid",
        strict=True,
        frozen=True,
        validate_default=True,
        revalidate_instances="always",
    )


class _HttpTransport(_StrictFrozenTransport):
    """Status semantics common to an NBA stats or live HTTP attempt."""

    status_code: HTTPStatus | None = None
    effective_status_code: HTTPStatus | None = None

    @model_validator(mode="after")
    def _require_observed_status_for_effective_status(self) -> Self:
        if self.effective_status_code is not None and self.status_code is None:
            raise ValueError("effective_status_code requires status_code")
        return self


class StatsHttpTransportV1(_HttpTransport):
    """Transport semantics for an NBA stats endpoint HTTP attempt."""

    transport_kind: Literal["stats_http"]


class LiveHttpTransportV1(_HttpTransport):
    """Transport semantics for an NBA live-data endpoint HTTP attempt."""

    transport_kind: Literal["live_http"]


class StaticSnapshotTransportV1(_StrictFrozenTransport):
    """Transport semantics for a deterministic non-HTTP static snapshot."""

    transport_kind: Literal["static_snapshot"]


type RawTransportV1 = Annotated[
    StatsHttpTransportV1 | LiveHttpTransportV1 | StaticSnapshotTransportV1,
    Field(discriminator="transport_kind"),
]

RAW_TRANSPORT_ADAPTER = TypeAdapter(RawTransportV1)


def validate_raw_transport(value: object) -> RawTransportV1:
    """Strictly revalidate one untrusted transport value without coercion."""

    return RAW_TRANSPORT_ADAPTER.validate_python(value, strict=True)


def source_family_for_transport(value: object) -> SourceFamily:
    """Return the exact provider family implied by the validated discriminator."""

    transport = validate_raw_transport(value)
    if transport.transport_kind == "stats_http":
        return "stats"
    if transport.transport_kind == "live_http":
        return "live"
    return "static"


def canonical_transport_payload(value: object) -> dict[str, object]:
    """Return an exact-key JSON-compatible payload after strict revalidation."""

    validated = validate_raw_transport(value)
    decoded_python = validated.model_dump(mode="python", round_trip=True)
    revalidated = validate_raw_transport(decoded_python)
    payload = revalidated.model_dump(mode="json", round_trip=True)
    validate_raw_transport(payload)
    return cast("dict[str, object]", payload)
