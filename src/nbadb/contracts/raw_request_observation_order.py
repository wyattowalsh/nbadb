"""Canonical semantic ordering for Raw Request Authority V2 observations.

This leaf deliberately depends only on the frozen Raw-v2 observation DTO.  It
is shared by public authorities that need one order which is independent of
input tuple order, mutable registries, persistence order, and projections.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

if TYPE_CHECKING:
    from collections.abc import Sequence

from nbadb.contracts.raw_request_authority import (
    MAX_AUTHORITY_ROWS,
    RequestObservationV2,
    validate_request_observation,
)

__all__ = [
    "RawRequestObservationOrderError",
    "canonical_raw_request_observations",
    "raw_request_observation_order_key",
]

_MAX_ORDINAL: Final = 2**63 - 1


class RawRequestObservationOrderError(ValueError):
    """Raised when an observation sequence has no exact canonical order."""


def _fail(message: str) -> RawRequestObservationOrderError:
    return RawRequestObservationOrderError(message)


def _exact_nonnegative(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_ORDINAL:
        raise _fail(f"{label} must be one bounded exact integer")
    return value


def raw_request_observation_order_key(
    observation: RequestObservationV2,
) -> tuple[object, ...]:
    """Return the nine-coordinate semantic order key for one exact Raw-v2 row."""

    if type(observation) is not RequestObservationV2:
        raise _fail("raw request observation has a foreign structured type")
    try:
        validated = validate_request_observation(observation)
    except (RecursionError, TypeError, ValueError):
        raise _fail("raw request observation failed exact DTO validation") from None
    if type(validated) is not RequestObservationV2:
        raise _fail("raw request observation validation returned a foreign type")
    attempt = validated.attempt
    provider_call_ordinal = _exact_nonnegative(
        attempt.provider_call_ordinal,
        label="provider-call ordinal",
    )
    retry_ordinal = _exact_nonnegative(attempt.retry_ordinal, label="retry ordinal")
    request_ordinal = _exact_nonnegative(attempt.request_ordinal, label="request ordinal")
    if attempt.page_ordinal is None:
        page_discriminator = 0
        page_ordinal = 0
    else:
        page_discriminator = 1
        page_ordinal = _exact_nonnegative(attempt.page_ordinal, label="page ordinal")
    return (
        attempt.logical_invocation_sha256,
        attempt.semantic_request_sha256,
        provider_call_ordinal,
        page_discriminator,
        page_ordinal,
        attempt.provider_call_role,
        attempt.provider_call_sha256,
        retry_ordinal,
        request_ordinal,
    )


def canonical_raw_request_observations(
    observations: Sequence[RequestObservationV2],
    *,
    selection: Literal["selected_terminal", "downstream_incomplete"] | None = None,
    maximum: int = MAX_AUTHORITY_ROWS,
) -> tuple[RequestObservationV2, ...]:
    """Validate, filter, and canonically order one Raw-v2 observation sequence.

    ``downstream_incomplete`` selects the exact outcome together with its
    required ``incomplete`` lifecycle; it is never treated as a lifecycle.
    """

    if type(maximum) is not int or maximum < 0 or maximum > MAX_AUTHORITY_ROWS:
        raise _fail("raw request observation maximum is invalid")
    if selection is not None and type(selection) is not str:
        raise _fail("raw request observation selection is invalid")
    if selection not in {None, "selected_terminal", "downstream_incomplete"}:
        raise _fail("raw request observation selection is invalid")
    if type(observations) not in {tuple, list}:
        raise _fail("raw request observations must be one exact tuple or list")
    if len(observations) > maximum:
        raise _fail("raw request observation inventory exceeds its explicit bound")

    selected: list[RequestObservationV2] = []
    identities: set[str] = set()
    coordinate_owner: dict[tuple[object, ...], str] = {}
    for observation in observations:
        if type(observation) is not RequestObservationV2:
            raise _fail("raw request observation inventory contains a foreign row type")
        try:
            rebuilt = RequestObservationV2.from_canonical_bytes(observation.to_canonical_bytes())
        except (RecursionError, TypeError, ValueError):
            raise _fail("raw request observation failed exact DTO reconstruction") from None
        if rebuilt != observation or type(rebuilt) is not RequestObservationV2:
            raise _fail("raw request observation differs from exact DTO reconstruction")
        observation_sha256 = rebuilt.attempt.observation_sha256
        if observation_sha256 in identities:
            raise _fail("raw request observation identities must be unique")
        identities.add(observation_sha256)

        semantic_key = raw_request_observation_order_key(rebuilt)
        prior_owner = coordinate_owner.get(semantic_key)
        if prior_owner is not None and prior_owner != observation_sha256:
            raise _fail("raw request observations collide on semantic order coordinates")
        coordinate_owner[semantic_key] = observation_sha256

        if (
            selection is None
            or selection == "selected_terminal"
            and rebuilt.lifecycle == "selected_terminal"
            or selection == "downstream_incomplete"
            and rebuilt.lifecycle == "incomplete"
            and rebuilt.outcome == "downstream_incomplete"
        ):
            selected.append(rebuilt)

    return tuple(
        sorted(
            selected,
            key=lambda item: (
                *raw_request_observation_order_key(item),
                item.attempt.observation_sha256,
            ),
        )
    )
