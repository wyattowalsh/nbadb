from __future__ import annotations

import ast
import inspect
import json
import socket
import ssl
from collections import deque
from dataclasses import replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from nbadb.contracts import github_pull_request_review_admission as admission
from nbadb.contracts.github_pull_request_review_admission import (
    CallerClaimedGitHubRepositoryV1,
    CallerClaimedGitHubReviewerV1,
    CallerClaimedGitHubReviewPolicyV1,
    ExternalReviewResultBundleV1,
    GitHubApiReadReceiptV1,
    GitHubPullRequestReviewAdmissionError,
    UntrustedGitHubPullRequestReviewObservationV1,
    build_caller_claimed_review_submission_body,
    build_external_review_result_bundle,
    observe_github_pull_request_review_untrusted,
)
from nbadb.contracts.stable_model_review_packet import (
    StableModelReviewChallengeV1,
    StableModelReviewResultSlotV1,
    StableModelReviewShardV1,
)

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

SOURCE_SHA = "1" * 40
PULL_NUMBER = 47
REVIEW_ID = 9001
TOKEN = "test-token-never-log"
PR_URL = "https://api.github.com/repos/openai/nbadb/pulls/47"
REVIEW_URL = f"{PR_URL}/reviews/{REVIEW_ID}"
OBSERVED_AT = "2026-08-31T12:34:56.123456Z"


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _digest(character: str) -> str:
    return character * 64


def _slot(candidate_id: str, offset: int) -> StableModelReviewResultSlotV1:
    digests = tuple(_digest(character) for character in "abcdef")
    rotated = digests[offset:] + digests[:offset]
    candidate, structural, draft, pending, review_input = rotated[:5]
    return StableModelReviewResultSlotV1(
        candidate_id=candidate_id,
        topological_depth=0,
        candidate_sha256=candidate,
        candidate_structural_sha256=structural,
        draft_semantic_sha256=draft,
        pending_review_identity_sha256=pending,
        review_input_sha256=review_input,
        required_review_input_sha256s=tuple(
            sorted({candidate, structural, draft, pending, review_input, *digests})
        ),
    )


@pytest.fixture
def w0() -> tuple[StableModelReviewShardV1, StableModelReviewChallengeV1]:
    slots = (_slot("candidate.alpha", 0), _slot("candidate.beta", 1))
    shard = StableModelReviewShardV1(
        source_sha=SOURCE_SHA,
        topological_depth=0,
        shard_ordinal=0,
        candidate_source_authority_sha256=_digest("7"),
        candidate_census_canonical_bytes_sha256=_digest("8"),
        candidate_inventory_sha256=_digest("9"),
        disposition_draft_inventory_sha256=_digest("0"),
        review_input_inventory_sha256=_digest("1"),
        result_slots=slots,
    )
    challenge = StableModelReviewChallengeV1(
        source_sha=SOURCE_SHA,
        work_packet_sha256=_digest("2"),
        shard_id=shard.shard_id,
        shard_sha256=shard.shard_sha256,
        candidate_id_inventory_sha256=shard.candidate_id_inventory_sha256,
        result_slot_inventory_sha256=shard.result_slot_inventory_sha256,
        candidate_count=len(slots),
    )
    return shard, challenge


@pytest.fixture
def policy() -> CallerClaimedGitHubReviewPolicyV1:
    return CallerClaimedGitHubReviewPolicyV1(
        repository=CallerClaimedGitHubRepositoryV1(
            repository_id=101,
            repository_node_id="R_kgDOExample",
            owner_id=201,
            owner_node_id="O_kgDOExample",
            owner_login="openai",
            name="nbadb",
            full_name="openai/nbadb",
            base_ref="main",
        ),
        reviewer=CallerClaimedGitHubReviewerV1(
            reviewer_id=301,
            reviewer_node_id="U_kgDOReviewer",
            login="reviewer-one",
            user_type="User",
            role="maintainer",
            bot_policy="human_only",
        ),
    )


@pytest.fixture
def bundle(
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
) -> ExternalReviewResultBundleV1:
    shard, challenge = w0
    return build_external_review_result_bundle(
        shard=shard,
        challenge=challenge,
        payloads_by_candidate_id={
            "candidate.alpha": {
                "decision": "stable",
                "validation": ["positive", "negative", "mutation"],
            },
            "candidate.beta": {
                "decision": "experimental",
                "validation": ["positive", "negative", "mutation"],
            },
        },
    )


def _repo_payload(*, fork: bool = False) -> dict[str, object]:
    return {
        "id": 102 if fork else 101,
        "node_id": "R_kgDOFork" if fork else "R_kgDOExample",
        "name": "fork" if fork else "nbadb",
        "full_name": "other/fork" if fork else "openai/nbadb",
        "owner": {
            "id": 202 if fork else 201,
            "node_id": "O_kgDOFork" if fork else "O_kgDOExample",
            "login": "other" if fork else "openai",
            "type": "User",
            "extra": "ignored",
        },
        "private": True,
    }


def _pull_payload() -> dict[str, object]:
    return {
        "number": PULL_NUMBER,
        "node_id": "PR_kwDOExample",
        "url": PR_URL,
        "html_url": "https://github.com/openai/nbadb/pull/47",
        "state": "open",
        "merged": False,
        "merged_at": None,
        "user": {
            "id": 401,
            "node_id": "U_kgDOAuthor",
            "login": "author-one",
            "type": "User",
            "avatar_url": "ignored",
        },
        "base": {"ref": "main", "repo": _repo_payload(), "label": "ignored"},
        "head": {
            "ref": "review/model-shard",
            "sha": SOURCE_SHA,
            "repo": _repo_payload(),
            "label": "ignored",
        },
        "title": "ignored additive field",
    }


def _review_payload(body: str) -> dict[str, object]:
    return {
        "id": REVIEW_ID,
        "user": {
            "id": 301,
            "node_id": "U_kgDOReviewer",
            "login": "reviewer-one",
            "type": "User",
            "avatar_url": "ignored",
        },
        "body": body,
        "state": "APPROVED",
        "html_url": ("https://github.com/openai/nbadb/pull/47#pullrequestreview-9001"),
        "pull_request_url": PR_URL,
        "submitted_at": "2026-08-31T12:30:00Z",
        "commit_id": SOURCE_SHA,
        "author_association": "MEMBER",
    }


def _raw_read(url: str, payload: Mapping[str, object], index: int) -> admission._RawGitHubRead:
    return admission._RawGitHubRead(
        requested_url=url,
        final_url=url,
        status_code=200,
        raw_body=_canonical(payload),
        etag=f'"etag-{index}"',
        request_id=f"request-{index}",
        observed_at=OBSERVED_AT,
    )


def _script_reads(
    *,
    body: str,
    pull_payloads: tuple[Mapping[str, object], Mapping[str, object], Mapping[str, object]]
    | None = None,
    review_payloads: tuple[Mapping[str, object], Mapping[str, object]] | None = None,
) -> deque[admission._RawGitHubRead]:
    pulls = pull_payloads or (_pull_payload(), _pull_payload(), _pull_payload())
    reviews = review_payloads or (_review_payload(body), _review_payload(body))
    return deque(
        (
            _raw_read(PR_URL, pulls[0], 1),
            _raw_read(REVIEW_URL, reviews[0], 2),
            _raw_read(PR_URL, pulls[1], 3),
            _raw_read(REVIEW_URL, reviews[1], 4),
            _raw_read(PR_URL, pulls[2], 5),
        )
    )


def _observe(
    monkeypatch: pytest.MonkeyPatch,
    *,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
    reads: deque[admission._RawGitHubRead] | None = None,
    expected_source_sha: str = SOURCE_SHA,
) -> UntrustedGitHubPullRequestReviewObservationV1:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    scripted = reads or _script_reads(body=body)
    calls: list[tuple[str, int]] = []

    def fake_get(
        url: str,
        *,
        token: str,
        maximum_bytes: int,
    ) -> admission._RawGitHubRead:
        assert token == TOKEN
        calls.append((url, maximum_bytes))
        return scripted.popleft()

    monkeypatch.setattr(admission, "_https_get", fake_get)
    result = observe_github_pull_request_review_untrusted(
        caller_claimed_policy_canonical_bytes=policy.canonical_bytes,
        shard=shard,
        challenge=challenge,
        expected_source_sha=expected_source_sha,
        result_bundle_canonical_bytes=bundle.canonical_bytes,
        pull_number=PULL_NUMBER,
        review_id=REVIEW_ID,
        github_token=TOKEN,
    )
    assert calls == [
        (PR_URL, 2 * 1024 * 1024),
        (REVIEW_URL, 1024 * 1024),
        (PR_URL, 2 * 1024 * 1024),
        (REVIEW_URL, 1024 * 1024),
        (PR_URL, 2 * 1024 * 1024),
    ]
    assert not scripted
    return result


@pytest.fixture
def observation(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> UntrustedGitHubPullRequestReviewObservationV1:
    return _observe(monkeypatch, policy=policy, w0=w0, bundle=bundle)


def _mutated(
    value: Mapping[str, object],
    mutate: Callable[[dict[str, object]], None],
) -> dict[str, object]:
    result = cast("dict[str, object]", json.loads(json.dumps(value)))
    mutate(result)
    return result


def _replace_read(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
    index: int,
    **changes: object,
) -> tuple[GitHubApiReadReceiptV1, ...]:
    reads = list(observation.reads)
    reads[index] = replace(reads[index], **changes)  # type: ignore[arg-type]
    return tuple(reads)


def test_positive_observation_is_exact_stabilized_and_remains_red(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    result = _observe(monkeypatch, policy=policy, w0=w0, bundle=bundle)

    assert result.schema_version == 1
    assert result.repository_id == policy.repository.repository_id
    assert result.claimed_policy_sha256 == policy.claimed_policy_sha256
    assert result.source_sha == SOURCE_SHA
    assert result.shard_sha256 == shard.shard_sha256
    assert result.challenge_sha256 == challenge.challenge_sha256
    assert result.result_bundle_sha256 == bundle.result_bundle_sha256
    assert result.candidate_count == 2
    assert tuple((item.read_ordinal, item.read_label) for item in result.reads) == (
        (1, "PR_A"),
        (2, "review_A"),
        (3, "PR_B"),
        (4, "review_B"),
        (5, "PR_C"),
    )
    assert all(item.raw_sha256 and item.projection_sha256 for item in result.reads)
    assert tuple(item.etag for item in result.reads) == tuple(
        f'"etag-{index}"' for index in range(1, 6)
    )
    assert result.read_inventory_sha256
    assert result.first_observed_at == OBSERVED_AT
    assert result.last_observed_at == OBSERVED_AT
    assert result.trust_class == "caller_supplied_untrusted"
    assert result.point_in_time_only is True
    assert result.requires_protected_reverification is True
    assert result.protected_identity_admitted is False
    assert result.review_gate_green is False
    assert json.loads(result.canonical_bytes)["observation_sha256"]


def test_arbitrary_self_consistent_caller_policy_can_only_emit_untrusted_red(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    arbitrary = replace(
        policy,
        reviewer=CallerClaimedGitHubReviewerV1(
            reviewer_id=999,
            reviewer_node_id="U_callerChosen",
            login="caller-chosen",
            user_type="User",
            role="owner",
            bot_policy="human_only",
        ),
    )
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=arbitrary,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    review = _review_payload(body)
    reviewer = cast("dict[str, object]", review["user"])
    reviewer.update(
        {
            "id": arbitrary.reviewer.reviewer_id,
            "node_id": arbitrary.reviewer.reviewer_node_id,
            "login": arbitrary.reviewer.login,
            "type": arbitrary.reviewer.user_type,
        }
    )
    result = _observe(
        monkeypatch,
        policy=arbitrary,
        w0=w0,
        bundle=bundle,
        reads=_script_reads(body=body, review_payloads=(review, review)),
    )

    assert result.claimed_policy_sha256 == arbitrary.claimed_policy_sha256
    assert result.trust_class == "caller_supplied_untrusted"
    assert result.requires_protected_reverification is True
    assert result.protected_identity_admitted is False
    assert result.review_gate_green is False


def test_observation_and_nested_read_have_exact_canonical_round_trips(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    observation = _observe(monkeypatch, policy=policy, w0=w0, bundle=bundle)

    assert (
        GitHubApiReadReceiptV1.from_dict(observation.reads[0].to_dict()) == (observation.reads[0])
    )
    assert (
        UntrustedGitHubPullRequestReviewObservationV1.from_canonical_bytes(
            observation.canonical_bytes
        )
        == observation
    )
    assert observation.observation_sha256 == observation.to_dict()["observation_sha256"]


def test_observation_wire_rejects_missing_extra_bool_int_and_nested_confusion(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
) -> None:
    original = observation.to_dict()
    mutations: list[dict[str, object]] = []

    missing = cast("dict[str, object]", json.loads(json.dumps(original)))
    missing.pop("read_inventory_sha256")
    mutations.append(missing)

    extra = cast("dict[str, object]", json.loads(json.dumps(original)))
    extra["trusted"] = True
    mutations.append(extra)

    for field_name in ("schema_version", "repository_id", "candidate_count"):
        bool_int = cast("dict[str, object]", json.loads(json.dumps(original)))
        bool_int[field_name] = True
        mutations.append(bool_int)

    nested_missing = cast("dict[str, object]", json.loads(json.dumps(original)))
    nested_reads = cast("list[dict[str, object]]", nested_missing["reads"])
    nested_reads[0].pop("receipt_sha256")
    mutations.append(nested_missing)

    nested_extra = cast("dict[str, object]", json.loads(json.dumps(original)))
    nested_reads = cast("list[dict[str, object]]", nested_extra["reads"])
    nested_reads[0]["trusted"] = True
    mutations.append(nested_extra)

    nested_bool_int = cast("dict[str, object]", json.loads(json.dumps(original)))
    nested_reads = cast("list[dict[str, object]]", nested_bool_int["reads"])
    nested_reads[0]["read_ordinal"] = True
    mutations.append(nested_bool_int)

    resealed = cast("dict[str, object]", json.loads(json.dumps(original)))
    resealed["observation_sha256"] = "f" * 64
    mutations.append(resealed)

    for payload in mutations:
        with pytest.raises(GitHubPullRequestReviewAdmissionError):
            UntrustedGitHubPullRequestReviewObservationV1.from_canonical_bytes(_canonical(payload))


def test_observation_wire_rejects_duplicate_nonfinite_and_noncanonical_bytes(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
) -> None:
    raw = observation.canonical_bytes
    duplicate = b'{"kind":"duplicate",' + raw[1:]
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="duplicate"):
        UntrustedGitHubPullRequestReviewObservationV1.from_canonical_bytes(duplicate)

    nonfinite = raw.replace(b'"candidate_count":2', b'"candidate_count":NaN', 1)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="non-finite"):
        UntrustedGitHubPullRequestReviewObservationV1.from_canonical_bytes(nonfinite)

    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="canonical JSON"):
        UntrustedGitHubPullRequestReviewObservationV1.from_canonical_bytes(raw + b"\n")


@pytest.mark.parametrize("index", range(5))
def test_observation_rejects_every_read_url_projection_and_raw_hash_mutation(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
    index: int,
) -> None:
    is_review = "review" in observation.reads[index].read_label
    foreign_url = "https://api.github.com/repos/openai/foreign/pulls/47"
    if is_review:
        foreign_url += f"/reviews/{REVIEW_ID}"
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="URL/projection"):
        replace(
            observation,
            reads=_replace_read(observation, index, requested_url=foreign_url),
        )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="URL/projection"):
        replace(
            observation,
            reads=_replace_read(observation, index, projection_sha256="f" * 64),
        )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="inventory root"):
        replace(
            observation,
            reads=_replace_read(observation, index, raw_sha256="f" * 64),
        )


@pytest.mark.parametrize("index", range(5))
def test_observation_rejects_every_read_ordinal_label_and_receipt_digest_mutation(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
    index: int,
) -> None:
    next_ordinal, next_label = admission._READ_SEQUENCE[(index + 1) % 5]
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="five-read sequence"):
        replace(
            observation,
            reads=_replace_read(
                observation,
                index,
                read_ordinal=next_ordinal,
                read_label=next_label,
            ),
        )

    receipt_payload = observation.reads[index].to_dict()
    receipt_payload["receipt_sha256"] = "f" * 64
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="reconstruction"):
        GitHubApiReadReceiptV1.from_dict(receipt_payload)


def test_observation_rejects_reordered_cross_swapped_and_reversed_time_receipts(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
) -> None:
    reordered = list(observation.reads)
    reordered[0], reordered[1] = reordered[1], reordered[0]
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="five-read sequence"):
        replace(observation, reads=tuple(reordered))

    foreign = GitHubApiReadReceiptV1(
        read_ordinal=1,
        read_label="PR_A",
        requested_url="https://api.github.com/repos/openai/foreign/pulls/47",
        raw_sha256="a" * 64,
        projection_sha256=observation.pull_request_projection_sha256,
        etag='"foreign"',
        request_id="foreign-request",
        observed_at=observation.first_observed_at,
    )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="URL/projection"):
        replace(observation, reads=(foreign, *observation.reads[1:]))

    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="nondecreasing"):
        replace(
            observation,
            reads=_replace_read(
                observation,
                2,
                observed_at="2026-08-31T12:34:55Z",
            ),
        )


def test_observation_rejects_first_last_read_root_and_top_projection_mutations(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
) -> None:
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="first/last"):
        replace(observation, first_observed_at="2026-08-31T12:34:55Z")
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="first/last"):
        replace(observation, last_observed_at="2026-08-31T12:34:57Z")
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="inventory root"):
        replace(observation, read_inventory_sha256="f" * 64)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="URL/projection"):
        replace(observation, pull_request_projection_sha256="f" * 64)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="URL/projection"):
        replace(observation, review_projection_sha256="f" * 64)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("trust_class", "trusted"),
        ("point_in_time_only", False),
        ("requires_protected_reverification", False),
        ("protected_identity_admitted", True),
        ("review_gate_green", True),
    ],
)
def test_observation_rejects_every_trust_or_green_reseal(
    observation: UntrustedGitHubPullRequestReviewObservationV1,
    field_name: str,
    value: object,
) -> None:
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="protected identity|green"):
        replace(observation, **{field_name: value})


def test_caller_claimed_policy_is_canonical_typed_and_self_digest_bound(
    policy: CallerClaimedGitHubReviewPolicyV1,
) -> None:
    checked = CallerClaimedGitHubReviewPolicyV1.from_canonical_bytes(
        policy.canonical_bytes,
    )
    assert checked == policy
    assert checked.trust_class == "caller_supplied_untrusted"

    payload = policy.to_dict()
    payload["claimed_policy_sha256"] = "f" * 64
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="reconstruction"):
        CallerClaimedGitHubReviewPolicyV1.from_canonical_bytes(_canonical(payload))
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="canonical JSON"):
        CallerClaimedGitHubReviewPolicyV1.from_canonical_bytes(
            policy.canonical_bytes + b"\n",
        )


@pytest.mark.parametrize(
    ("constructor", "match"),
    [
        (
            lambda: CallerClaimedGitHubRepositoryV1(
                repository_id=101,
                repository_node_id="R_node",
                owner_id=201,
                owner_node_id="O_node",
                owner_login="OpenAI",
                name="nbadb",
                full_name="OpenAI/nbadb",
                base_ref="main",
            ),
            "canonical ASCII",
        ),
        (
            lambda: CallerClaimedGitHubRepositoryV1(
                repository_id=101,
                repository_node_id="R_node",
                owner_id=201,
                owner_node_id="O_node",
                owner_login="openai",
                name="nbadb",
                full_name="other/nbadb",
                base_ref="main",
            ),
            "full_name",
        ),
        (
            lambda: CallerClaimedGitHubReviewerV1(
                reviewer_id=301,
                reviewer_node_id="U_bot",
                login="review-bot",
                user_type="Bot",
                role="member",
                bot_policy="human_only",
            ),
            "forbidden by policy",
        ),
    ],
)
def test_caller_claimed_policy_rejects_noncanonical_or_foreign_identity(
    constructor: Callable[[], object],
    match: str,
) -> None:
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match=match):
        constructor()


def test_result_bundle_is_exact_sorted_unique_w0_union(
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    assert tuple(item.candidate_id for item in bundle.entries) == shard.candidate_ids
    assert bundle.entry_inventory_sha256
    assert bundle.payload_inventory_sha256
    assert (
        ExternalReviewResultBundleV1.from_canonical_bytes(
            bundle.canonical_bytes,
            shard=shard,
            challenge=challenge,
        )
        == bundle
    )

    for payloads in (
        {"candidate.alpha": {}},
        {"candidate.alpha": {}, "candidate.beta": {}, "foreign": {}},
    ):
        with pytest.raises(GitHubPullRequestReviewAdmissionError, match="candidate union"):
            build_external_review_result_bundle(
                shard=shard,
                challenge=challenge,
                payloads_by_candidate_id=payloads,
            )


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (
            lambda value: value["entries"].reverse(),
            "not sorted",
        ),
        (
            lambda value: value["entries"].__setitem__(1, value["entries"][0]),
            "duplicated",
        ),
        (
            lambda value: value["entries"][0].__setitem__("candidate_sha256", "f" * 64),
            "exact reconstruction|exact W0 slot",
        ),
        (
            lambda value: value["entries"][0]["payload"].__setitem__("decision", "changed"),
            "payload differs",
        ),
    ],
)
def test_result_bundle_rejects_reordering_duplicates_stale_slots_and_payloads(
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
    mutate: Callable[[dict[str, object]], None],
    match: str,
) -> None:
    shard, challenge = w0
    payload = json.loads(bundle.canonical_bytes)
    mutate(payload)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match=match):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            _canonical(payload),
            shard=shard,
            challenge=challenge,
        )


def test_result_bundle_parser_rejects_duplicate_nonfinite_noncanonical_size_depth_and_nodes(
    monkeypatch: pytest.MonkeyPatch,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    duplicate = bundle.canonical_bytes[:-1] + b',"kind":"external_review_result_bundle_v1"}'
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="duplicate"):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            duplicate,
            shard=shard,
            challenge=challenge,
        )
    nonfinite = bundle.canonical_bytes.replace(b'"decision":"stable"', b'"decision":NaN')
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="non-finite"):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            nonfinite,
            shard=shard,
            challenge=challenge,
        )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="canonical JSON"):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            bundle.canonical_bytes + b"\n",
            shard=shard,
            challenge=challenge,
        )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="size"):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            b"x" * (4 * 1024 * 1024 + 1),
            shard=shard,
            challenge=challenge,
        )
    monkeypatch.setattr(admission, "_MAX_JSON_DEPTH", 2)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="depth"):
        admission._decode_json(
            b"[[[]]]",
            label="test",
            maximum_bytes=100,
            require_canonical=False,
        )
    monkeypatch.setattr(admission, "_MAX_JSON_NODES", 2)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="node"):
        admission._decode_json(
            b'{"a":1,"b":2}',
            label="test",
            maximum_bytes=100,
            require_canonical=False,
        )


def test_w0_join_rejects_foreign_challenge(
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    foreign = replace(challenge, work_packet_sha256="f" * 64)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="exact reconstruction|W0"):
        ExternalReviewResultBundleV1.from_canonical_bytes(
            bundle.canonical_bytes,
            shard=shard,
            challenge=foreign,
        )


def test_review_body_is_exact_ascii_without_code_fence_or_slack(
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    assert body.startswith("NBADB-STABLE-MODEL-REVIEW-V1\n")
    assert "trust_class:caller_supplied_untrusted" in body
    assert f"claimed_policy_sha256:{policy.claimed_policy_sha256}" in body
    assert f"challenge_sha256:{challenge.challenge_sha256}" in body
    assert f"result_bundle_sha256:{bundle.result_bundle_sha256}" in body
    assert body.encode("ascii").decode("ascii") == body
    assert "```" not in body
    assert not body.endswith((" ", "\n"))
    assert all(line == line.strip() for line in body.splitlines())


def _set_path(payload: dict[str, object], path: tuple[str, ...], value: object) -> None:
    current = payload
    for part in path[:-1]:
        current = cast("dict[str, object]", current[part])
    current[path[-1]] = value


@pytest.mark.parametrize(
    ("target", "path", "value", "match"),
    [
        ("pull", ("url",), "https://API.github.com/repos/openai/nbadb/pulls/47", "URL"),
        ("pull", ("html_url",), "https://github.com:443/openai/nbadb/pull/47", "URL"),
        ("pull", ("base", "repo", "id"), 999, "repository projection"),
        ("pull", ("base", "ref"), "develop", "base ref"),
        ("pull", ("head", "sha"), "2" * 40, "source SHA"),
        ("pull", ("state",), "closed", "open and unmerged"),
        ("pull", ("merged",), True, "open and unmerged"),
        ("review", ("id",), 9002, "review id"),
        ("review", ("pull_request_url",), PR_URL + "?x=1", "review URL"),
        (
            "review",
            ("html_url",),
            "https://github.com/openai/nbadb/pull/47#pullrequestreview-09001",
            "review URL",
        ),
        ("review", ("commit_id",), "2" * 40, "source SHA"),
        ("review", ("user", "id"), 999, "caller-claimed policy"),
        ("review", ("user", "node_id"), "U_other", "caller-claimed policy"),
        ("review", ("user", "login"), "other", "caller-claimed policy"),
        ("review", ("user", "type"), "Bot", "caller-claimed policy"),
        ("review", ("state",), "DISMISSED", "not submitted"),
        ("review", ("body",), "replayed-or-edited", "body differs"),
        ("review", ("submitted_at",), "2026-08-31T12:30:00+00:00", "RFC3339"),
    ],
)
def test_observation_fails_closed_for_identity_url_state_body_and_time_confusion(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
    target: str,
    path: tuple[str, ...],
    value: object,
    match: str,
) -> None:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    pull = _pull_payload()
    review = _review_payload(body)
    _set_path(pull if target == "pull" else review, path, value)
    reads = _script_reads(
        body=body,
        pull_payloads=(pull, pull, pull),
        review_payloads=(review, review),
    )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match=match):
        _observe(monkeypatch, policy=policy, w0=w0, bundle=bundle, reads=reads)


def test_fork_and_self_review_are_rejected_by_numeric_and_node_identity(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    fork = _pull_payload()
    cast("dict[str, object]", fork["head"])["repo"] = _repo_payload(fork=True)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="repository projection|fork"):
        _observe(
            monkeypatch,
            policy=policy,
            w0=w0,
            bundle=bundle,
            reads=_script_reads(
                body=body,
                pull_payloads=(fork, fork, fork),
            ),
        )

    for author_field, author_value in (
        ("id", policy.reviewer.reviewer_id),
        ("node_id", policy.reviewer.reviewer_node_id),
    ):
        pull = _pull_payload()
        cast("dict[str, object]", pull["user"])[author_field] = author_value
        with pytest.raises(GitHubPullRequestReviewAdmissionError, match="self-authored"):
            _observe(
                monkeypatch,
                policy=policy,
                w0=w0,
                bundle=bundle,
                reads=_script_reads(
                    body=body,
                    pull_payloads=(pull, pull, pull),
                ),
            )


def test_expected_source_and_replayed_result_bundle_fail_before_or_at_body_join(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="expected source"):
        _observe(
            monkeypatch,
            policy=policy,
            w0=w0,
            bundle=bundle,
            expected_source_sha="2" * 40,
        )

    shard, challenge = w0
    old_body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    changed = build_external_review_result_bundle(
        shard=shard,
        challenge=challenge,
        payloads_by_candidate_id={
            "candidate.alpha": {"decision": "changed"},
            "candidate.beta": {"decision": "experimental"},
        },
    )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="body differs"):
        _observe(
            monkeypatch,
            policy=policy,
            w0=w0,
            bundle=changed,
            reads=_script_reads(body=old_body),
        )


def test_exact_five_read_stabilization_rejects_pr_or_review_mutation(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
) -> None:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    changed_pull = _mutated(
        _pull_payload(),
        lambda payload: cast("dict[str, object]", payload["head"]).__setitem__(
            "ref", "changed-ref"
        ),
    )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="did not stabilize"):
        _observe(
            monkeypatch,
            policy=policy,
            w0=w0,
            bundle=bundle,
            reads=_script_reads(
                body=body,
                pull_payloads=(_pull_payload(), changed_pull, _pull_payload()),
            ),
        )
    changed_review = _mutated(
        _review_payload(body),
        lambda payload: payload.__setitem__("state", "COMMENTED"),
    )
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="did not stabilize"):
        _observe(
            monkeypatch,
            policy=policy,
            w0=w0,
            bundle=bundle,
            reads=_script_reads(
                body=body,
                review_payloads=(_review_payload(body), changed_review),
            ),
        )


def test_github_json_rejects_duplicate_nonfinite_invalid_size_depth_and_node(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="duplicate"):
        admission._parse_review(b'{"id":1,"id":2}')
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="non-finite"):
        admission._parse_review(b'{"id":1,"extra":NaN}')
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="size"):
        admission._parse_review(b"x" * (1024 * 1024 + 1))
    monkeypatch.setattr(admission, "_MAX_JSON_DEPTH", 2)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="depth"):
        admission._parse_review(b'{"a":{"b":{"c":1}}}')
    monkeypatch.setattr(admission, "_MAX_JSON_NODES", 2)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match="node"):
        admission._parse_review(b'{"a":1,"b":2}')


@pytest.mark.parametrize(
    ("replacement", "match"),
    [
        (replace(_raw_read(PR_URL, _pull_payload(), 1), final_url=PR_URL + "?redirect=1"), "URL"),
        (replace(_raw_read(PR_URL, _pull_payload(), 1), status_code=302), "status 200"),
        (replace(_raw_read(PR_URL, _pull_payload(), 1), raw_body=b""), "size"),
        (replace(_raw_read(PR_URL, _pull_payload(), 1), observed_at="not-a-time"), "RFC3339"),
    ],
)
def test_read_envelope_rejects_redirect_status_size_and_time(
    monkeypatch: pytest.MonkeyPatch,
    policy: CallerClaimedGitHubReviewPolicyV1,
    w0: tuple[StableModelReviewShardV1, StableModelReviewChallengeV1],
    bundle: ExternalReviewResultBundleV1,
    replacement: admission._RawGitHubRead,
    match: str,
) -> None:
    shard, challenge = w0
    body = build_caller_claimed_review_submission_body(
        policy=policy,
        pull_number=PULL_NUMBER,
        shard=shard,
        challenge=challenge,
        result_bundle=bundle,
    )
    reads = _script_reads(body=body)
    reads[0] = replacement
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match=match):
        _observe(monkeypatch, policy=policy, w0=w0, bundle=bundle, reads=reads)


class _FakeResponse:
    def __init__(self, *, status: int = 200, raw: bytes = b"{}", encoding: str | None = None):
        self.status = status
        self._raw = raw
        self._encoding = encoding

    def getheader(self, name: str) -> str | None:
        return {
            "Content-Encoding": self._encoding,
            "ETag": '"etag"',
            "X-GitHub-Request-Id": "request-id",
        }.get(name)

    def read(self, amount: int) -> bytes:
        return self._raw[:amount]


class _FakeConnection:
    created: list[_FakeConnection] = []
    response = _FakeResponse()

    def __init__(
        self,
        host: str,
        *,
        port: int,
        timeout: float,
        context: ssl.SSLContext,
    ) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.context = context
        self.request_args: tuple[str, str, dict[str, str]] | None = None
        self.closed = False
        self.__class__.created.append(self)

    def request(self, method: str, path: str, *, headers: dict[str, str]) -> None:
        self.request_args = (method, path, headers)

    def getresponse(self) -> _FakeResponse:
        return self.__class__.response

    def close(self) -> None:
        self.closed = True


def test_private_https_client_is_fixed_host_tls_verified_header_exact_and_no_proxy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _FakeConnection.created.clear()
    _FakeConnection.response = _FakeResponse()
    monkeypatch.setattr(admission.http.client, "HTTPSConnection", _FakeConnection)
    result = admission._https_get(PR_URL, token=TOKEN, maximum_bytes=1024)

    connection = _FakeConnection.created[0]
    assert connection.host == "api.github.com"
    assert connection.port == 443
    assert isinstance(connection.context, ssl.SSLContext)
    assert connection.context.verify_mode == ssl.CERT_REQUIRED
    assert connection.context.check_hostname is True
    assert connection.request_args == (
        "GET",
        "/repos/openai/nbadb/pulls/47",
        {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2026-03-10",
            "Accept-Encoding": "identity",
            "User-Agent": "nbadb-pr-review-observer/1",
            "Authorization": f"Bearer {TOKEN}",
        },
    )
    assert result.final_url == PR_URL
    assert connection.closed is True


@pytest.mark.parametrize(
    ("response", "match"),
    [
        (_FakeResponse(status=301), "non-200"),
        (_FakeResponse(status=429), "non-200"),
        (_FakeResponse(status=500), "non-200"),
        (_FakeResponse(raw=b"x" * 11), "size"),
        (_FakeResponse(encoding="gzip"), "content encoding"),
    ],
)
def test_private_https_client_fails_closed_on_status_rate_limit_size_and_encoding(
    monkeypatch: pytest.MonkeyPatch,
    response: _FakeResponse,
    match: str,
) -> None:
    _FakeConnection.created.clear()
    _FakeConnection.response = response
    monkeypatch.setattr(admission.http.client, "HTTPSConnection", _FakeConnection)
    with pytest.raises(GitHubPullRequestReviewAdmissionError, match=match):
        admission._https_get(PR_URL, token=TOKEN, maximum_bytes=10)


@pytest.mark.parametrize(
    "failure",
    [
        TimeoutError("test-token-never-log"),
        ssl.SSLError("test-token-never-log"),
        socket.gaierror("test-token-never-log"),
        OSError("test-token-never-log"),
    ],
)
def test_transport_and_invalid_json_errors_redact_token_and_body(
    monkeypatch: pytest.MonkeyPatch,
    failure: BaseException,
) -> None:
    class FailingConnection:
        def __init__(self, *_args: object, **_kwargs: object) -> None:
            raise failure

    monkeypatch.setattr(admission.http.client, "HTTPSConnection", FailingConnection)
    with pytest.raises(GitHubPullRequestReviewAdmissionError) as caught:
        admission._https_get(PR_URL, token=TOKEN, maximum_bytes=1024)
    assert TOKEN not in str(caught.value)

    secret_body = b'{"secret":"must-not-echo", broken}'
    with pytest.raises(GitHubPullRequestReviewAdmissionError) as malformed:
        admission._parse_review(secret_body)
    assert "must-not-echo" not in str(malformed.value)


def test_token_and_url_confusion_fail_without_secret_echo() -> None:
    for token in ("", " leading", "trailing ", "line\nbreak"):
        with pytest.raises(GitHubPullRequestReviewAdmissionError) as caught:
            admission._https_get(PR_URL, token=token, maximum_bytes=1024)
        if token:
            assert token not in str(caught.value)
    for url in (
        "http://api.github.com/repos/openai/nbadb/pulls/47",
        "https://API.github.com/repos/openai/nbadb/pulls/47",
        "https://api.github.com:443/repos/openai/nbadb/pulls/47",
        "https://api.github.com:bad/repos/openai/nbadb/pulls/47",
        "https://api.github.com/repos/openai/nbadb/pulls/47?x=1",
        "https://user@api.github.com/repos/openai/nbadb/pulls/47",
    ):
        with pytest.raises(GitHubPullRequestReviewAdmissionError, match="fixed-host HTTPS"):
            admission._https_get(url, token=TOKEN, maximum_bytes=1024)


def test_module_has_no_review_receipt_green_or_public_transport_injection() -> None:
    source_path = Path(admission.__file__)
    source = source_path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    names = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    attributes = {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    signature = inspect.signature(observe_github_pull_request_review_untrusted)

    assert "nbadb.contracts.review_evidence" not in imported_modules
    assert "ReviewReceiptV1" not in names | attributes
    assert "authority_green" not in source
    assert "protected_identity_admitted: Literal[False]" in source
    assert "review_gate_green: Literal[False]" in source
    assert not {
        "ProtectedGitHubRepositoryV1",
        "ProtectedGitHubReviewerV1",
        "ProtectedGitHubPullRequestReviewAuthorityV1",
        "GitHubPullRequestReviewObservationV1",
        "observe_github_pull_request_review",
        "build_review_submission_body",
    } & (names | attributes)
    assert set(signature.parameters) == {
        "caller_claimed_policy_canonical_bytes",
        "shard",
        "challenge",
        "expected_source_sha",
        "result_bundle_canonical_bytes",
        "pull_number",
        "review_id",
        "github_token",
    }
    assert not {
        "base_url",
        "transport",
        "response_json",
        "verified",
        "review_body",
        "nonce",
        "expires_at",
        "protected_authority_canonical_bytes",
        "expected_protected_authority_sha256",
        "trust_root",
        "resolver",
    } & set(signature.parameters)
    assert not any(
        "protected" in name
        or "resolver" in name
        or ("policy" in name and ("sha" in name or "digest" in name))
        for name in signature.parameters
    )
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and any(alias.name == "logging" for alias in node.names)
        for node in ast.walk(tree)
    )
