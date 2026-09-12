"""Exact installed-resource checks for sealed competition provenance."""

from __future__ import annotations

import hashlib
from importlib import resources

import pytest

_ROOT = ("provenance", "nba_api_v1_11_4")
_EXPECTED = {
    "competition_applicability/A1.2c.json": (
        18_042,
        317,
        "d2f668cd0627562508849423c5df5d8e0e120a2fecc270a44699c9fe4458bf91",
    ),
    "competition_applicability/competition-existence-evidence.json": (
        17_690,
        393,
        "876f79c748faa1f477dee8f15071d1799ad423d7e3b32e5b38e7c56cb34ccfa6",
    ),
    "competition_applicability/endpoint-support-evidence.json": (
        203_490,
        6_341,
        "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    ),
    "competition_applicability/source-review.json": (
        14_943,
        352,
        "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
    ),
    "competition_identity/A1.2e.json": (
        112_380,
        1_996,
        "d87507bb66d470dfec88626f8fc9c0b8484fa54dbb1244d564693414e18fc64c",
    ),
    "competition_identity/A1.3a.json": (
        97_245,
        2_030,
        "a2fea5fc1ef45404d9d917ed13107fc4356646810c222bb9234c832bdb7ed660",
    ),
    "competition_identity/A1.3a-repair-1.json": (
        131_669,
        2_305,
        "d4b8f42ce99a7aa587f123e1bdb3640a50a8f61343a24701d8f662c3b226cb1c",
    ),
    "competition_identity/A1.3a-repair-2.json": (
        150_660,
        2_537,
        "edd3d85dffc4274a6423c32ed5491adfcecafe401d7ad84f42ff261f7d1e4277",
    ),
    "competition_identity/A1.3a-repair-3.json": (
        168_029,
        3_187,
        "fb416dae2138193e46f0176b5ffe614ccae1f9f63732cbc7dc539117f7b27313",
    ),
    "competition_identity/A1.3a-repair-4.json": (
        195_745,
        3_766,
        "50a6a3aac9ae745310abd70cd6329b0ae0fccf400f6abf95812e973541cfc7cc",
    ),
    "competition_identity/A1.3a-repair-5.json": (
        244_906,
        4_847,
        "e580c8b09906b0c61d5963ba254621733ac1b5342d1e336b004e7103f200a28f",
    ),
    "competition_identity/A1.3a-repair-6.json": (
        318_301,
        6_370,
        "3f70b85f91b6ac00cbaf0afb6f29b17c116e03feddf4db3b6c50b1ac20d26b81",
    ),
    "competition_identity/A1.3a-repair-7.json": (
        340_405,
        6_755,
        "edcac7bc3665b75abb27f6620e6bee6beae8e8004d54dab0ea14964f3ce9fb90",
    ),
    "competition_identity/A1.3a-repair-8.json": (
        362_821,
        7_138,
        "cdcc5ebfd9a421dfad4687a875e321758df4af1bf65b10523146474843a6ffd5",
    ),
    "competition_identity/A1.3a-repair-9.json": (
        385_867,
        7_634,
        "2e3ba24efd741f36843cc6889a566a56479c140ebf5b940f8e087a509c1f26b1",
    ),
    "competition_identity/A1.3a-repair-10.json": (
        407_143,
        7_989,
        "86841cb180f840f545e11bcb8351e0d8c33dc73b35131e4343dad4f2c69493fb",
    ),
    "competition_identity/A1.3a-repair-11.json": (
        434_834,
        8_478,
        "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da",
    ),
    "implicit_competition/A1.2d.json": (
        43_345,
        844,
        "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    ),
    "implicit_competition/implicit-competition-root-evidence.json": (
        370_991,
        8_602,
        "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba",
    ),
    "implicit_competition/source-review.json": (
        15_888,
        309,
        "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8",
    ),
}


@pytest.mark.parametrize("relative", sorted(_EXPECTED))
def test_packaged_competition_provenance_is_exact(relative: str) -> None:
    """Every sealed source remains byte-identical inside an installed package."""

    expected_size, expected_lf_count, expected_sha256 = _EXPECTED[relative]
    raw = resources.files("nbadb.contracts").joinpath(*_ROOT, *relative.split("/")).read_bytes()

    assert len(raw) == expected_size
    assert raw.count(b"\n") == expected_lf_count
    assert hashlib.sha256(raw).hexdigest() == expected_sha256


def test_packaged_competition_provenance_inventory_is_closed() -> None:
    """The pinned provenance namespace contains no missing or foreign JSON member."""

    root = resources.files("nbadb.contracts").joinpath(*_ROOT)
    observed = {
        f"{group.name}/{member.name}"
        for group in root.iterdir()
        if group.is_dir()
        for member in group.iterdir()
        if member.is_file()
    }
    assert observed == set(_EXPECTED)
