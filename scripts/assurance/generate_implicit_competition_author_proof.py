#!/usr/bin/env python3
"""Generate the provider-free author proof for current competition sources.

This command deliberately stops at author evidence.  It does not create a
review receipt, admit a current-source authority, import ``nba_api``, or make
network requests.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import stat
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Final, cast

from nbadb.contracts.implicit_competition_source_authority import (
    SOURCE_PATHS,
    ImplicitCompetitionSourceGenerationProofV1,
    generate_implicit_competition_generation_proof,
)

AUTHOR_TASK_ID: Final = "A1.3a-repair-12"
AUTHOR_ROLE: Final = "current-source-author"
PROVIDER_AUTHORITY_SHA256: Final = (
    "e5981c0223c99ecd4a483606781d1433cc23f22b26ec71c41a3b12b9ad827085"
)
AUTHORITY_SOURCE_SHA256: Final = "9b6914bf2995124b053e8280a4c726fcc69659c633cae055b4cccee1ade90d2c"
AUTHORITY_TEST_SHA256: Final = "4ef58b340582b911d107c41cc66517c890bc5218bbf5c904b2e1091740127302"

AUTHORITY_SOURCE_PATH: Final = "src/nbadb/contracts/implicit_competition_source_authority.py"
AUTHORITY_TEST_PATH: Final = "tests/unit/contracts/test_implicit_competition_source_authority.py"
PROVIDER_PROVENANCE_PATH: Final = "src/nbadb/core/nba_api_provenance.py"
GENERATOR_PATH: Final = "scripts/assurance/generate_implicit_competition_author_proof.py"
PROOF_FILENAME: Final = "generation-proof.json"
RECEIPT_FILENAME: Final = "author-receipt.json"
DEFAULT_OUTPUT_RELATIVE: Final = (
    "artifacts/assurance/complete-nba-api-sink/current-source-authority/author"
)

_FROZEN_INPUTS: Final = (
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_applicability/"
        "endpoint-support-evidence.json",
        "6db164143c588092acbd2c8497b068a770ff5a39501d1c05e28ef638b6fb6cfb",
    ),
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_applicability/"
        "source-review.json",
        "accdd459d72d58be7c8b83f9c17e2e2086c058f3112b7714f4f0ea33e588f589",
    ),
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/A1.2d.json",
        "acc12887aa5525a0ed9cc8047264c7efda3da92da745c5145138b4eb2a72e1bb",
    ),
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/"
        "implicit-competition-root-evidence.json",
        "ff848edf46d65bbfc5748e0b30a59d45e2be2a981a578fab73170089aa1c12ba",
    ),
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/implicit_competition/source-review.json",
        "d028c60baa78832991d83cbd977d0d555b32b6ebc38a281bb14e7592d76f37e8",
    ),
    (
        "src/nbadb/contracts/nba_api_implicit_competition_v1_11_4.json",
        "ed75be5cf84df8975cc32d50b51215648896b618584ed5b3b3aedcb8b6dc2111",
    ),
    (
        "src/nbadb/contracts/provenance/nba_api_v1_11_4/competition_identity/A1.3a-repair-11.json",
        "5f0cb0d04f9e46f412458489ba0d088193e18ba128f1739a2c03d87b4b5e57da",
    ),
)
AUTHORITY_INPUT_PATHS: Final = tuple(path for path, _sha256 in _FROZEN_INPUTS) + tuple(SOURCE_PATHS)
_OBSERVED_PROJECT_PATHS: Final = tuple(
    sorted(
        {
            *AUTHORITY_INPUT_PATHS,
            AUTHORITY_SOURCE_PATH,
            AUTHORITY_TEST_PATH,
            GENERATOR_PATH,
            PROVIDER_PROVENANCE_PATH,
        }
    )
)


class AuthorProofError(ValueError):
    """The author-only current-source proof could not be generated safely."""


@dataclass(frozen=True, slots=True)
class _ObservedFile:
    raw: bytes
    identity: tuple[int, int, int, int, int, int]


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AuthorProofError("author receipt is not canonical JSON") from exc


def _digest(value: object) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_identity(path: Path) -> tuple[int, int, int, int, int, int]:
    try:
        item = path.lstat()
    except OSError as exc:
        raise AuthorProofError(f"required author input is unreadable: {path.name}") from exc
    if stat.S_IFMT(item.st_mode) != stat.S_IFREG or path.is_symlink():
        raise AuthorProofError(f"required author input is not a regular file: {path.name}")
    return (
        item.st_dev,
        item.st_ino,
        stat.S_IFMT(item.st_mode),
        item.st_size,
        item.st_mtime_ns,
        item.st_ctime_ns,
    )


def _observe_file(path: Path) -> _ObservedFile:
    before = _file_identity(path)
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise AuthorProofError(f"required author input is unreadable: {path.name}") from exc
    after = _file_identity(path)
    if before != after or len(raw) != before[3]:
        raise AuthorProofError(f"required author input drifted while read: {path.name}")
    return _ObservedFile(raw=raw, identity=after)


def _observe_project(project_root: Path) -> dict[str, _ObservedFile]:
    return {
        relative: _observe_file(project_root / relative) for relative in _OBSERVED_PROJECT_PATHS
    }


def _require_unchanged_project(
    project_root: Path,
    opening: dict[str, _ObservedFile],
) -> None:
    closing = _observe_project(project_root)
    if closing != opening:
        changed = sorted(path for path in opening if opening[path] != closing[path])
        label = changed[0] if changed else "unknown"
        raise AuthorProofError(f"author source drifted during generation: {label}")


def _require_machinery_hashes(observed: dict[str, _ObservedFile]) -> None:
    expected = {
        AUTHORITY_SOURCE_PATH: AUTHORITY_SOURCE_SHA256,
        AUTHORITY_TEST_PATH: AUTHORITY_TEST_SHA256,
    }
    for path, sha256 in expected.items():
        if hashlib.sha256(observed[path].raw).hexdigest() != sha256:
            raise AuthorProofError(f"author machinery hash drifted: {path}")
    for path, sha256 in _FROZEN_INPUTS:
        if hashlib.sha256(observed[path].raw).hexdigest() != sha256:
            raise AuthorProofError(f"immutable authority input drifted: {path}")


def _literal_constants(source: bytes) -> dict[str, object]:
    try:
        tree = ast.parse(source.decode("utf-8"), filename=PROVIDER_PROVENANCE_PATH)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise AuthorProofError("provider provenance source is not valid UTF-8 Python") from exc
    required_functions = {
        "_attestation_digest",
        "expected_nba_api_provider_contract",
        "expected_nba_api_provider_evidence_receipt",
        "expected_nba_api_provider_authority",
    }
    functions = [node.name for node in tree.body if isinstance(node, ast.FunctionDef)]
    if any(functions.count(name) != 1 for name in required_functions):
        raise AuthorProofError("provider provenance function inventory drifted")
    constants: dict[str, object] = {}
    for node in tree.body:
        name: str | None = None
        value: ast.expr | None = None
        if (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
        ):
            name = node.targets[0].id
            value = node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            name = node.target.id
            value = node.value
        if name is None or value is None:
            continue
        try:
            literal = ast.literal_eval(value)
        except (TypeError, ValueError):
            continue
        if name in constants:
            raise AuthorProofError(f"provider provenance constant is duplicated: {name}")
        constants[name] = literal
    return constants


def _require_constant(constants: dict[str, object], name: str) -> object:
    if name not in constants:
        raise AuthorProofError(f"provider provenance constant is absent: {name}")
    return constants[name]


def _provider_authority_from_static_source(source: bytes) -> dict[str, object]:
    """Rederive the provider pin without importing or calling ``nba_api``."""

    values = _literal_constants(source)
    get = lambda name: _require_constant(values, name)  # noqa: E731
    contract: dict[str, object] = {
        "schema_version": 1,
        "provider": "nba_api",
        "distribution_name": get("NBA_API_DISTRIBUTION"),
        "distribution_version": get("NBA_API_VERSION"),
        "upstream_repository": get("NBA_API_UPSTREAM_REPOSITORY"),
        "upstream_tag": get("NBA_API_UPSTREAM_TAG"),
        "upstream_commit_sha": get("NBA_API_UPSTREAM_COMMIT"),
        "upstream_tree_sha": get("NBA_API_UPSTREAM_TREE"),
        "sdist_sha256": get("NBA_API_SDIST_SHA256"),
        "wheel_sha256": get("NBA_API_WHEEL_SHA256"),
        "source_inventory_file_count": get("NBA_API_INVENTORY_FILE_COUNT"),
        "source_inventory_sha256": get("NBA_API_TREE_INVENTORY_SHA256"),
        "installed_inventory_sha256": get("NBA_API_TREE_INVENTORY_SHA256"),
        "license_identifier": get("NBA_API_LICENSE_IDENTIFIER"),
        "license_sha256": get("NBA_API_LICENSE_SHA256"),
    }
    contract["attestation_sha256"] = _digest(contract)
    observation: dict[str, object] = {
        "installed_version": get("NBA_API_VERSION"),
        "lock_version": get("NBA_API_VERSION"),
        "locked_sdist_sha256": get("NBA_API_SDIST_SHA256"),
        "locked_wheel_sha256": get("NBA_API_WHEEL_SHA256"),
        "upstream_commit_sha": get("NBA_API_UPSTREAM_COMMIT"),
        "upstream_tag_commit_sha": get("NBA_API_UPSTREAM_COMMIT"),
        "upstream_tree_sha": get("NBA_API_UPSTREAM_TREE"),
        "upstream_tracked_clean": True,
        "source_inventory_file_count": get("NBA_API_INVENTORY_FILE_COUNT"),
        "source_inventory_sha256": get("NBA_API_TREE_INVENTORY_SHA256"),
        "installed_inventory_file_count": get("NBA_API_INVENTORY_FILE_COUNT"),
        "installed_inventory_sha256": get("NBA_API_TREE_INVENTORY_SHA256"),
        "source_installed_file_parity": True,
        "license_sha256": get("NBA_API_LICENSE_SHA256"),
    }
    evidence: dict[str, object] = {
        "schema_version": 1,
        "kind": "nbadb_nba_api_provider_evidence",
        "provider_contract_sha256": contract["attestation_sha256"],
        "observed": observation,
        "verified": True,
        "errors": [],
    }
    evidence["evidence_sha256"] = _digest(evidence)
    authority: dict[str, object] = {
        "schema_version": 1,
        "provider_contract": contract,
        "provider_evidence_sha256": evidence["evidence_sha256"],
        "runtime_endpoint_contract_count": get("NBA_API_RUNTIME_CONTRACT_COUNT"),
        "runtime_endpoint_contract_sha256": get("NBA_API_RUNTIME_CONTRACT_SHA256"),
        "live_endpoint_contract_count": get("NBA_API_LIVE_ENDPOINT_CONTRACT_COUNT"),
        "live_result_set_contract_count": get("NBA_API_LIVE_RESULT_SET_CONTRACT_COUNT"),
        "live_column_contract_count": get("NBA_API_LIVE_COLUMN_CONTRACT_COUNT"),
        "live_parsed_column_contract_count": get("NBA_API_LIVE_PARSED_COLUMN_CONTRACT_COUNT"),
        "live_contract_sha256": get("NBA_API_LIVE_CONTRACT_SHA256"),
        "static_dataset_contract_count": get("NBA_API_STATIC_DATASET_CONTRACT_COUNT"),
        "static_modeled_field_contract_count": get("NBA_API_STATIC_MODELED_FIELD_CONTRACT_COUNT"),
        "static_contract_sha256": get("NBA_API_STATIC_CONTRACT_SHA256"),
        "runtime_contract_payload_sha256": get("NBA_API_RUNTIME_CONTRACT_PAYLOAD_SHA256"),
        "docs_tools_bundle_sha256": get("NBA_API_UPSTREAM_CONTRACT_BUNDLE_SHA256"),
        "bronze_contract_sha256": get("NBA_API_BRONZE_CONTRACT_SHA256"),
        "metadata_ledger_sha256": get("NBA_API_METADATA_LEDGER_SHA256"),
    }
    authority["authority_sha256"] = _digest(authority)
    if authority["authority_sha256"] != PROVIDER_AUTHORITY_SHA256:
        raise AuthorProofError("provider-free authority rederivation differs from the frozen pin")
    return authority


def _generator_ast_evidence(source: bytes) -> dict[str, object]:
    """Describe only direct imports/calls visible in this generator's AST."""

    try:
        tree = ast.parse(source.decode("utf-8"), filename=GENERATOR_PATH)
    except (UnicodeDecodeError, SyntaxError) as exc:
        raise AuthorProofError("author generator is not valid UTF-8 Python") from exc
    imported_modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imported_modules.add(node.module)

    def call_name(node: ast.expr) -> str | None:
        parts: list[str] = []
        current = node
        while isinstance(current, ast.Attribute):
            parts.append(current.attr)
            current = current.value
        if not isinstance(current, ast.Name):
            return None
        parts.append(current.id)
        return ".".join(reversed(parts))

    call_names = sorted(
        {
            name
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            for name in [call_name(node.func)]
            if name is not None
        }
    )
    nba_api_imports = sorted(
        name for name in imported_modules if name == "nba_api" or name.startswith("nba_api.")
    )
    network_roots = ("aiohttp", "http.client", "httpx", "requests", "socket", "urllib")
    network_imports = sorted(
        name
        for name in imported_modules
        if any(name == root or name.startswith(f"{root}.") for root in network_roots)
    )
    provider_calls = sorted(
        name for name in call_names if name == "nba_api" or name.startswith("nba_api.")
    )
    network_calls = sorted(
        name
        for name in call_names
        if any(name == root or name.startswith(f"{root}.") for root in network_roots)
    )
    if nba_api_imports or network_imports or provider_calls or network_calls:
        raise AuthorProofError("author generator contains a direct provider or network operation")
    return {
        "direct_nba_api_imports": nba_api_imports,
        "direct_network_imports": network_imports,
        "direct_network_operation_calls": network_calls,
        "direct_provider_endpoint_calls": provider_calls,
        "generator_path": GENERATOR_PATH,
        "generator_sha256": hashlib.sha256(source).hexdigest(),
        "package_import_side_effects_attested_absent": False,
        "scope": "direct_generator_ast_only",
    }


def _copy_independent_roots(
    temporary_parent: Path,
    observed: dict[str, _ObservedFile],
) -> tuple[tuple[Path, Path, Path], dict[str, object]]:
    roots = cast(
        "tuple[Path, Path, Path]",
        tuple(temporary_parent / f"root-{index}" for index in range(1, 4)),
    )
    for root in roots:
        root.mkdir()
        for relative in AUTHORITY_INPUT_PATHS:
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as stream:
                stream.write(observed[relative].raw)
                stream.flush()
                os.fsync(stream.fileno())
    member_evidence: list[dict[str, object]] = []
    for relative in sorted(AUTHORITY_INPUT_PATHS):
        identities = {
            ((root / relative).stat().st_dev, (root / relative).stat().st_ino) for root in roots
        }
        if len(identities) != 3:
            raise AuthorProofError(f"temporary source copies share an inode: {relative}")
        raws = [(root / relative).read_bytes() for root in roots]
        if any(raw != observed[relative].raw for raw in raws):
            raise AuthorProofError(f"temporary source copy bytes drifted: {relative}")
        member_evidence.append(
            {
                "distinct_device_inode_count": 3,
                "path": relative,
                "sha256": hashlib.sha256(raws[0]).hexdigest(),
            }
        )
    resolved = tuple(root.resolve(strict=True) for root in roots)
    if len({(root.stat().st_dev, root.stat().st_ino) for root in resolved}) != 3:
        raise AuthorProofError("temporary source roots are not independently authenticated")
    if any(
        resolved[left] in resolved[right].parents or resolved[right] in resolved[left].parents
        for left in range(3)
        for right in range(left + 1, 3)
    ):
        raise AuthorProofError("temporary source roots are nested")
    evidence = {
        "all_corresponding_members_have_distinct_inodes": True,
        "member_count": len(member_evidence),
        "members": member_evidence,
        "root_count": 3,
        "roots_pairwise_distinct": True,
        "roots_pairwise_non_nested": True,
        "transient_paths_recorded": False,
    }
    return roots, evidence


def _source_input_inventory(observed: dict[str, _ObservedFile]) -> list[dict[str, object]]:
    return [
        {
            "byte_count": len(observed[path].raw),
            "path": path,
            "sha256": hashlib.sha256(observed[path].raw).hexdigest(),
        }
        for path in sorted(AUTHORITY_INPUT_PATHS)
    ]


def _author_receipt(
    *,
    proof: ImplicitCompetitionSourceGenerationProofV1,
    proof_bytes: bytes,
    provider_source: bytes,
    generator_source: bytes,
    input_inventory: list[dict[str, object]],
    root_independence: dict[str, object],
) -> bytes:
    proof_raw_sha256 = hashlib.sha256(proof_bytes).hexdigest()
    output_inventory = [
        {
            "binding": "receipt_body_sha256",
            "kind": "author_receipt",
            "path": RECEIPT_FILENAME,
        },
        {
            "byte_count": len(proof_bytes),
            "kind": "canonical_generation_proof",
            "path": PROOF_FILENAME,
            "sha256": proof_raw_sha256,
        },
    ]
    output_inventory.sort(key=lambda item: cast("str", item["path"]))
    candidate = proof.candidate
    body: dict[str, object] = {
        "author_role": AUTHOR_ROLE,
        "author_task_id": AUTHOR_TASK_ID,
        "candidate_sha256": candidate.candidate_sha256,
        "generation_candidate_bytes_sha256s": list(proof.generation_candidate_bytes_sha256s),
        "generation_policy_sha256": proof.generation_policy_sha256,
        "kind": "nbadb_implicit_competition_current_source_author_receipt",
        "machinery": [
            {"path": AUTHORITY_SOURCE_PATH, "sha256": AUTHORITY_SOURCE_SHA256},
            {"path": AUTHORITY_TEST_PATH, "sha256": AUTHORITY_TEST_SHA256},
        ],
        "output_inventory": output_inventory,
        "proof_raw_sha256": proof_raw_sha256,
        "proof_sha256": proof.proof_sha256,
        "provider_authority_sha256": PROVIDER_AUTHORITY_SHA256,
        "provider_validation": {
            "authority_sha256": PROVIDER_AUTHORITY_SHA256,
            "generator_execution_surface": _generator_ast_evidence(generator_source),
            "method": "provider_free_static_rederivation_from_nbadb_constants_v1",
            "provenance_path": PROVIDER_PROVENANCE_PATH,
            "provenance_sha256": hashlib.sha256(provider_source).hexdigest(),
        },
        "root_independence": root_independence,
        "schema_version": 1,
        "semantic_projection_sha256": candidate.semantic_projection_sha256,
        "source_input_inventory": input_inventory,
        "source_input_inventory_sha256": _digest(input_inventory),
        "source_inventory_sha256": candidate.source_inventory_sha256,
    }
    return _canonical_bytes({**body, "receipt_sha256": _digest(body)})


def author_bundle_bytes(project_root: Path | str) -> dict[str, bytes]:
    """Return deterministic author-only outputs after a three-root derivation."""

    root = Path(project_root).resolve(strict=True)
    observed = _observe_project(root)
    _require_machinery_hashes(observed)
    _provider_authority_from_static_source(observed[PROVIDER_PROVENANCE_PATH].raw)
    with tempfile.TemporaryDirectory(prefix="nbadb-current-source-author-") as raw_temporary:
        temporary_parent = Path(raw_temporary)
        roots, root_independence = _copy_independent_roots(temporary_parent, observed)
        proof = generate_implicit_competition_generation_proof(
            roots[0],
            roots[1],
            roots[2],
            provider_authority_sha256=PROVIDER_AUTHORITY_SHA256,
            author_task_id=AUTHOR_TASK_ID,
            author_role=AUTHOR_ROLE,
        )
        proof_bytes = proof.canonical_bytes
    input_inventory = _source_input_inventory(observed)
    receipt_bytes = _author_receipt(
        proof=proof,
        proof_bytes=proof_bytes,
        provider_source=observed[PROVIDER_PROVENANCE_PATH].raw,
        generator_source=observed[GENERATOR_PATH].raw,
        input_inventory=input_inventory,
        root_independence=root_independence,
    )
    _require_unchanged_project(root, observed)
    return {PROOF_FILENAME: proof_bytes, RECEIPT_FILENAME: receipt_bytes}


def _publish_outputs(output_dir: Path, outputs: dict[str, bytes], *, check: bool) -> None:
    if output_dir.exists() and (output_dir.is_symlink() or not output_dir.is_dir()):
        raise AuthorProofError("author output path is not a concrete directory")
    if not output_dir.exists():
        if check:
            raise AuthorProofError("author outputs are absent in check mode")
        output_dir.mkdir(parents=True)
    for name in sorted(outputs):
        path = output_dir / name
        if path.exists():
            if path.is_symlink() or not path.is_file() or path.read_bytes() != outputs[name]:
                raise AuthorProofError(f"existing author output differs: {name}")
        elif check:
            raise AuthorProofError(f"author output is absent in check mode: {name}")
    if check:
        return
    for name in sorted(outputs):
        path = output_dir / name
        if path.exists():
            continue
        try:
            with path.open("xb") as stream:
                stream.write(outputs[name])
                stream.flush()
                os.fsync(stream.fileno())
        except FileExistsError:
            if not path.is_file() or path.read_bytes() != outputs[name]:
                raise AuthorProofError(f"concurrent author output differs: {name}") from None


def generate_author_bundle(
    *,
    project_root: Path | str,
    output_dir: Path | str,
    check: bool = False,
) -> dict[str, str]:
    """Generate then create-or-exact-check the two author-only output files."""

    root = Path(project_root).resolve(strict=True)
    destination = Path(output_dir)
    if not destination.is_absolute():
        destination = root / destination
    outputs = author_bundle_bytes(root)
    _publish_outputs(destination, outputs, check=check)
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in sorted(outputs.items())}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path(__file__).resolve().parents[2],
    )
    parser.add_argument("--output-dir", type=Path, default=Path(DEFAULT_OUTPUT_RELATIVE))
    parser.add_argument(
        "--check",
        action="store_true",
        help="require both outputs to exist with the exact regenerated bytes",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        digests = generate_author_bundle(
            project_root=args.project_root,
            output_dir=args.output_dir,
            check=args.check,
        )
    except (AuthorProofError, OSError) as exc:
        print(f"author proof generation failed: {exc}", file=sys.stderr)
        return 1
    print(_canonical_bytes({"outputs": digests, "verified": True}).decode("utf-8"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
