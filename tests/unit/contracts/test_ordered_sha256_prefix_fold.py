from __future__ import annotations

import hashlib
import inspect
import sys
from dataclasses import FrozenInstanceError, fields

import pytest

from nbadb.contracts.ordered_sha256_prefix_fold import (
    OrderedSha256PrefixFoldV1,
    compute_ordered_sha256_prefix_fold,
    empty_ordered_sha256_prefix_fold,
    extend_ordered_sha256_prefix_fold,
)

_DOMAIN = "nbadb.operation-data.raw-terminal-locator.v1"
_MAX_COUNT = (1 << 63) - 1
_ZERO_LEAF = "00" * 32
_ONE_LEAF = "11" * 32


def _leaf(index: int) -> str:
    return hashlib.sha256(f"leaf:{index}".encode()).hexdigest()


class _TextSubclass(str):
    pass


class _IntSubclass(int):
    pass


class _OnePassIterator:
    def __init__(self, values: tuple[object, ...]) -> None:
        self._values = values
        self._index = 0
        self.iter_calls = 0
        self.next_calls = 0

    def __iter__(self) -> _OnePassIterator:
        self.iter_calls += 1
        if self.iter_calls != 1:
            raise AssertionError("iterator was acquired more than once")
        return self

    def __next__(self) -> object:
        self.next_calls += 1
        if self._index == len(self._values):
            raise StopIteration
        value = self._values[self._index]
        self._index += 1
        return value


class _ForbiddenIterator:
    def __iter__(self) -> _ForbiddenIterator:
        raise AssertionError("aggregate overflow must fail before iteration")


def test_exact_empty_and_step_golden_vectors() -> None:
    empty = empty_ordered_sha256_prefix_fold(domain=_DOMAIN)
    first = extend_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        prior_count=empty.count,
        prior_root_sha256=empty.root_sha256,
        appended_count=1,
        item_sha256s=iter((_ZERO_LEAF,)),
    )
    second = extend_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        prior_count=first.count,
        prior_root_sha256=first.root_sha256,
        appended_count=1,
        item_sha256s=iter((_ONE_LEAF,)),
    )

    assert type(empty) is OrderedSha256PrefixFoldV1
    assert empty == OrderedSha256PrefixFoldV1(
        domain=_DOMAIN,
        count=0,
        root_sha256="4ef9ac2ed2153f2c3c279586fcbedbe9ca776887c20fb361678131b97db8ceb6",
    )
    assert first.root_sha256 == ("ed2af97fb45576c3a5c29eb2002a030fe11df349b62e8740b202cff6efbddc9d")
    assert second.root_sha256 == (
        "3ec2edad38745ba87105ab278e8a3f25807009b7f56b07ca3ea920d7063b6ce2"
    )


def test_compute_equals_extension_and_chunk_page_boundaries() -> None:
    leaves = tuple(_leaf(index) for index in range(513))
    complete = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=len(leaves),
        item_sha256s=iter(leaves),
    )
    state = empty_ordered_sha256_prefix_fold(domain=_DOMAIN)
    start = 0
    for chunk_size in (127, 128, 1, 257):
        chunk = leaves[start : start + chunk_size]
        state = extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=state.count,
            prior_root_sha256=state.root_sha256,
            appended_count=chunk_size,
            item_sha256s=iter(chunk),
        )
        start += chunk_size

    assert start == len(leaves)
    assert state == complete


def test_compute_a_plus_b_equals_extending_fold_a_with_b() -> None:
    first_leaves = tuple(_leaf(index) for index in range(31))
    second_leaves = tuple(_leaf(index) for index in range(31, 73))
    first = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=len(first_leaves),
        item_sha256s=iter(first_leaves),
    )
    extended = extend_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        prior_count=first.count,
        prior_root_sha256=first.root_sha256,
        appended_count=len(second_leaves),
        item_sha256s=iter(second_leaves),
    )
    complete = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=len(first_leaves) + len(second_leaves),
        item_sha256s=iter(first_leaves + second_leaves),
    )

    assert extended == complete


def test_exact_single_pass_and_zero_extension() -> None:
    leaves = _OnePassIterator((_leaf(0), _leaf(1), _leaf(2)))
    result = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=3,
        item_sha256s=leaves,
    )
    empty_suffix = _OnePassIterator(())
    unchanged = extend_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        prior_count=result.count,
        prior_root_sha256=result.root_sha256,
        appended_count=0,
        item_sha256s=empty_suffix,
    )

    assert leaves.iter_calls == 1
    assert leaves.next_calls == 4
    assert empty_suffix.iter_calls == 1
    assert empty_suffix.next_calls == 1
    assert unchanged == result


def test_underflow_and_overflow_stop_at_the_first_boundary() -> None:
    empty = empty_ordered_sha256_prefix_fold(domain=_DOMAIN)
    underflow = _OnePassIterator((_leaf(0), _leaf(1)))
    with pytest.raises(ValueError, match="underflow"):
        extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=0,
            prior_root_sha256=empty.root_sha256,
            appended_count=3,
            item_sha256s=underflow,
        )
    overflow = _OnePassIterator((_leaf(0), _leaf(1), _leaf(2), _leaf(3)))
    with pytest.raises(ValueError, match="overflow"):
        extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=0,
            prior_root_sha256=empty.root_sha256,
            appended_count=2,
            item_sha256s=overflow,
        )

    assert underflow.iter_calls == 1
    assert underflow.next_calls == 3
    assert overflow.iter_calls == 1
    assert overflow.next_calls == 3


def test_invalid_leaf_stops_without_consuming_a_later_leaf() -> None:
    leaves = _OnePassIterator((_leaf(0), "F" * 64, _leaf(2)))
    with pytest.raises(ValueError, match="leaf"):
        compute_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            count=3,
            item_sha256s=leaves,
        )

    assert leaves.iter_calls == 1
    assert leaves.next_calls == 2


@pytest.mark.parametrize(
    "domain",
    (
        "",
        "Uppercase",
        "-leading",
        "contains/slash",
        "nonascii-\N{LATIN SMALL LETTER E WITH ACUTE}",
        "a" * 201,
        _TextSubclass(_DOMAIN),
        None,
        b"bytes",
    ),
)
def test_invalid_domains_fail_closed(domain: object) -> None:
    with pytest.raises(ValueError, match="domain"):
        empty_ordered_sha256_prefix_fold(domain=domain)


def test_domain_exact_200_byte_boundary() -> None:
    accepted = "a" * 200
    assert empty_ordered_sha256_prefix_fold(domain=accepted).domain == accepted
    with pytest.raises(ValueError, match="domain"):
        empty_ordered_sha256_prefix_fold(domain="a" * 201)


@pytest.mark.parametrize(
    "count",
    (True, False, -1, _MAX_COUNT + 1, 1.0, "1", _IntSubclass(1), None),
)
def test_invalid_counts_and_subclasses_fail_closed(count: object) -> None:
    with pytest.raises(ValueError, match="count"):
        compute_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            count=count,
            item_sha256s=(),
        )


def test_cumulative_count_overflow_fails_before_iteration() -> None:
    with pytest.raises(ValueError, match="cumulative count"):
        extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=_MAX_COUNT,
            prior_root_sha256="ab" * 32,
            appended_count=1,
            item_sha256s=_ForbiddenIterator(),
        )


@pytest.mark.parametrize(
    "leaf",
    (
        "",
        "0" * 63,
        "0" * 65,
        "GG" * 32,
        "AA" * 32,
        _TextSubclass("ab" * 32),
        None,
        b"ab" * 32,
        1,
    ),
)
def test_invalid_leaf_types_and_encodings_fail_closed(leaf: object) -> None:
    with pytest.raises(ValueError, match="leaf"):
        compute_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            count=1,
            item_sha256s=iter((leaf,)),
        )


@pytest.mark.parametrize(
    "root",
    (
        "",
        "0" * 63,
        "F" * 64,
        "gg" * 32,
        _TextSubclass("ab" * 32),
        None,
        b"ab" * 32,
    ),
)
def test_invalid_prior_roots_fail_closed(root: object) -> None:
    with pytest.raises(ValueError, match="prior root"):
        extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=1,
            prior_root_sha256=root,
            appended_count=0,
            item_sha256s=(),
        )


@pytest.mark.parametrize("items", (None, 1, "digest", b"digest", bytearray(b"x")))
def test_non_iterable_or_scalar_leaf_inputs_fail_closed(items: object) -> None:
    with pytest.raises(ValueError, match="iterable"):
        compute_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            count=0,
            item_sha256s=items,
        )


def test_domain_order_drop_insert_and_duplicate_are_distinct() -> None:
    first, second, third, inserted = (_leaf(index) for index in range(4))
    variants = (
        (_DOMAIN, (first, second, third)),
        ("nbadb.operation-data.w2-operation.v1", (first, second, third)),
        (_DOMAIN, (second, first, third)),
        (_DOMAIN, (first, third)),
        (_DOMAIN, (first, inserted, second, third)),
        (_DOMAIN, (first, second, second, third)),
    )
    roots = {
        compute_ordered_sha256_prefix_fold(
            domain=domain,
            count=len(leaves),
            item_sha256s=iter(leaves),
        ).root_sha256
        for domain, leaves in variants
    }

    assert len(roots) == len(variants)


@pytest.mark.parametrize("count", (20_001, 200_001))
def test_streams_beyond_canonical_collection_and_graph_bounds(count: int) -> None:
    result = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=count,
        item_sha256s=(_ZERO_LEAF for _index in range(count)),
    )

    assert type(result) is OrderedSha256PrefixFoldV1
    assert result.count == count
    assert len(result.root_sha256) == 64


def test_dto_is_exact_immutable_and_constant_size() -> None:
    small = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=1,
        item_sha256s=iter((_ZERO_LEAF,)),
    )
    large = compute_ordered_sha256_prefix_fold(
        domain=_DOMAIN,
        count=20_001,
        item_sha256s=(_ZERO_LEAF for _index in range(20_001)),
    )

    assert tuple(field.name for field in fields(OrderedSha256PrefixFoldV1)) == (
        "domain",
        "count",
        "root_sha256",
    )
    assert sys.getsizeof(small) == sys.getsizeof(large)
    assert all(
        type(value) in {str, int} for value in (large.domain, large.count, large.root_sha256)
    )
    with pytest.raises(FrozenInstanceError):
        small.count = 2  # type: ignore[misc]
    with pytest.raises(ValueError, match="subclasses"):

        class _ForbiddenFold(OrderedSha256PrefixFoldV1):
            pass


def test_public_functions_are_keyword_only_and_exactly_named() -> None:
    expected = {
        empty_ordered_sha256_prefix_fold: ("domain",),
        extend_ordered_sha256_prefix_fold: (
            "domain",
            "prior_count",
            "prior_root_sha256",
            "appended_count",
            "item_sha256s",
        ),
        compute_ordered_sha256_prefix_fold: ("domain", "count", "item_sha256s"),
    }
    for function, names in expected.items():
        parameters = inspect.signature(function).parameters
        assert tuple(parameters) == names
        assert all(
            parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in parameters.values()
        )


def test_empty_state_rejects_a_foreign_root() -> None:
    with pytest.raises(ValueError, match="empty"):
        OrderedSha256PrefixFoldV1(
            domain=_DOMAIN,
            count=0,
            root_sha256="ab" * 32,
        )
    with pytest.raises(ValueError, match="empty"):
        extend_ordered_sha256_prefix_fold(
            domain=_DOMAIN,
            prior_count=0,
            prior_root_sha256="ab" * 32,
            appended_count=0,
            item_sha256s=(),
        )
