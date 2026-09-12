"""Installed-wheel proof for sealed competition contract resources."""

from __future__ import annotations

import subprocess
import sys
import zipfile
from pathlib import Path

_PROJECT_ROOT = Path(__file__).parents[2]
_PROVENANCE_PREFIX = "nbadb/contracts/provenance/nba_api_v1_11_4/"


def test_built_wheel_compiles_competition_identity_outside_checkout(
    tmp_path: Path,
) -> None:
    """The wheel is self-contained and never needs ignored assurance artifacts."""

    dist = tmp_path / "dist"
    build = subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(dist)],
        cwd=_PROJECT_ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert build.returncode == 0, build.stderr
    wheels = list(dist.glob("*.whl"))
    assert len(wheels) == 1
    wheel = wheels[0]

    with zipfile.ZipFile(wheel) as archive:
        members = archive.namelist()
    assert (
        len(
            [
                member
                for member in members
                if member.startswith(_PROVENANCE_PREFIX) and member.endswith(".json")
            ]
        )
        == 20
    )
    assert not any(
        member.startswith("artifacts/") or "/artifacts/assurance/" in member for member in members
    )

    outside = tmp_path / "outside"
    outside.mkdir()
    program = """
import pathlib
import sys

wheel = pathlib.Path(sys.argv[1]).resolve()
sys.path.insert(0, str(wheel))

import nbadb
from nbadb.core.nba_api_competition_identity import (
    compile_competition_identity_requirements,
    pinned_competition_identity_authority,
)
from nbadb.core.nba_api_competition_identity_verifier import (
    verify_pinned_competition_identity_authority,
)

assert str(wheel) in str(nbadb.__file__)
requirements = compile_competition_identity_requirements()
authority = pinned_competition_identity_authority()
proof = verify_pinned_competition_identity_authority()
assert len(requirements) == 815
assert sum(item.executable for item in requirements) == 799
assert authority.identity_requirements == requirements
assert proof.finding_count == 0
assert proof.candidate_authority_sha256 == authority.authority_sha256
"""
    installed = subprocess.run(
        [sys.executable, "-I", "-c", program, str(wheel)],
        cwd=outside,
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert installed.returncode == 0, installed.stderr
