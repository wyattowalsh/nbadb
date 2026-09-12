"""Constant-memory ordered SHA-256 prefix folds.

The fold commits an append-only ordered stream of lowercase SHA-256 leaves.
Its finalized root is also the exact state required to extend the stream, so a
successor can derive a cumulative root from a trusted prior count/root without
materializing the prior leaves.  Roots from other domains, counts, positions,
or leaf orders are not interchangeable.

This module deliberately uses no JSON encoding, member array, chunk tree, or
aggregate call-site ceiling.  Callers retain responsibility for enforcing any
narrower native denominator bound.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Never, cast

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator

__all__ = [
    "OrderedSha256PrefixFoldV1",
    "compute_ordered_sha256_prefix_fold",
    "empty_ordered_sha256_prefix_fold",
    "extend_ordered_sha256_prefix_fold",
]

_CONTRACT_PREFIX: Final = b"nbadb-sha256-ordered-prefix-fold-v1\0"
_EMPTY_TAG: Final = b"\x00"
_STEP_TAG: Final = b"\x01"
_MAX_COUNT: Final = (1 << 63) - 1
_DOMAIN_RE: Final = re.compile(r"[a-z0-9][a-z0-9._:-]{0,199}\Z", flags=re.ASCII)
_SHA256_RE: Final = re.compile(r"[0-9a-f]{64}\Z", flags=re.ASCII)


def _fail(message: str) -> Never:
    raise ValueError(message)


def _domain_bytes(value: object) -> bytes:
    if type(value) is not str or _DOMAIN_RE.fullmatch(value) is None:
        _fail("ordered SHA-256 prefix-fold domain must be exact safe lowercase ASCII")
    try:
        encoded = value.encode("ascii", errors="strict")
    except UnicodeEncodeError:
        _fail("ordered SHA-256 prefix-fold domain must be exact safe lowercase ASCII")
    if not encoded or len(encoded) > 200:
        _fail("ordered SHA-256 prefix-fold domain exceeds its byte bound")
    return encoded


def _count(value: object, *, label: str) -> int:
    if type(value) is not int or value < 0 or value > _MAX_COUNT:
        _fail(f"{label} must be an exact nonnegative signed-63-bit integer")
    return value


def _sha256_bytes(value: object, *, label: str) -> bytes:
    if type(value) is not str or _SHA256_RE.fullmatch(value) is None:
        _fail(f"{label} must be an exact lowercase SHA-256")
    return bytes.fromhex(value)


def _item_iterator(value: object) -> Iterator[object]:
    if type(value) in {str, bytes, bytearray, memoryview}:
        _fail("ordered SHA-256 prefix-fold leaves must be one iterable of digests")
    try:
        return iter(cast("Iterable[object]", value))
    except TypeError:
        _fail("ordered SHA-256 prefix-fold leaves must be one iterable of digests")


def _domain_frame(domain: bytes) -> bytes:
    return len(domain).to_bytes(8, byteorder="big", signed=False) + domain


def _empty_root(domain: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(_CONTRACT_PREFIX)
    digest.update(_EMPTY_TAG)
    digest.update(_domain_frame(domain))
    digest.update((0).to_bytes(8, byteorder="big", signed=False))
    return digest.digest()


def _append_root(*, domain_frame: bytes, ordinal: int, prior_root: bytes, leaf: bytes) -> bytes:
    digest = hashlib.sha256()
    digest.update(_CONTRACT_PREFIX)
    digest.update(_STEP_TAG)
    digest.update(domain_frame)
    digest.update(ordinal.to_bytes(8, byteorder="big", signed=False))
    digest.update(prior_root)
    digest.update(leaf)
    return digest.digest()


@dataclass(frozen=True, slots=True)
class OrderedSha256PrefixFoldV1:
    """One immutable exact count/root state for a domain-separated fold."""

    domain: str
    count: int
    root_sha256: str

    def __post_init__(self) -> None:
        if type(self) is not OrderedSha256PrefixFoldV1:
            _fail("ordered SHA-256 prefix-fold DTO subclasses are forbidden")
        domain = _domain_bytes(self.domain)
        count = _count(self.count, label="ordered SHA-256 prefix-fold count")
        root = _sha256_bytes(self.root_sha256, label="ordered SHA-256 prefix-fold root")
        if count == 0 and root != _empty_root(domain):
            _fail("ordered SHA-256 prefix-fold empty root differs from its domain")

    def __init_subclass__(cls, **_kwargs: object) -> Never:
        _fail("ordered SHA-256 prefix-fold DTO subclasses are forbidden")


def empty_ordered_sha256_prefix_fold(*, domain: object) -> OrderedSha256PrefixFoldV1:
    """Return the exact empty state for ``domain``."""

    encoded_domain = _domain_bytes(domain)
    return OrderedSha256PrefixFoldV1(
        domain=cast("str", domain),
        count=0,
        root_sha256=_empty_root(encoded_domain).hex(),
    )


def extend_ordered_sha256_prefix_fold(
    *,
    domain: object,
    prior_count: object,
    prior_root_sha256: object,
    appended_count: object,
    item_sha256s: object,
) -> OrderedSha256PrefixFoldV1:
    """Extend one trusted prior state with exactly ``appended_count`` leaves.

    The iterable is acquired once and consumed once.  Underflow fails at the
    first absent leaf; overflow consumes only the first excess leaf before
    failing.  No leaf is retained after its fold step.
    """

    encoded_domain = _domain_bytes(domain)
    exact_prior_count = _count(prior_count, label="ordered SHA-256 prefix-fold prior count")
    exact_appended_count = _count(
        appended_count,
        label="ordered SHA-256 prefix-fold appended count",
    )
    if exact_appended_count > _MAX_COUNT - exact_prior_count:
        _fail("ordered SHA-256 prefix-fold cumulative count exceeds its bound")
    root = _sha256_bytes(
        prior_root_sha256,
        label="ordered SHA-256 prefix-fold prior root",
    )
    if exact_prior_count == 0 and root != _empty_root(encoded_domain):
        _fail("ordered SHA-256 prefix-fold empty prior root differs from its domain")
    iterator = _item_iterator(item_sha256s)
    framed_domain = _domain_frame(encoded_domain)
    for offset in range(exact_appended_count):
        try:
            value = next(iterator)
        except StopIteration:
            _fail("ordered SHA-256 prefix-fold leaves underflow their exact count")
        leaf = _sha256_bytes(value, label="ordered SHA-256 prefix-fold leaf")
        root = _append_root(
            domain_frame=framed_domain,
            ordinal=exact_prior_count + offset + 1,
            prior_root=root,
            leaf=leaf,
        )
    try:
        next(iterator)
    except StopIteration:
        pass
    else:
        _fail("ordered SHA-256 prefix-fold leaves overflow their exact count")
    return OrderedSha256PrefixFoldV1(
        domain=cast("str", domain),
        count=exact_prior_count + exact_appended_count,
        root_sha256=root.hex(),
    )


def compute_ordered_sha256_prefix_fold(
    *,
    domain: object,
    count: object,
    item_sha256s: object,
) -> OrderedSha256PrefixFoldV1:
    """Compute one exact fold from its domain-specific empty state."""

    exact_count = _count(count, label="ordered SHA-256 prefix-fold count")
    empty = empty_ordered_sha256_prefix_fold(domain=domain)
    return extend_ordered_sha256_prefix_fold(
        domain=domain,
        prior_count=empty.count,
        prior_root_sha256=empty.root_sha256,
        appended_count=exact_count,
        item_sha256s=item_sha256s,
    )
