from __future__ import annotations

import hashlib
from dataclasses import replace
from itertools import repeat

import pytest

from nbadb.contracts.ordered_sha256_prefix_fold import extend_ordered_sha256_prefix_fold
from nbadb.orchestrate.successor_planning_partition_authority import (
    MAX_SUCCESSOR_PLANNING_PARTITION_BYTES,
    SuccessorPlanningPartitionAuthorityError,
    SuccessorPlanningPartitionDescriptorV1,
    SuccessorPlanningPartitionHeaderV1,
    SuccessorPlanningRouteDispatchPartitionV1,
    SuccessorPlanningRouteDispatchRowV1,
    build_successor_planning_partition_header,
    empty_successor_planning_row_fold,
    iter_verified_successor_planning_rows,
)


def _sha(label: str) -> str:
    return hashlib.sha256(label.encode()).hexdigest()


def _row(
    ordinal: int,
    *,
    position: int = 0,
    scope: dict[str, object] | None = None,
) -> SuccessorPlanningRouteDispatchRowV1:
    return SuccessorPlanningRouteDispatchRowV1.from_canonical_scope(
        global_ordinal=ordinal,
        dispatch_identity_sha256=_sha(f"dispatch-{ordinal // 2}"),
        call_identity_sha256=_sha(f"call-{ordinal // 2}"),
        requested_scope_identity_sha256=_sha(f"scope-{ordinal}"),
        canonical_scope={} if scope is None else scope,
        staging_route_id=f"route:{ordinal}",
        route_contract_identity_sha256=_sha(f"route-contract-{ordinal}"),
        endpoint_identity_sha256=_sha(f"endpoint-{ordinal // 2}"),
        position=position,
        dependency_identity_sha256s=(_sha("dependency"),),
    )


def _partitions(
    rows: tuple[SuccessorPlanningRouteDispatchRowV1, ...],
    sizes: tuple[int, ...],
) -> tuple[SuccessorPlanningRouteDispatchPartitionV1, ...]:
    state = empty_successor_planning_row_fold()
    result: list[SuccessorPlanningRouteDispatchPartitionV1] = []
    offset = 0
    for partition_ordinal, size in enumerate(sizes):
        partition = SuccessorPlanningRouteDispatchPartitionV1.build(
            partition_ordinal=partition_ordinal,
            prior_fold=state,
            rows=rows[offset : offset + size],
        )
        result.append(partition)
        state = partition.row_fold
        offset += size
    assert offset == len(rows)
    return tuple(result)


def _loader(
    partitions: tuple[SuccessorPlanningRouteDispatchPartitionV1, ...],
):
    by_digest = {partition.content_sha256: partition.canonical_bytes() for partition in partitions}
    return lambda descriptor: by_digest[descriptor.content_sha256]


def _partition_with_exact_canonical_byte_length(
    byte_length: int,
) -> SuccessorPlanningRouteDispatchPartitionV1:
    row_count = 256
    empty_rows = tuple(_row(ordinal, scope={"padding": ""}) for ordinal in range(row_count))
    empty_length = len(_partitions(empty_rows, (row_count,))[0].canonical_bytes())
    padding_length, remainder = divmod(byte_length - empty_length, row_count)
    assert 0 <= padding_length < 60_000
    rows = tuple(
        _row(
            ordinal,
            scope={"padding": "x" * (padding_length + (ordinal < remainder))},
        )
        for ordinal in range(row_count)
    )
    partition = _partitions(rows, (row_count,))[0]
    assert len(partition.canonical_bytes()) == byte_length
    return partition


def _synthetic_descriptors(
    count: int,
) -> tuple[SuccessorPlanningPartitionDescriptorV1, ...]:
    state = empty_successor_planning_row_fold()
    descriptors: list[SuccessorPlanningPartitionDescriptorV1] = []
    for ordinal in range(count):
        row_count = 10_000
        next_state = extend_ordered_sha256_prefix_fold(
            domain=state.domain,
            prior_count=state.count,
            prior_root_sha256=state.root_sha256,
            appended_count=row_count,
            item_sha256s=repeat(_sha(f"synthetic-leaf-{ordinal}"), row_count),
        )
        descriptors.append(
            SuccessorPlanningPartitionDescriptorV1(
                partition_ordinal=ordinal,
                start_ordinal=state.count,
                end_ordinal=next_state.count - 1,
                row_count=row_count,
                canonical_byte_length=1,
                content_sha256=_sha(f"synthetic-partition-{ordinal}"),
                prior_row_root_sha256=state.root_sha256,
                row_root_sha256=next_state.root_sha256,
            )
        )
        state = next_state
    return tuple(descriptors)


def test_row_and_partition_exact_roundtrip_and_header_contains_no_rows() -> None:
    rows = (_row(0), _row(1, position=1))
    partitions = _partitions(rows, (1, 1))
    header = build_successor_planning_partition_header(iter(partitions))

    assert (
        SuccessorPlanningRouteDispatchRowV1.from_canonical_bytes(rows[0].canonical_bytes())
        == rows[0]
    )
    assert (
        SuccessorPlanningRouteDispatchPartitionV1.from_canonical_bytes(
            partitions[0].canonical_bytes()
        )
        == partitions[0]
    )
    assert (
        SuccessorPlanningPartitionHeaderV1.from_canonical_bytes(header.canonical_bytes()) == header
    )
    assert b'"rows"' not in header.canonical_bytes()
    assert tuple(iter_verified_successor_planning_rows(header, _loader(partitions))) == rows


def test_partition_accepts_9999_and_10000_rows_and_rejects_10001() -> None:
    for count in (9_999, 10_000):
        rows = tuple(_row(ordinal) for ordinal in range(count))
        partition = _partitions(rows, (count,))[0]
        assert partition.row_count == count
        assert len(partition.canonical_bytes()) <= MAX_SUCCESSOR_PLANNING_PARTITION_BYTES

    one = _row(0)
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="row_count"):
        SuccessorPlanningRouteDispatchPartitionV1(
            partition_ordinal=0,
            start_ordinal=0,
            end_ordinal=10_000,
            prior_row_root_sha256=empty_successor_planning_row_fold().root_sha256,
            rows=(one,) * 10_001,
            row_count=10_001,
            row_root_sha256=_sha("foreign"),
        )


def test_header_accepts_24_and_25_descriptors_and_rejects_26() -> None:
    for count in (24, 25):
        descriptors = _synthetic_descriptors(count)
        header = SuccessorPlanningPartitionHeaderV1(
            total_row_count=count * 10_000,
            total_row_root_sha256=descriptors[-1].row_root_sha256,
            descriptors=descriptors,
            descriptor_count=count,
        )
        assert header.descriptor_count == count

    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="partition_ordinal"):
        _synthetic_descriptors(26)


def test_total_row_root_is_invariant_across_partition_boundaries() -> None:
    rows = tuple(_row(index, position=index % 2) for index in range(7))
    one = _partitions(rows, (7,))
    several = _partitions(rows, (1, 2, 4))

    assert (
        build_successor_planning_partition_header(one).total_row_root_sha256
        == build_successor_planning_partition_header(several).total_row_root_sha256
    )
    assert (
        tuple(
            iter_verified_successor_planning_rows(
                build_successor_planning_partition_header(several), _loader(several)
            )
        )
        == rows
    )


@pytest.mark.parametrize("mutation", ["omission", "duplicate", "reorder", "overlap", "gap"])
def test_header_rejects_descriptor_omission_duplicate_reorder_overlap_and_gap(
    mutation: str,
) -> None:
    rows = tuple(_row(index) for index in range(3))
    descriptors = list(
        build_successor_planning_partition_header(_partitions(rows, (1, 1, 1))).descriptors
    )
    if mutation == "omission":
        descriptors = descriptors[1:]
    elif mutation == "duplicate":
        descriptors[1] = descriptors[0]
    elif mutation == "reorder":
        descriptors[0], descriptors[1] = descriptors[1], descriptors[0]
    elif mutation == "overlap":
        descriptors[1] = replace(descriptors[1], start_ordinal=0, end_ordinal=0)
    else:
        descriptors[1] = replace(descriptors[1], start_ordinal=2, end_ordinal=2)

    with pytest.raises(SuccessorPlanningPartitionAuthorityError):
        SuccessorPlanningPartitionHeaderV1(
            total_row_count=3,
            total_row_root_sha256=descriptors[-1].row_root_sha256,
            descriptors=tuple(descriptors),
            descriptor_count=len(descriptors),
        )


@pytest.mark.parametrize("mutation", ["missing", "extra", "truncated", "substitution"])
def test_stream_rejects_missing_extra_truncated_and_substituted_partition_bytes(
    mutation: str,
) -> None:
    rows = (_row(0), _row(1))
    partitions = _partitions(rows, (1, 1))
    header = build_successor_planning_partition_header(partitions)
    raw = partitions[0].canonical_bytes()
    other = partitions[1].canonical_bytes()

    loaded = {
        "missing": b"",
        "extra": raw + b"{}",
        "truncated": raw[:-1],
        "substitution": other,
    }[mutation]

    def loader(_descriptor: SuccessorPlanningPartitionDescriptorV1) -> bytes:
        return loaded

    with pytest.raises(SuccessorPlanningPartitionAuthorityError):
        tuple(iter_verified_successor_planning_rows(header, loader))


def test_stream_rejects_coherent_partition_reseal_and_stale_descriptor() -> None:
    rows = (_row(0),)
    original = _partitions(rows, (1,))
    header = build_successor_planning_partition_header(original)
    changed_row = replace(rows[0], call_identity_sha256=_sha("changed-call"))
    changed = _partitions((changed_row,), (1,))[0]

    def load_changed(_descriptor: SuccessorPlanningPartitionDescriptorV1) -> bytes:
        return changed.canonical_bytes()

    with pytest.raises(SuccessorPlanningPartitionAuthorityError):
        tuple(iter_verified_successor_planning_rows(header, load_changed))

    stale_descriptor = replace(header.descriptors[0], content_sha256=_sha("stale"))
    stale_header = SuccessorPlanningPartitionHeaderV1(
        total_row_count=1,
        total_row_root_sha256=stale_descriptor.row_root_sha256,
        descriptors=(stale_descriptor,),
        descriptor_count=1,
    )
    with pytest.raises(SuccessorPlanningPartitionAuthorityError):
        tuple(iter_verified_successor_planning_rows(stale_header, _loader(original)))


def test_route_scope_positional_swap_cannot_satisfy_original_header() -> None:
    first = _row(0, position=0, scope={"game_id": "001"})
    second = _row(1, position=1, scope={"game_id": "002"})
    original = _partitions((first, second), (2,))
    header = build_successor_planning_partition_header(original)
    swapped_first = replace(
        first,
        requested_scope_identity_sha256=second.requested_scope_identity_sha256,
        canonical_scope_body=second.canonical_scope_body,
        canonical_scope_body_sha256=second.canonical_scope_body_sha256,
        parameter_identity_sha256=second.parameter_identity_sha256,
        staging_route_id=second.staging_route_id,
        route_contract_identity_sha256=second.route_contract_identity_sha256,
    )
    swapped_second = replace(
        second,
        requested_scope_identity_sha256=first.requested_scope_identity_sha256,
        canonical_scope_body=first.canonical_scope_body,
        canonical_scope_body_sha256=first.canonical_scope_body_sha256,
        parameter_identity_sha256=first.parameter_identity_sha256,
        staging_route_id=first.staging_route_id,
        route_contract_identity_sha256=first.route_contract_identity_sha256,
    )
    swapped = _partitions((swapped_first, swapped_second), (2,))[0]

    def load_swapped(_descriptor: SuccessorPlanningPartitionDescriptorV1) -> bytes:
        return swapped.canonical_bytes()

    with pytest.raises(SuccessorPlanningPartitionAuthorityError):
        tuple(iter_verified_successor_planning_rows(header, load_swapped))


def test_strict_types_subclasses_paths_and_hostile_json_fail_closed() -> None:
    row = _row(0)
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="subclasses"):

        class ForeignRow(SuccessorPlanningRouteDispatchRowV1):
            pass

    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="integer"):
        replace(row, global_ordinal=True)
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="physical path"):
        _row(0, scope={"output_path": "/tmp/data"})

    duplicate = b'{"kind":"foreign",' + row.canonical_bytes()[1:]
    nonfinite = row.canonical_bytes().replace(b'"global_ordinal":0', b'"global_ordinal":NaN')
    boolean = row.canonical_bytes().replace(b'"global_ordinal":0', b'"global_ordinal":true')
    for hostile in (duplicate, nonfinite, boolean, row.canonical_bytes() + b"\n"):
        with pytest.raises(SuccessorPlanningPartitionAuthorityError):
            SuccessorPlanningRouteDispatchRowV1.from_canonical_bytes(hostile)


def test_partition_rejects_noncontiguous_rows_and_oversized_bytes() -> None:
    state = empty_successor_planning_row_fold()
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="globally contiguous"):
        SuccessorPlanningRouteDispatchPartitionV1.build(
            partition_ordinal=0,
            prior_fold=state,
            rows=(_row(0), _row(2)),
        )
    assert MAX_SUCCESSOR_PLANNING_PARTITION_BYTES == (12 * 1024 * 1024) - 1
    boundary = _partition_with_exact_canonical_byte_length(MAX_SUCCESSOR_PLANNING_PARTITION_BYTES)
    assert (
        SuccessorPlanningRouteDispatchPartitionV1.from_canonical_bytes(boundary.canonical_bytes())
        == boundary
    )

    oversized = boundary.canonical_bytes() + b"\n"
    assert len(oversized) == 12 * 1024 * 1024
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="oversized"):
        SuccessorPlanningRouteDispatchPartitionV1.from_canonical_bytes(oversized)

    descriptor = replace(
        SuccessorPlanningPartitionDescriptorV1.from_partition(boundary),
        canonical_byte_length=MAX_SUCCESSOR_PLANNING_PARTITION_BYTES,
    )
    assert descriptor.canonical_byte_length == MAX_SUCCESSOR_PLANNING_PARTITION_BYTES
    with pytest.raises(SuccessorPlanningPartitionAuthorityError, match="integer"):
        replace(descriptor, canonical_byte_length=12 * 1024 * 1024)
