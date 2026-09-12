"""Test-replaceable crash injection after durable successor planning steps.

Production callers invoke :func:`after_durable_step` only after the named write
is already durable.  The default implementation is a no-op; tests replace it to
kill the process after that exact step.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = [
    "DurablePlanningStep",
    "after_durable_step",
]


class DurablePlanningStep(StrEnum):
    """Named crash boundaries in the planning and current-pointer sequence."""

    PROVIDER_CAPTURE = "provider_capture"
    PLANNING_DUCKDB_COMMIT = "planning_duckdb_commit"
    MEMBER_RECEIPT = "member_receipt"
    CALL_COMPLETION = "call_completion"
    PRIVATE_SEAL = "private_seal"
    WAVE_MANIFEST = "wave_manifest"
    DISPATCH_SEAL = "dispatch_seal"
    POINTER_ADVANCE = "pointer_advance"


def after_durable_step(step: DurablePlanningStep, **identity: object) -> None:
    """No-op hook invoked after a durable planning or pointer write."""

    if type(step) is not DurablePlanningStep:
        raise TypeError("durable planning step must be DurablePlanningStep")
    del identity
