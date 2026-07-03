from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import pkgutil
import re
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from nbadb.core.field_docs import resolved_field_description

ContractSource = Literal[
    "expected_data",
    "source_ast",
    "load_response",
    "manual_override",
    "endpoint_analysis_docs",
]
Confidence = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class NbaApiResultSetContract:
    runtime_class_name: str
    result_set_index: int
    result_set_name: str | None
    expected_columns: tuple[str, ...]
    source: ContractSource
    confidence: Confidence


@dataclass(frozen=True)
class NbaApiEndpointContract:
    runtime_class_name: str
    module_name: str
    endpoint_slug: str | None
    parameters: tuple[str, ...]
    required_parameters: tuple[str, ...]
    nullable_parameters: tuple[str, ...]
    result_sets: tuple[NbaApiResultSetContract, ...]
    deprecated: bool
    warnings: tuple[str, ...]
    parameter_patterns: tuple[tuple[str, str | None], ...] = ()
    endpoint_url: str | None = None
    valid_url: str | None = None
    last_validated_date: str | None = None
    source_path: str | None = None
    source_family: str | None = None
    status: str | None = None


_AUX_PARAMETER_NAMES = {"proxy", "headers", "timeout", "get_request"}


def _literal_expected_data(node: ast.AST) -> dict[str, list[str]] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError, MemoryError):
        return None
    if not isinstance(value, dict):
        return None

    expected_data: dict[str, list[str]] = {}
    for key, columns in value.items():
        if not isinstance(key, str) or not isinstance(columns, list):
            continue
        expected_data[key] = [column for column in columns if isinstance(column, str)]
    return expected_data


def _load_response_result_set_names(class_node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for node in class_node.body:
        if not isinstance(node, ast.FunctionDef) or node.name != "load_response":
            continue
        for child in ast.walk(node):
            if not isinstance(child, ast.Subscript):
                continue
            if not isinstance(child.value, ast.Name) or child.value.id != "data_sets":
                continue
            slice_node = child.slice
            if (
                isinstance(slice_node, ast.Constant)
                and isinstance(slice_node.value, str)
                and slice_node.value not in names
            ):
                names.append(slice_node.value)
    return names


def _source_contract(runtime_cls: type) -> tuple[dict[str, list[str]], tuple[str, ...]]:
    try:
        source_path = Path(inspect.getsourcefile(runtime_cls) or "")
    except TypeError:
        return {}, ()
    if not source_path.is_file():
        return {}, ()

    try:
        tree = ast.parse(source_path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return {}, ()

    for node in tree.body:
        if not isinstance(node, ast.ClassDef) or node.name != runtime_cls.__name__:
            continue
        expected_data: dict[str, list[str]] = {}
        for child in node.body:
            if not isinstance(child, ast.Assign):
                continue
            if not any(
                isinstance(target, ast.Name) and target.id == "expected_data"
                for target in child.targets
            ):
                continue
            expected_data = _literal_expected_data(child.value) or {}
            break
        return expected_data, tuple(_load_response_result_set_names(node))
    return {}, ()


def _endpoint_parameters(
    runtime_cls: type,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    try:
        signature = inspect.signature(runtime_cls.__init__)
    except (TypeError, ValueError):
        return (), (), ()

    parameters: list[str] = []
    required: list[str] = []
    nullable: list[str] = []
    for name, parameter in signature.parameters.items():
        if name == "self" or name in _AUX_PARAMETER_NAMES:
            continue
        parameters.append(name)
        if parameter.default is inspect.Parameter.empty:
            required.append(name)
        if parameter.default is None or name.endswith("_nullable"):
            nullable.append(name)
    return tuple(parameters), tuple(required), tuple(nullable)


def build_endpoint_contract(runtime_cls: type) -> NbaApiEndpointContract:
    runtime_class_name = runtime_cls.__name__
    runtime_expected = getattr(runtime_cls, "expected_data", None)
    expected_data: dict[str, list[str]] = {}
    source: ContractSource = "expected_data"
    confidence: Confidence = "high"

    if isinstance(runtime_expected, dict):
        for key, columns in runtime_expected.items():
            if isinstance(key, str) and isinstance(columns, list):
                expected_data[key] = [column for column in columns if isinstance(column, str)]

    source_expected, load_response_names = _source_contract(runtime_cls)
    warnings: list[str] = []
    if not expected_data and source_expected:
        expected_data = source_expected
        source = "source_ast"
        confidence = "medium"
    if load_response_names and expected_data:
        missing_from_expected = [name for name in load_response_names if name not in expected_data]
        if missing_from_expected:
            warnings.append(
                "load_response_result_sets_missing_expected_data:" + ",".join(missing_from_expected)
            )

    result_sets = tuple(
        NbaApiResultSetContract(
            runtime_class_name=runtime_class_name,
            result_set_index=index,
            result_set_name=name,
            expected_columns=tuple(columns),
            source=source,
            confidence=confidence,
        )
        for index, (name, columns) in enumerate(expected_data.items())
    )
    parameters, required_parameters, nullable_parameters = _endpoint_parameters(runtime_cls)
    doc = inspect.getdoc(runtime_cls) or ""
    return NbaApiEndpointContract(
        runtime_class_name=runtime_class_name,
        module_name=runtime_cls.__module__,
        endpoint_slug=getattr(runtime_cls, "endpoint", None),
        parameters=parameters,
        required_parameters=required_parameters,
        nullable_parameters=nullable_parameters,
        result_sets=result_sets,
        deprecated="deprecated" in doc.lower(),
        warnings=tuple(warnings),
    )


_JSON_BLOCK_RE = re.compile(r"```json\s*(.*?)\s*```", re.DOTALL)
_CODE_BLOCK_RE = re.compile(r"```(?P<language>[a-zA-Z0-9_-]*)\s*(?P<body>.*?)\s*```", re.DOTALL)
_MARKDOWN_LINK_RE = re.compile(r"^\[(?P<label>[^\]]+)\](?:\((?P<url>[^)]+)\))?$")
_LAST_VALIDATED_RE = re.compile(r"Last validated (?P<date>\d{4}-\d{2}-\d{2})")
_MARKDOWN_HEADING_RE = re.compile(r"^(?P<level>#{1,6})\s+(?P<title>.+?)\s*$")
_DATA_SET_HEADING_RE = re.compile(
    r"^####\s+(?P<label>.+?)(?:\s+`(?P<method_name>[^`]+)`)?\s*$",
    re.MULTILINE,
)
_STATIC_FUNCTION_RE = re.compile(
    r"^##\s+`(?P<function_name>[^`]+)`\((?P<parameters>[^)]*)\)",
    re.MULTILINE,
)
_STATIC_DICT_KEY_RE = re.compile(r"^\s*['\"](?P<key>[A-Za-z_][A-Za-z0-9_]*)['\"]\s*:", re.MULTILINE)
_BRONZE_IDENTIFIER_RE = re.compile(r"[^a-zA-Z0-9]+")


def _endpoint_docs_dir(root: Path) -> Path:
    if (root / "docs" / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "docs" / "nba_api" / "stats" / "endpoints"
    if (root / "nba_api" / "stats" / "endpoints").is_dir():
        return root / "nba_api" / "stats" / "endpoints"
    return root


def _live_endpoint_docs_dir(root: Path) -> Path | None:
    if (root / "docs" / "nba_api" / "live" / "endpoints").is_dir():
        return root / "docs" / "nba_api" / "live" / "endpoints"
    if (root / "nba_api" / "live" / "endpoints").is_dir():
        return root / "nba_api" / "live" / "endpoints"
    if len(root.parts) >= 3 and root.parts[-3:] == ("nba_api", "live", "endpoints"):
        return root
    if len(root.parts) >= 2 and root.parts[-2:] == ("live", "endpoints"):
        return root
    return None


def _endpoint_output_docs_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "endpoints_output",
        root / "nba_api" / "stats" / "endpoints_output",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _endpoint_response_fixtures_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "endpoints" / "responses",
        root / "nba_api" / "stats" / "endpoints" / "responses",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _stats_static_docs_dir(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "static",
        root / "nba_api" / "stats" / "static",
    ):
        if candidate.is_dir():
            return candidate
    return None


def _parameter_library_doc_path(root: Path) -> Path | None:
    for candidate in (
        root / "docs" / "nba_api" / "stats" / "library" / "parameters.md",
        root / "nba_api" / "stats" / "library" / "parameters.md",
    ):
        if candidate.is_file():
            return candidate
    return None


def _tools_dir(root: Path) -> Path | None:
    for candidate in (root / "tools", root.parent / "tools"):
        if candidate.is_dir():
            return candidate
    return None


def _json_loads_lenient(raw_json: str) -> dict[str, Any] | None:
    candidate = raw_json
    try:
        payload = json.loads(candidate)
    except json.JSONDecodeError:
        # Some upstream markdown historically contains regex strings such as
        # "^(\d{4}-\d{2})$". Treat those as intended JSON string backslashes
        # rather than dropping the whole contract.
        for _attempt in range(4):
            escaped = re.sub(r'(?<!\\)\\(?!["\\/bfnrtu])', r"\\\\", candidate)
            if escaped == candidate:
                return None
            candidate = escaped
            try:
                payload = json.loads(candidate)
            except json.JSONDecodeError:
                continue
            break
        else:
            return None
    return payload if isinstance(payload, dict) else None


def _json_payload_candidates(markdown: str) -> list[str]:
    candidates = [match.group(1) for match in _JSON_BLOCK_RE.finditer(markdown)]
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != "## JSON":
            continue
        block: list[str] = []
        started = False
        for candidate_line in lines[index + 1 :]:
            stripped = candidate_line.strip()
            if stripped.startswith("```"):
                break
            if stripped.startswith("#") and started:
                break
            if not started and not stripped:
                continue
            if candidate_line.startswith("    "):
                started = True
                block.append(candidate_line[4:])
                continue
            if candidate_line.startswith("\t"):
                started = True
                block.append(candidate_line[1:])
                continue
            if not started and stripped.startswith(("{", "[")):
                started = True
                block.append(candidate_line)
                continue
            if started and not stripped:
                block.append("")
                continue
            if started:
                break
        if block:
            candidate = "\n".join(block).strip()
            if candidate:
                candidates.append(candidate)
    return candidates


def _endpoint_analysis_payload(markdown: str) -> dict[str, Any] | None:
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is None:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("data_sets"), dict):
            return payload
    return None


def _markdown_url(markdown: str, label: str) -> str | None:
    lines = markdown.splitlines()
    for index, line in enumerate(lines):
        if line.strip() != f"##### {label}":
            continue
        for candidate_line in lines[index + 1 :]:
            candidate = candidate_line.strip()
            if not candidate:
                continue
            if candidate.startswith("##### "):
                break
            if not candidate.startswith(">"):
                continue
            candidate = candidate.lstrip(">").strip()
            match = _MARKDOWN_LINK_RE.match(candidate)
            if match is not None:
                return match.group("url") or match.group("label")
            return candidate.strip("<>")
    return None


def _last_validated_date(markdown: str, payload: dict[str, Any]) -> str | None:
    value = payload.get("last_validated_date")
    if isinstance(value, str) and value:
        return value
    match = _LAST_VALIDATED_RE.search(markdown)
    return match.group("date") if match else None


def _markdown_title(markdown: str) -> str | None:
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            return title or None
    return None


def _dedupe_columns(columns: list[str]) -> tuple[str, ...]:
    deduped: list[str] = []
    counts: dict[str, int] = {}
    for raw_column in columns:
        column = raw_column.strip()
        if not column:
            continue
        count = counts.get(column, 0) + 1
        counts[column] = count
        deduped.append(column if count == 1 else f"{column}_{count}")
    return tuple(deduped)


def _structured_data_set_columns(data_set: list[Any]) -> tuple[str, ...]:
    columns_item = next(
        (
            item
            for item in data_set
            if isinstance(item, dict)
            and _normalise_metadata_key(str(item.get("name") or "")) == "columns"
        ),
        None,
    )
    if not isinstance(columns_item, dict) or not isinstance(columns_item.get("columnNames"), list):
        return ()

    base_columns = [str(column) for column in columns_item["columnNames"] if str(column).strip()]
    if not base_columns:
        return ()

    grouping_items = [
        item
        for item in data_set
        if isinstance(item, dict)
        and _normalise_metadata_key(str(item.get("name") or "")) != "columns"
        and isinstance(item.get("columnNames"), list)
        and isinstance(item.get("columnSpan"), int)
        and item["columnSpan"] > 0
    ]
    if not grouping_items:
        return _dedupe_columns(base_columns)

    # nba_api's generated shot-location docs encode repeated metrics in the
    # `columns` row and category labels in the preceding grouped header row.
    primary_group = grouping_items[0]
    skip_count = int(primary_group.get("columnsToSkip") or 0)
    group_labels = [
        _bronze_identifier(str(label))
        for label in primary_group.get("columnNames", [])
        if _bronze_identifier(str(label))
    ]
    metric_span = int(primary_group["columnSpan"])
    output_columns = [column for column in base_columns[:skip_count] if column.strip()]
    metric_columns = base_columns[skip_count:]

    cursor = 0
    for group_label in group_labels:
        for _offset in range(metric_span):
            if cursor >= len(metric_columns):
                break
            metric = _bronze_identifier(metric_columns[cursor])
            cursor += 1
            if not metric:
                continue
            output_columns.append(f"{group_label}_{metric}")

    if cursor < len(metric_columns):
        output_columns.extend(metric_columns[cursor:])
    return _dedupe_columns(output_columns)


def _data_set_expected_columns(data_set: list[Any]) -> tuple[str, ...]:
    string_columns = [column for column in data_set if isinstance(column, str)]
    if string_columns:
        return _dedupe_columns(string_columns)
    if any(isinstance(column, dict) for column in data_set):
        return _structured_data_set_columns(data_set)
    return ()


def _contract_from_endpoint_analysis_doc(
    path: Path,
    payload: dict[str, Any],
    markdown: str = "",
    source_family: str = "stats",
    source_path: str | None = None,
) -> NbaApiEndpointContract | None:
    endpoint = payload.get("endpoint")
    data_sets = payload.get("data_sets")
    if not isinstance(endpoint, str) or not endpoint:
        endpoint = _markdown_title(markdown) or path.stem
    if not isinstance(data_sets, dict):
        return None

    parameter_patterns_payload = payload.get("parameter_patterns")
    result_sets: list[NbaApiResultSetContract] = []
    warnings: list[str] = []
    for name, columns in data_sets.items():
        if not isinstance(name, str) or not isinstance(columns, list):
            continue
        expected_columns = _data_set_expected_columns(columns)
        if not expected_columns:
            warnings.append(f"zero_column_result_set:{name}")
        result_sets.append(
            NbaApiResultSetContract(
                runtime_class_name=endpoint,
                result_set_index=len(result_sets),
                result_set_name=name,
                expected_columns=expected_columns,
                source="endpoint_analysis_docs",
                confidence="high",
            )
        )

    return NbaApiEndpointContract(
        runtime_class_name=endpoint,
        module_name=f"nba_api.docs.nba_api.stats.endpoints.{path.stem}",
        endpoint_slug=path.stem,
        parameters=tuple(str(value) for value in payload.get("parameters", []) if str(value)),
        required_parameters=tuple(
            str(value) for value in payload.get("required_parameters", []) if str(value)
        ),
        nullable_parameters=tuple(
            str(value) for value in payload.get("nullable_parameters", []) if str(value)
        ),
        result_sets=tuple(result_sets),
        deprecated=str(payload.get("status", "")).lower() == "deprecated",
        warnings=tuple(warnings),
        parameter_patterns=tuple(
            sorted(
                (str(key), str(value) if value is not None else None)
                for key, value in (
                    parameter_patterns_payload.items()
                    if isinstance(parameter_patterns_payload, dict)
                    else ()
                )
            )
        ),
        endpoint_url=_markdown_url(markdown, "Endpoint URL"),
        valid_url=_markdown_url(markdown, "Valid URL"),
        last_validated_date=_last_validated_date(markdown, payload),
        source_path=source_path or str(path),
        source_family=source_family,
        status=str(payload.get("status")) if payload.get("status") is not None else None,
    )


def _contract_from_live_endpoint_doc(
    path: Path,
    markdown: str,
    source_path: str | None = None,
) -> NbaApiEndpointContract | None:
    title = None
    for line in markdown.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break
    if not title:
        return None

    warnings: list[str] = []
    payload = None
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            break
    if payload is None:
        warnings.append("live_doc_json_payload_missing_or_invalid")

    return NbaApiEndpointContract(
        runtime_class_name=title,
        module_name=f"nba_api.docs.nba_api.live.endpoints.{path.stem}",
        endpoint_slug=path.stem,
        parameters=(),
        required_parameters=(),
        nullable_parameters=(),
        result_sets=(),
        deprecated=False,
        warnings=tuple(warnings),
        endpoint_url=_markdown_url(markdown, "Endpoint URL"),
        last_validated_date=_last_validated_date(markdown, payload or {}),
        source_path=source_path or str(path),
        source_family="live",
        status="success" if payload is not None else None,
    )


def _source_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return os.path.relpath(path, root)


def _discover_endpoint_analysis_doc_contracts_with_warnings(
    docs_root: Path | str | None,
) -> tuple[dict[str, NbaApiEndpointContract], list[dict[str, str]]]:
    if docs_root is None:
        return {}, []

    root = Path(docs_root)
    docs_dir = _endpoint_docs_dir(root)
    if not docs_dir.is_dir():
        return {}, [
            {
                "source_path": str(docs_dir),
                "reason": "stats_endpoint_docs_dir_missing",
            }
        ]

    contracts: dict[str, NbaApiEndpointContract] = {}
    warnings: list[dict[str, str]] = []
    for path in sorted(docs_dir.glob("*.md")):
        source_path = _source_path(root, path)
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError as exc:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": f"read_failed:{exc.__class__.__name__}",
                }
            )
            continue
        payload = _endpoint_analysis_payload(markdown)
        if payload is None:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": "json_payload_missing_or_invalid",
                }
            )
            continue
        contract = _contract_from_endpoint_analysis_doc(
            path,
            payload,
            markdown,
            source_path=source_path,
        )
        if contract is None:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": "contract_payload_missing_required_shape",
                }
            )
            continue
        contracts[contract.runtime_class_name] = contract
    return contracts, warnings


def discover_endpoint_analysis_doc_contracts(
    docs_root: Path | str | None,
) -> dict[str, NbaApiEndpointContract]:
    contracts, _warnings = _discover_endpoint_analysis_doc_contracts_with_warnings(docs_root)
    return contracts


def discover_live_endpoint_doc_contracts(
    docs_root: Path | str | None,
) -> dict[str, NbaApiEndpointContract]:
    if docs_root is None:
        return {}

    root = Path(docs_root)
    docs_dir = _live_endpoint_docs_dir(root)
    if docs_dir is None or not docs_dir.is_dir():
        return {}

    contracts: dict[str, NbaApiEndpointContract] = {}
    for path in sorted(docs_dir.glob("*.md")):
        try:
            markdown = path.read_text(encoding="utf-8")
        except OSError:
            continue
        source_path = _source_path(root, path)
        contract = _contract_from_live_endpoint_doc(path, markdown, source_path=source_path)
        if contract is not None:
            contracts[contract.runtime_class_name] = contract
    return contracts


def _git_sha(root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    sha = result.stdout.strip()
    return sha or None


def _relative_paths(root: Path, directory: Path | None, pattern: str) -> list[str]:
    if directory is None or not directory.is_dir():
        return []
    return sorted(
        os.path.relpath(path, root) for path in directory.rglob(pattern) if path.is_file()
    )


def _source_file_digests(root: Path, relative_paths: list[str]) -> dict[str, str]:
    digests: dict[str, str] = {}
    for relative_path in relative_paths:
        path = root / relative_path
        try:
            digests[relative_path] = hashlib.sha256(path.read_bytes()).hexdigest()
        except OSError:
            digests[relative_path] = "read_failed"
    return digests


def _clean_markdown_cell(value: str) -> str:
    cleaned = value.strip()
    cleaned = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", cleaned)
    cleaned = cleaned.replace("_**", "").replace("**_", "")
    cleaned = cleaned.strip("`*_ ")
    return cleaned


def _normalise_metadata_key(value: str) -> str:
    cleaned = _clean_markdown_cell(value).lower()
    cleaned = re.sub(r"[^a-z0-9]+", "_", cleaned).strip("_")
    return cleaned


def _split_markdown_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]

    cells: list[str] = []
    current: list[str] = []
    in_code = False
    for char in stripped:
        if char == "`":
            in_code = not in_code
            current.append(char)
            continue
        if char == "|" and not in_code:
            cells.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    cells.append("".join(current).strip())
    return cells


def _is_markdown_separator(cells: list[str]) -> bool:
    return bool(cells) and all(re.fullmatch(r":?-{2,}:?", cell.strip()) for cell in cells)


def _markdown_tables(markdown: str) -> list[dict[str, Any]]:
    lines = markdown.splitlines()
    tables: list[dict[str, Any]] = []
    index = 0
    while index + 1 < len(lines):
        if "|" not in lines[index] or "|" not in lines[index + 1]:
            index += 1
            continue
        headers = _split_markdown_row(lines[index])
        separator = _split_markdown_row(lines[index + 1])
        if not _is_markdown_separator(separator):
            index += 1
            continue

        header_keys = [_normalise_metadata_key(header) for header in headers]
        rows: list[dict[str, str]] = []
        row_index = index + 2
        while row_index < len(lines) and "|" in lines[row_index]:
            if lines[row_index].lstrip().startswith("#"):
                break
            cells = _split_markdown_row(lines[row_index])
            if not any(cell.strip() for cell in cells):
                break
            if len(cells) < len(header_keys):
                cells = [*cells, *([""] * (len(header_keys) - len(cells)))]
            if len(cells) > len(header_keys):
                cells = [*cells[: len(header_keys) - 1], " | ".join(cells[len(header_keys) - 1 :])]
            rows.append(
                {
                    header_keys[cell_index]: _clean_markdown_cell(cell)
                    for cell_index, cell in enumerate(cells[: len(header_keys)])
                    if header_keys[cell_index]
                }
            )
            row_index += 1

        tables.append(
            {
                "headers": [_clean_markdown_cell(header) for header in headers],
                "header_keys": header_keys,
                "rows": rows,
                "start_line": index + 1,
            }
        )
        index = row_index
    return tables


def _markdown_parameter_rows(markdown: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for table in _markdown_tables(markdown):
        header_keys = set(table["header_keys"])
        if not ({"api_parameter_name", "python_parameter_variable"} <= header_keys) and not (
            "parameter" in header_keys or "parameter_name" in header_keys
        ):
            continue
        for row in table["rows"]:
            rows.append(
                {
                    "api_parameter_name": row.get("api_parameter_name")
                    or row.get("parameter")
                    or row.get("parameter_name"),
                    "python_parameter_variable": row.get("python_parameter_variable"),
                    "pattern": row.get("pattern"),
                    "required": (row.get("required") or "").upper() == "Y",
                    "nullable": (row.get("nullable") or "").upper() == "Y",
                    "source_line": table["start_line"],
                }
            )
    return rows


def _markdown_data_set_headings(markdown: str) -> dict[str, dict[str, str | None]]:
    headings: dict[str, dict[str, str | None]] = {}
    for match in _DATA_SET_HEADING_RE.finditer(markdown):
        label = _clean_markdown_cell(match.group("label"))
        if not label or label.lower().startswith("class "):
            continue
        headings[label] = {
            "result_set_name": label,
            "method_name": match.group("method_name"),
        }
    return headings


def _markdown_data_set_field_lists(markdown: str) -> dict[str, list[str]]:
    matches = list(_DATA_SET_HEADING_RE.finditer(markdown))
    fields_by_dataset: dict[str, list[str]] = {}
    heading_matches = list(_MARKDOWN_HEADING_RE.finditer(markdown))
    for index, match in enumerate(matches):
        label = _clean_markdown_cell(match.group("label"))
        if not label:
            continue
        start = match.end()
        end_candidates = [
            heading.start()
            for heading in heading_matches
            if heading.start() > start and len(heading.group("level")) <= 2
        ]
        if index + 1 < len(matches):
            end_candidates.append(matches[index + 1].start())
        end = min(end_candidates) if end_candidates else len(markdown)
        section = markdown[start:end]
        columns: list[str] = []
        for code_block in _CODE_BLOCK_RE.finditer(section):
            body = code_block.group("body")
            columns.extend(re.findall(r'"([^"]+)"(?:\[\])?', body))
        if columns:
            fields_by_dataset[label] = list(dict.fromkeys(columns))
    return fields_by_dataset


def _first_json_payload(markdown: str) -> dict[str, Any] | None:
    for candidate in _json_payload_candidates(markdown):
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            return payload
    return None


def _first_json_payload_with_warning(markdown: str) -> tuple[dict[str, Any] | None, str | None]:
    candidates = _json_payload_candidates(markdown)
    if not candidates:
        return None, "live_doc_json_payload_missing"
    for candidate in candidates:
        payload = _json_loads_lenient(candidate)
        if payload is not None:
            return payload, None
    return None, "live_doc_json_payload_invalid"


def _parse_stats_endpoint_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    payload = _endpoint_analysis_payload(markdown)
    if payload is None:
        return None
    contract = _contract_from_endpoint_analysis_doc(
        path,
        payload,
        markdown,
        source_path=_source_path(root, path),
    )
    if contract is None:
        return None

    heading_metadata = _markdown_data_set_headings(markdown)
    result_sets: list[dict[str, Any]] = []
    for result_set in contract.result_sets:
        result_set_name = result_set.result_set_name or f"result_set_{result_set.result_set_index}"
        heading = heading_metadata.get(result_set_name, {})
        columns: list[dict[str, Any]] = []
        for ordinal, column in enumerate(result_set.expected_columns):
            description, description_source = resolved_field_description(
                None,
                column,
                endpoint=contract.runtime_class_name,
                result_set=result_set_name,
            )
            columns.append(
                {
                    "name": column,
                    "ordinal": ordinal,
                    "description": description,
                    "description_source": description_source,
                    "source": "endpoint_analysis_data_sets",
                }
            )
        result_sets.append(
            {
                "result_set_name": result_set_name,
                "result_set_index": result_set.result_set_index,
                "method_name": heading.get("method_name"),
                "column_count": len(result_set.expected_columns),
                "columns": columns,
            }
        )

    return {
        "endpoint": contract.runtime_class_name,
        "endpoint_slug": contract.endpoint_slug,
        "source_path": contract.source_path,
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "endpoint_url": contract.endpoint_url,
        "valid_url": contract.valid_url,
        "last_validated_date": contract.last_validated_date,
        "status": contract.status,
        "parameters": _markdown_parameter_rows(markdown),
        "parameter_patterns": dict(contract.parameter_patterns),
        "result_sets": result_sets,
    }


def _parse_live_endpoint_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    title = _markdown_title(markdown)
    if not title:
        return None

    about_fields: list[dict[str, Any]] = []
    for table in _markdown_tables(markdown):
        header_keys = set(table["header_keys"])
        if "key" not in header_keys or not ({"description", "class"} & header_keys):
            continue
        for row in table["rows"]:
            key = row.get("key")
            if not key:
                continue
            about_fields.append(
                {
                    "key": key,
                    "class": row.get("class"),
                    "type": row.get("type"),
                    "sample": row.get("sample") or row.get("example"),
                    "description": row.get("description"),
                    "always_present": (row.get("alwayspresent") or row.get("always_present")),
                    "source_line": table["start_line"],
                }
            )

    payload, payload_warning = _first_json_payload_with_warning(markdown)
    return {
        "endpoint": title,
        "endpoint_slug": path.stem,
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "endpoint_url": _markdown_url(markdown, "Endpoint URL"),
        "valid_url": _markdown_url(markdown, "Valid URL"),
        "last_validated_date": _last_validated_date(markdown, payload or {}),
        "parameters": _markdown_parameter_rows(markdown),
        "about_fields": about_fields,
        "json_payload_keys": sorted(payload) if isinstance(payload, dict) else [],
        "warnings": (
            [{"source_path": _source_path(root, path), "reason": payload_warning}]
            if payload_warning
            else []
        ),
    }


def _runtime_parameter_rows(runtime_cls: type) -> list[dict[str, Any]]:
    try:
        signature = inspect.signature(runtime_cls)
    except (TypeError, ValueError):
        return []

    rows: list[dict[str, Any]] = []
    for parameter in signature.parameters.values():
        if parameter.name in _AUX_PARAMETER_NAMES:
            continue
        rows.append(
            {
                "api_parameter_name": parameter.name,
                "python_parameter_variable": parameter.name,
                "pattern": None,
                "required": parameter.default is inspect.Parameter.empty,
                "nullable": parameter.default is None,
                "source_line": None,
                "source": "runtime_signature",
            }
        )
    return rows


def _sample_value_type(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int) and not isinstance(value, bool):
        return "integer"
    if isinstance(value, float):
        return "number"
    if isinstance(value, str):
        return "string"
    if isinstance(value, list):
        return "array"
    if isinstance(value, dict):
        return "object"
    return type(value).__name__


def _live_json_path(path: tuple[str, ...], field_name: str | None = None) -> str:
    parts = [*path]
    if field_name is not None:
        parts.append(field_name)
    return "$" + ("." + ".".join(parts) if parts else "")


def _live_result_set_name(path: tuple[str, ...]) -> str:
    return _bronze_identifier(*path) or "root"


def _live_shape_field(
    field_name: str, value: Any, path: tuple[str, ...], ordinal: int
) -> dict[str, Any]:
    return {
        "key": field_name,
        "name": field_name,
        "ordinal": ordinal,
        "json_path": _live_json_path(path, field_name),
        "sample_type": _sample_value_type(value),
        "description": None,
        "nullable": True,
        "source": "nba_api_live_expected_data",
    }


def _flatten_live_expected_data_node(
    node: Any,
    *,
    path: tuple[str, ...],
    tables: list[dict[str, Any]],
    skipped: list[dict[str, Any]],
    data_grain: str,
) -> None:
    if isinstance(node, dict):
        field_items = [
            (key, value)
            for key, value in node.items()
            if isinstance(key, str)
            and (not isinstance(value, dict | list) or (isinstance(value, list) and not value))
        ]
        if field_items:
            fields = [
                _live_shape_field(key, value, path, ordinal)
                for ordinal, (key, value) in enumerate(field_items)
            ]
            tables.append(
                {
                    "result_set_name": _live_result_set_name(path),
                    "method_name": _live_result_set_name(path),
                    "json_path": _live_json_path(path),
                    "data_grain": data_grain,
                    "fields": fields,
                    "field_count": len(fields),
                    "source": "runtime_live_expected_data",
                }
            )
        for key, value in node.items():
            if (
                not isinstance(key, str)
                or not isinstance(value, dict | list)
                or (isinstance(value, list) and not value)
            ):
                continue
            _flatten_live_expected_data_node(
                value,
                path=(*path, key),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array"
                if isinstance(value, list)
                else "nba_api_live_json_object",
            )
        if not field_items and not any(isinstance(value, dict | list) for value in node.values()):
            skipped.append(
                {
                    "json_path": _live_json_path(path),
                    "reason": "empty_object",
                    "source": "runtime_live_expected_data",
                }
            )
        return

    if isinstance(node, list):
        if not node:
            skipped.append(
                {
                    "json_path": _live_json_path(path),
                    "reason": "empty_array",
                    "source": "runtime_live_expected_data",
                }
            )
            return
        exemplar = next((item for item in node if item is not None), node[0])
        if isinstance(exemplar, dict):
            _flatten_live_expected_data_node(
                exemplar,
                path=path,
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array",
            )
            return
        if isinstance(exemplar, list):
            _flatten_live_expected_data_node(
                exemplar,
                path=(*path, "item"),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array",
            )
            return
        tables.append(
            {
                "result_set_name": _live_result_set_name(path),
                "method_name": _live_result_set_name(path),
                "json_path": _live_json_path(path),
                "data_grain": "nba_api_live_json_array",
                "fields": [_live_shape_field("value", exemplar, path, 0)],
                "field_count": 1,
                "source": "runtime_live_expected_data",
            }
        )
        return

    skipped.append(
        {
            "json_path": _live_json_path(path),
            "reason": "scalar_root",
            "sample_type": _sample_value_type(node),
            "source": "runtime_live_expected_data",
        }
    )


def _flatten_live_expected_data(
    expected_data: Any,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tables: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []
    if isinstance(expected_data, dict):
        for key, value in expected_data.items():
            if not isinstance(key, str):
                continue
            _flatten_live_expected_data_node(
                value,
                path=(key,),
                tables=tables,
                skipped=skipped,
                data_grain="nba_api_live_json_array"
                if isinstance(value, list)
                else "nba_api_live_json_object",
            )
    else:
        _flatten_live_expected_data_node(
            expected_data,
            path=("root",),
            tables=tables,
            skipped=skipped,
            data_grain="nba_api_live_json_object",
        )

    deduped_tables: dict[str, dict[str, Any]] = {}
    for table in tables:
        if table["field_count"] <= 0:
            skipped.append(
                {
                    "json_path": table.get("json_path"),
                    "reason": "zero_column_table_suppressed",
                    "result_set_name": table.get("result_set_name"),
                    "source": "runtime_live_expected_data",
                }
            )
            continue
        deduped_tables[table["result_set_name"]] = table
    return [deduped_tables[key] for key in sorted(deduped_tables)], skipped


def _discover_live_runtime_endpoint_classes() -> dict[str, type]:
    try:
        from nba_api.live.nba import endpoints
    except Exception:
        return {}

    package_path = getattr(endpoints, "__path__", None)
    if package_path is None:
        return {}

    classes: dict[str, type] = {}
    for module_info in pkgutil.iter_modules(package_path):
        try:
            module = importlib.import_module(f"{endpoints.__name__}.{module_info.name}")
        except Exception:
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if name.startswith("_") or name == "DataSet":
                continue
            if not hasattr(obj, "expected_data"):
                continue
            classes[name] = obj
    return classes


def _live_runtime_metadata_from_class(
    runtime_cls: type,
    supplement: dict[str, Any] | None = None,
) -> dict[str, Any]:
    endpoint_slug = runtime_cls.__module__.rsplit(".", 1)[-1]
    expected_data = getattr(runtime_cls, "expected_data", {})
    data_sets, skipped_shapes = _flatten_live_expected_data(expected_data)
    source_path = f"{runtime_cls.__module__}.{runtime_cls.__name__}"
    source_file = inspect.getsourcefile(runtime_cls)
    source_sha256 = None
    if source_file:
        try:
            source_sha256 = hashlib.sha256(Path(source_file).read_bytes()).hexdigest()
        except OSError:
            source_sha256 = None
    supplement = supplement or {}
    about_fields_by_key = {
        _normalise_metadata_key(str(field.get("key"))): field
        for field in supplement.get("about_fields", [])
        if isinstance(field, dict) and field.get("key")
    }
    for data_set in data_sets:
        result_set_name = data_set.get("result_set_name")
        for field in data_set.get("fields", []):
            key = str(field.get("key") or field.get("name") or "")
            about_field = about_fields_by_key.get(_normalise_metadata_key(key))
            explicit_description = (
                about_field.get("description") if isinstance(about_field, dict) else None
            )
            description, description_source = resolved_field_description(
                explicit_description,
                key,
                endpoint=runtime_cls.__name__,
                result_set=str(result_set_name) if result_set_name else None,
                json_path=field.get("json_path"),
            )
            field["description"] = description
            field["description_source"] = (
                "live_docs_about_fields" if description_source == "metadata" else description_source
            )
    return {
        "endpoint": runtime_cls.__name__,
        "endpoint_slug": endpoint_slug,
        "runtime_module": runtime_cls.__module__,
        "source_path": source_path,
        "source_sha256": source_sha256,
        "source": "runtime_live_expected_data",
        "endpoint_url": supplement.get("endpoint_url")
        or getattr(runtime_cls, "endpoint_url", None),
        "valid_url": supplement.get("valid_url"),
        "last_validated_date": supplement.get("last_validated_date"),
        "parameters": _runtime_parameter_rows(runtime_cls),
        "data_sets": data_sets,
        "skipped_shapes": skipped_shapes,
        "expected_data_root_keys": sorted(expected_data) if isinstance(expected_data, dict) else [],
        "docs_supplement": {
            key: supplement.get(key)
            for key in (
                "source_path",
                "source_sha256",
                "json_payload_keys",
                "about_fields",
                "parameters",
            )
            if supplement.get(key) not in (None, [], {})
        },
    }


def discover_runtime_live_endpoint_contracts(
    supplements_by_slug: dict[str, dict[str, Any]] | None = None,
) -> dict[str, NbaApiEndpointContract]:
    supplements_by_slug = supplements_by_slug or {}
    contracts: dict[str, NbaApiEndpointContract] = {}
    for name, runtime_cls in sorted(_discover_live_runtime_endpoint_classes().items()):
        metadata = _live_runtime_metadata_from_class(
            runtime_cls,
            supplements_by_slug.get(runtime_cls.__module__.rsplit(".", 1)[-1]),
        )
        result_sets = [
            NbaApiResultSetContract(
                runtime_class_name=name,
                result_set_index=index,
                result_set_name=data_set["result_set_name"],
                expected_columns=tuple(field["key"] for field in data_set["fields"]),
                source="expected_data",
                confidence="high",
            )
            for index, data_set in enumerate(metadata["data_sets"])
        ]
        contracts[name] = NbaApiEndpointContract(
            runtime_class_name=name,
            module_name=runtime_cls.__module__,
            endpoint_slug=metadata["endpoint_slug"],
            parameters=tuple(row["python_parameter_variable"] for row in metadata["parameters"]),
            required_parameters=tuple(
                row["python_parameter_variable"]
                for row in metadata["parameters"]
                if row["required"]
            ),
            nullable_parameters=tuple(
                row["python_parameter_variable"]
                for row in metadata["parameters"]
                if row["nullable"]
            ),
            result_sets=tuple(result_sets),
            deprecated=False,
            warnings=(),
            endpoint_url=metadata["endpoint_url"],
            valid_url=metadata["valid_url"],
            last_validated_date=metadata["last_validated_date"],
            source_path=metadata["source_path"],
            source_family="live",
            status="success",
        )
    return contracts


def _static_doc_sections(markdown: str) -> list[dict[str, Any]]:
    matches = list(_STATIC_FUNCTION_RE.finditer(markdown))
    sections: list[dict[str, Any]] = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(markdown)
        body = markdown[start:end].strip()
        description_lines = [
            line.strip()
            for line in body.splitlines()
            if line.strip() and not line.strip().startswith("```")
        ]
        sections.append(
            {
                "function_name": match.group("function_name"),
                "parameters": [
                    _clean_markdown_cell(parameter)
                    for parameter in match.group("parameters").split(",")
                    if parameter.strip()
                ],
                "description": " ".join(description_lines).strip() or None,
            }
        )
    return sections


def _parse_static_doc_metadata(root: Path, path: Path, markdown: str) -> dict[str, Any] | None:
    title = _markdown_title(markdown) or path.stem
    dictionary_shapes: list[dict[str, Any]] = []
    for code_block in _CODE_BLOCK_RE.finditer(markdown):
        if code_block.group("language").lower() != "python":
            continue
        keys = list(dict.fromkeys(_STATIC_DICT_KEY_RE.findall(code_block.group("body"))))
        if keys:
            dictionary_shapes.append({"keys": keys, "key_count": len(keys)})

    return {
        "module": title.removesuffix(".py"),
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "functions": _static_doc_sections(markdown),
        "dictionary_shapes": dictionary_shapes,
    }


def _markdown_h2_sections(markdown: str) -> list[dict[str, str]]:
    lines = markdown.splitlines()
    sections: list[dict[str, str]] = []
    current_title: str | None = None
    current_lines: list[str] = []
    for line in lines:
        match = _MARKDOWN_HEADING_RE.match(line)
        if match is not None and len(match.group("level")) == 2:
            if current_title is not None:
                sections.append({"title": current_title, "body": "\n".join(current_lines)})
            current_title = _clean_markdown_cell(match.group("title"))
            current_lines = []
            continue
        if current_title is not None:
            current_lines.append(line)
    if current_title is not None:
        sections.append({"title": current_title, "body": "\n".join(current_lines)})
    return sections


def _parse_parameter_library(root: Path, path: Path | None) -> dict[str, Any]:
    if path is None:
        return {
            "source_path": None,
            "source_sha256": None,
            "parameters": [],
            "missing": True,
        }

    markdown = path.read_text(encoding="utf-8")
    parameters: list[dict[str, Any]] = []
    for section in _markdown_h2_sections(markdown):
        body = section["body"]
        no_available_info = "No available information." in body
        classes = re.findall(r"####\s+[Cc]lass\s+`([^`]+)`", body)
        patterns = [
            _clean_markdown_cell(match.group(1))
            for match in re.finditer(r"^\s*-\s+(.+?)\s*$", body, re.MULTILINE)
        ]
        values: list[dict[str, Any]] = []
        for table in _markdown_tables(body):
            if {"variable_name", "value"} <= set(table["header_keys"]):
                values.extend(
                    {
                        "variable_name": row.get("variable_name", ""),
                        "value": row.get("value", ""),
                        "is_default": "default" in (row.get("variable_name", "").lower()),
                    }
                    for row in table["rows"]
                )
        parameters.append(
            {
                "parameter_name": section["title"],
                "classes": classes,
                "patterns": patterns,
                "values": values,
                "no_available_information": no_available_info,
            }
        )

    return {
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "parameters": parameters,
        "missing": False,
    }


def _infer_sample_type(values: list[str]) -> str:
    cleaned = [value for value in values if value not in ("", "null", "None", "nan", "-")]
    if not cleaned:
        return "unknown"
    if all(re.fullmatch(r"-?\d+", value) for value in cleaned):
        return "integer"
    if all(re.fullmatch(r"-?(?:\d+\.\d+|\d+)", value) for value in cleaned):
        return "number"
    return "string"


def _parse_endpoint_output_sample(root: Path, path: Path, markdown: str) -> dict[str, Any]:
    tables = _markdown_tables(markdown)
    columns: list[dict[str, Any]] = []
    sample_rows: list[dict[str, str]] = []
    if tables:
        first_table = tables[0]
        sample_rows = first_table["rows"][:5]
        for header_key, header in zip(
            first_table["header_keys"], first_table["headers"], strict=False
        ):
            columns.append(
                {
                    "name": header,
                    "sample_type": _infer_sample_type(
                        [row.get(header_key, "") for row in first_table["rows"]]
                    ),
                }
            )
    return {
        "endpoint_slug": path.name.removesuffix("_output.md"),
        "source_path": _source_path(root, path),
        "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "columns": columns,
        "sample_rows": sample_rows,
        "sample_row_count": len(sample_rows),
    }


def _ast_key_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        parent = _ast_key_name(node.value)
        return f"{parent}.{node.attr}" if parent else node.attr
    return None


def _ast_sequence_names(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.List | ast.Tuple | ast.Set):
        return []
    names: list[str] = []
    for element in node.elts:
        name = _ast_key_name(element)
        if name is not None:
            names.append(name)
    return names


def _ast_mapping_keys(node: ast.AST) -> list[str]:
    if not isinstance(node, ast.Dict):
        return []
    keys: list[str] = []
    for key in node.keys:
        if key is None:
            continue
        name = _ast_key_name(key)
        if name is not None:
            keys.append(name)
    return keys


def _parse_tools_metadata(root: Path, tools_dir: Path | None) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    endpoint_list: list[str] = []
    parameter_variation_keys: list[str] = []
    parameter_map_keys: list[str] = []
    warnings: list[dict[str, str]] = []

    if tools_dir is None or not tools_dir.is_dir():
        return {
            "files": [],
            "endpoint_list": [],
            "parameter_variation_keys": [],
            "parameter_map_keys": [],
            "warnings": [{"source_path": "tools", "reason": "tools_dir_missing"}],
        }

    for path in sorted(tools_dir.rglob("*.py")):
        source_path = _source_path(root, path)
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:
            warnings.append(
                {
                    "source_path": source_path,
                    "reason": f"parse_failed:{type(exc).__name__}",
                }
            )
            continue
        assignments: dict[str, list[str]] = {}
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            names = [target.id for target in node.targets if isinstance(target, ast.Name)]
            for name in names:
                if name == "endpoint_list":
                    values = _ast_sequence_names(node.value)
                    assignments[name] = values
                    endpoint_list.extend(values)
                elif name == "parameter_variations":
                    values = _ast_mapping_keys(node.value)
                    assignments[name] = values
                    parameter_variation_keys.extend(values)
                elif name == "parameter_map":
                    values = _ast_mapping_keys(node.value)
                    assignments[name] = values
                    parameter_map_keys.extend(values)
        files.append(
            {
                "source_path": source_path,
                "source_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "assignments": assignments,
            }
        )

    return {
        "files": files,
        "endpoint_list": sorted(set(endpoint_list)),
        "parameter_variation_keys": sorted(set(parameter_variation_keys)),
        "parameter_map_keys": sorted(set(parameter_map_keys)),
        "warnings": warnings,
    }


def _endpoint_reconciliation_key(value: object) -> str:
    return _normalise_metadata_key(str(value))


_KNOWN_ZERO_COLUMN_RESULT_SETS: dict[tuple[str, str], tuple[str, str]] = {
    (
        "DefenseHub",
        "DefenseHubStat10",
    ): (
        "known_upstream_empty_result_set",
        "nba_api docs expose this conditional DefenseHub result set with no columns.",
    ),
    (
        "ScoreboardV2",
        "WinProbability",
    ): (
        "deprecated_upstream_empty_result_set",
        "nba_api v1.11.4 release notes deprecate ScoreboardV2; this conditional "
        "result set is documented without columns.",
    ),
}


def _known_zero_column_classification(
    endpoint_name: str,
    result_set_name: str,
) -> tuple[str, str, bool]:
    classification = _KNOWN_ZERO_COLUMN_RESULT_SETS.get((endpoint_name, result_set_name))
    if classification is None:
        return (
            "unclassified_zero_column_result_set",
            "No local evidence classifies this upstream zero-column result set.",
            True,
        )
    reason, detail = classification
    return reason, detail, False


def _reconciliation_row(
    *,
    endpoint: str,
    status: str,
    source: str,
    classification: str,
    reason: str,
    blocking: bool = False,
    matched_docs_endpoint: str | None = None,
    matched_tools_endpoint: str | None = None,
) -> dict[str, Any]:
    return {
        "endpoint": endpoint,
        "status": status,
        "source": source,
        "classification": classification,
        "classification_reason": reason,
        "blocking": blocking,
        "matched_docs_endpoint": matched_docs_endpoint,
        "matched_tools_endpoint": matched_tools_endpoint,
    }


def _reconcile_tools_metadata(
    tools_metadata: dict[str, Any],
    stats_endpoint_metadata: list[dict[str, Any]],
) -> dict[str, Any]:
    docs_by_key = {
        _endpoint_reconciliation_key(endpoint.get("endpoint")): str(endpoint.get("endpoint"))
        for endpoint in stats_endpoint_metadata
        if endpoint.get("endpoint")
    }
    tools_by_key = {
        _endpoint_reconciliation_key(endpoint): str(endpoint)
        for endpoint in tools_metadata.get("endpoint_list", [])
        if endpoint
    }
    docs_keys = set(docs_by_key)
    tools_keys = set(tools_by_key)
    tools_missing_docs = [tools_by_key[key] for key in sorted(tools_keys - docs_keys)]
    docs_missing_tools = [docs_by_key[key] for key in sorted(docs_keys - tools_keys)]
    rows = [
        _reconciliation_row(
            endpoint=tools_by_key[key],
            status="tools_endpoint_missing_docs",
            source="tools_endpoint_list",
            classification="tools_inventory_endpoint_without_parsed_doc",
            reason=(
                "tools/stats/library/mapping.py is an upstream endpoint inventory, "
                "but the current docs tree does not expose a parsed endpoint contract for this key."
            ),
            matched_tools_endpoint=tools_by_key[key],
        )
        for key in sorted(tools_keys - docs_keys)
    ]
    rows.extend(
        _reconciliation_row(
            endpoint=docs_by_key[key],
            status="docs_endpoint_missing_tools",
            source="stats_endpoint_docs",
            classification="docs_contract_without_tools_inventory_key",
            reason=(
                "The upstream docs tree exposes this endpoint contract, but the tools endpoint "
                "inventory does not list the same normalized key."
            ),
            matched_docs_endpoint=docs_by_key[key],
        )
        for key in sorted(docs_keys - tools_keys)
    )
    blocking_rows = [row for row in rows if row["blocking"]]
    return {
        "tools_endpoint_missing_docs": tools_missing_docs,
        "docs_endpoint_missing_tools": docs_missing_tools,
        "rows": rows,
        "tools_endpoint_missing_docs_count": len(tools_missing_docs),
        "docs_endpoint_missing_tools_count": len(docs_missing_tools),
        "classified_mismatch_count": len(rows) - len(blocking_rows),
        "blocking_mismatch_count": len(blocking_rows),
        "blocking_tools_endpoint_missing_docs_count": sum(
            1 for row in blocking_rows if row["status"] == "tools_endpoint_missing_docs"
        ),
        "blocking_docs_endpoint_missing_tools_count": sum(
            1 for row in blocking_rows if row["status"] == "docs_endpoint_missing_tools"
        ),
    }


def build_nba_api_metadata_ledger(docs_root: Path | str | None) -> dict[str, Any]:
    root = Path(docs_root) if docs_root is not None else None
    if root is None:
        ledger: dict[str, Any] = {
            "enabled": False,
            "schema_version": 1,
            "docs_root": None,
            "summary": {},
            "warnings": ["endpoint_analysis_docs_root_not_configured"],
        }
        digest_source = json.dumps(ledger, sort_keys=True, separators=(",", ":"))
        ledger["metadata_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
        return ledger

    warnings: list[dict[str, str]] = []
    stats_dir = _endpoint_docs_dir(root)
    live_dir = _live_endpoint_docs_dir(root)
    static_dir = _stats_static_docs_dir(root)
    output_dir = _endpoint_output_docs_dir(root)
    parameter_doc = _parameter_library_doc_path(root)
    tools_dir = _tools_dir(root)

    stats_endpoint_metadata: list[dict[str, Any]] = []
    if stats_dir.is_dir():
        for path in sorted(stats_dir.glob("*.md")):
            try:
                markdown = path.read_text(encoding="utf-8")
                metadata = _parse_stats_endpoint_metadata(root, path, markdown)
            except OSError as exc:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": f"read_failed:{type(exc).__name__}",
                    }
                )
                continue
            if metadata is None:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": "stats_metadata_parse_failed",
                    }
                )
                continue
            stats_endpoint_metadata.append(metadata)
    else:
        warnings.append(
            {
                "source_path": _source_path(root, stats_dir),
                "reason": "stats_endpoint_docs_dir_missing",
            }
        )

    live_supplements_by_slug: dict[str, dict[str, Any]] = {}
    if live_dir is not None and live_dir.is_dir():
        for path in sorted(live_dir.glob("*.md")):
            try:
                markdown = path.read_text(encoding="utf-8")
                supplement = _parse_live_endpoint_metadata(root, path, markdown)
            except OSError as exc:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": f"read_failed:{type(exc).__name__}",
                    }
                )
                continue
            if supplement is None:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": "live_metadata_parse_failed",
                    }
                )
                continue
            warnings.extend(supplement.get("warnings", []))
            live_supplements_by_slug[supplement["endpoint_slug"]] = supplement

    live_endpoint_metadata = [
        _live_runtime_metadata_from_class(
            runtime_cls,
            live_supplements_by_slug.get(runtime_cls.__module__.rsplit(".", 1)[-1]),
        )
        for _name, runtime_cls in sorted(_discover_live_runtime_endpoint_classes().items())
    ]

    static_doc_metadata: list[dict[str, Any]] = []
    if static_dir is not None and static_dir.is_dir():
        for path in sorted(static_dir.glob("*.md")):
            try:
                metadata = _parse_static_doc_metadata(root, path, path.read_text(encoding="utf-8"))
            except OSError as exc:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": f"read_failed:{type(exc).__name__}",
                    }
                )
                continue
            if metadata is not None:
                static_doc_metadata.append(metadata)

    endpoint_output_samples: list[dict[str, Any]] = []
    if output_dir is not None and output_dir.is_dir():
        for path in sorted(output_dir.glob("*_output.md")):
            try:
                endpoint_output_samples.append(
                    _parse_endpoint_output_sample(root, path, path.read_text(encoding="utf-8"))
                )
            except OSError as exc:
                warnings.append(
                    {
                        "source_path": _source_path(root, path),
                        "reason": f"read_failed:{type(exc).__name__}",
                    }
                )

    parameter_library = _parse_parameter_library(root, parameter_doc)
    tools_metadata = _parse_tools_metadata(root, tools_dir)
    tools_reconciliation = _reconcile_tools_metadata(tools_metadata, stats_endpoint_metadata)
    warnings.extend(tools_metadata.get("warnings", []))

    stats_result_set_count = sum(
        len(endpoint["result_sets"]) for endpoint in stats_endpoint_metadata
    )
    stats_column_count = sum(
        result_set["column_count"]
        for endpoint in stats_endpoint_metadata
        for result_set in endpoint["result_sets"]
    )
    live_data_set_count = sum(len(endpoint["data_sets"]) for endpoint in live_endpoint_metadata)
    live_field_count = sum(
        data_set["field_count"]
        for endpoint in live_endpoint_metadata
        for data_set in endpoint["data_sets"]
    )
    live_skipped_shape_count = sum(
        len(endpoint.get("skipped_shapes", [])) for endpoint in live_endpoint_metadata
    )
    static_function_count = sum(len(doc["functions"]) for doc in static_doc_metadata)
    static_dictionary_shape_count = sum(
        len(doc["dictionary_shapes"]) for doc in static_doc_metadata
    )
    parameter_entries = parameter_library["parameters"]
    parameter_no_info_count = sum(
        1 for parameter in parameter_entries if parameter["no_available_information"]
    )

    ledger = {
        "enabled": True,
        "schema_version": 1,
        "docs_root": str(root),
        "stats_endpoint_metadata": stats_endpoint_metadata,
        "live_endpoint_metadata": live_endpoint_metadata,
        "static_doc_metadata": static_doc_metadata,
        "parameter_library": parameter_library,
        "endpoint_output_samples": endpoint_output_samples,
        "tools_metadata": tools_metadata,
        "tools_reconciliation": tools_reconciliation,
        "summary": {
            "stats_endpoint_metadata_count": len(stats_endpoint_metadata),
            "stats_result_set_metadata_count": stats_result_set_count,
            "stats_column_metadata_count": stats_column_count,
            "stats_parameter_row_count": sum(
                len(endpoint["parameters"]) for endpoint in stats_endpoint_metadata
            ),
            "live_endpoint_metadata_count": len(live_endpoint_metadata),
            "live_data_set_metadata_count": live_data_set_count,
            "live_field_metadata_count": live_field_count,
            "live_skipped_shape_count": live_skipped_shape_count,
            "static_doc_metadata_count": len(static_doc_metadata),
            "static_function_doc_count": static_function_count,
            "static_dictionary_shape_count": static_dictionary_shape_count,
            "parameter_library_entry_count": len(parameter_entries),
            "parameter_library_no_available_info_count": parameter_no_info_count,
            "endpoint_output_sample_count": len(endpoint_output_samples),
            "endpoint_output_sample_column_count": sum(
                len(sample["columns"]) for sample in endpoint_output_samples
            ),
            "tools_endpoint_list_count": len(tools_metadata["endpoint_list"]),
            "tools_parameter_variation_key_count": len(tools_metadata["parameter_variation_keys"]),
            "tools_parameter_map_key_count": len(tools_metadata["parameter_map_keys"]),
            "tools_endpoint_missing_docs_count": tools_reconciliation[
                "tools_endpoint_missing_docs_count"
            ],
            "docs_endpoint_missing_tools_count": tools_reconciliation[
                "docs_endpoint_missing_tools_count"
            ],
            "classified_tools_docs_mismatch_count": tools_reconciliation[
                "classified_mismatch_count"
            ],
            "blocking_tools_docs_mismatch_count": tools_reconciliation["blocking_mismatch_count"],
            "blocking_tools_endpoint_missing_docs_count": tools_reconciliation[
                "blocking_tools_endpoint_missing_docs_count"
            ],
            "blocking_docs_endpoint_missing_tools_count": tools_reconciliation[
                "blocking_docs_endpoint_missing_tools_count"
            ],
            "metadata_ingestion_warning_count": len(warnings),
        },
        "warnings": warnings,
    }
    digest_payload = {key: value for key, value in ledger.items() if key != "docs_root"}
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    ledger["metadata_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return ledger


def _bronze_identifier(*parts: str | None) -> str:
    tokens: list[str] = []
    for part in parts:
        if not part:
            continue
        cleaned = _BRONZE_IDENTIFIER_RE.sub("_", part).strip("_").lower()
        if cleaned:
            tokens.append(cleaned)
    return "_".join(tokens)


def _bronze_columns_from_names(
    names: list[str],
    *,
    endpoint: str | None = None,
    result_set: str | None = None,
) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for ordinal, name in enumerate(names):
        description, description_source = resolved_field_description(
            None,
            name,
            endpoint=endpoint,
            result_set=result_set,
        )
        columns.append(
            {
                "name": name,
                "ordinal": ordinal,
                "description": description,
                "description_source": description_source,
                "nullable": True,
                "source": "nba_api_expected_columns",
            }
        )
    return columns


def build_nba_api_bronze_contracts_from_bundle(bundle: dict[str, Any]) -> dict[str, Any]:
    metadata_ledger = bundle.get("metadata_ledger", {})
    stats_metadata_by_endpoint = {
        endpoint["endpoint"]: endpoint
        for endpoint in metadata_ledger.get("stats_endpoint_metadata", [])
        if isinstance(endpoint, dict) and endpoint.get("endpoint")
    }
    tables: list[dict[str, Any]] = []
    skipped_zero_column_tables: list[dict[str, Any]] = []

    for endpoint in bundle.get("stats_contracts", []):
        endpoint_name = endpoint["runtime_class_name"]
        endpoint_slug = endpoint.get("endpoint_slug") or _bronze_identifier(endpoint_name)
        stats_metadata = stats_metadata_by_endpoint.get(endpoint_name, {})
        result_metadata_by_name = {
            result_set["result_set_name"]: result_set
            for result_set in stats_metadata.get("result_sets", [])
            if isinstance(result_set, dict)
        }
        for result_set in endpoint.get("result_sets", []):
            result_set_name = result_set.get("result_set_name") or "result_set"
            result_metadata = result_metadata_by_name.get(result_set_name, {})
            columns: list[dict[str, Any]] = []
            for column in result_metadata.get("columns", []):
                column_name = str(column.get("name") or "")
                description, description_source = resolved_field_description(
                    column.get("description"),
                    column_name,
                    endpoint=endpoint_name,
                    result_set=result_set_name,
                )
                columns.append(
                    {
                        **column,
                        "description": description,
                        "description_source": column.get("description_source")
                        or description_source,
                        "nullable": True,
                        "source": "nba_api_docs_tools_ingestion",
                    }
                )
            if not columns:
                columns = _bronze_columns_from_names(
                    result_set.get("expected_columns", []),
                    endpoint=endpoint_name,
                    result_set=result_set_name,
                )
            if not columns:
                classification, classification_reason, blocking = _known_zero_column_classification(
                    endpoint_name, result_set_name
                )
                skipped_zero_column_tables.append(
                    {
                        "source_family": "stats",
                        "endpoint": endpoint_name,
                        "endpoint_slug": endpoint_slug,
                        "result_set_name": result_set_name,
                        "source_path": endpoint.get("source_path"),
                        "reason": "zero_column_result_set_suppressed",
                        "classification": classification,
                        "classification_reason": classification_reason,
                        "blocking": blocking,
                    }
                )
                continue
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier("stats", endpoint_slug, result_set_name),
                    "source_family": "stats",
                    "endpoint": endpoint_name,
                    "endpoint_slug": endpoint_slug,
                    "result_set_name": result_set_name,
                    "source_dataset_method": result_metadata.get("method_name"),
                    "data_grain": "nba_api_result_set",
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": stats_metadata.get("parameters", endpoint.get("parameters", [])),
                    "source_path": endpoint.get("source_path"),
                    "endpoint_url": endpoint.get("endpoint_url"),
                    "valid_url": endpoint.get("valid_url"),
                }
            )

    for endpoint in metadata_ledger.get("live_endpoint_metadata", []):
        for data_set in endpoint.get("data_sets", []):
            fields = data_set.get("fields", [])
            columns = []
            for ordinal, field in enumerate(fields):
                if not field.get("key"):
                    continue
                column_name = str(field.get("name") or field["key"])
                description, description_source = resolved_field_description(
                    field.get("description"),
                    column_name,
                    endpoint=str(endpoint.get("endpoint") or ""),
                    result_set=str(data_set.get("result_set_name") or ""),
                    json_path=field.get("json_path"),
                )
                columns.append(
                    {
                        "name": column_name,
                        "ordinal": ordinal,
                        "description": description,
                        "description_source": field.get("description_source") or description_source,
                        "nullable": field.get("nullable", True),
                        "source": field.get("source", "nba_api_live_expected_data"),
                        "json_path": field.get("json_path"),
                        "sample_type": field.get("sample_type") or field.get("type"),
                    }
                )
            if not columns:
                continue
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier(
                        "live",
                        endpoint.get("endpoint_slug"),
                        data_set.get("result_set_name"),
                    ),
                    "source_family": "live",
                    "endpoint": endpoint.get("endpoint"),
                    "endpoint_slug": endpoint.get("endpoint_slug"),
                    "result_set_name": data_set.get("result_set_name"),
                    "source_dataset_method": data_set.get("method_name"),
                    "data_grain": data_set.get("data_grain", "nba_api_live_json_object"),
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": endpoint.get("parameters", []),
                    "source_path": endpoint.get("source_path"),
                    "endpoint_url": endpoint.get("endpoint_url"),
                    "valid_url": endpoint.get("valid_url"),
                    "json_path": data_set.get("json_path"),
                }
            )

    for static_doc in metadata_ledger.get("static_doc_metadata", []):
        for index, dictionary_shape in enumerate(static_doc.get("dictionary_shapes", [])):
            keys = dictionary_shape.get("keys", [])
            result_set_name = f"shape_{index + 1}"
            columns = _bronze_columns_from_names(
                keys,
                endpoint=str(static_doc.get("module") or "static"),
                result_set=result_set_name,
            )
            tables.append(
                {
                    "bronze_table": "bronze_"
                    + _bronze_identifier("static", static_doc.get("module"), result_set_name),
                    "source_family": "static",
                    "endpoint": static_doc.get("module"),
                    "endpoint_slug": static_doc.get("module"),
                    "result_set_name": f"{static_doc.get('module')}_{result_set_name}",
                    "source_dataset_method": None,
                    "data_grain": "nba_api_static_dictionary",
                    "columns": columns,
                    "column_count": len(columns),
                    "parameters": [],
                    "source_path": static_doc.get("source_path"),
                    "endpoint_url": None,
                    "valid_url": None,
                }
            )

    contracts = {
        "enabled": bool(bundle.get("enabled")),
        "schema_version": 1,
        "source_bundle_digest": bundle.get("bundle_digest"),
        "source_metadata_digest": metadata_ledger.get("metadata_digest"),
        "tables": sorted(tables, key=lambda table: table["bronze_table"]),
        "summary": {
            "table_count": len(tables),
            "stats_table_count": sum(1 for table in tables if table["source_family"] == "stats"),
            "live_table_count": sum(1 for table in tables if table["source_family"] == "live"),
            "static_table_count": sum(1 for table in tables if table["source_family"] == "static"),
            "column_count": sum(table["column_count"] for table in tables),
            "zero_column_table_count": len(skipped_zero_column_tables),
        },
        "skipped_zero_column_tables": skipped_zero_column_tables,
    }
    blocking_zero_column_tables = [
        table for table in skipped_zero_column_tables if table.get("blocking")
    ]
    contracts["summary"]["classified_zero_column_table_count"] = len(
        skipped_zero_column_tables
    ) - len(blocking_zero_column_tables)
    contracts["summary"]["blocking_zero_column_table_count"] = len(blocking_zero_column_tables)
    described_column_count = 0
    description_source_counts: dict[str, int] = {}
    for table in contracts["tables"]:
        for column in table.get("columns", []):
            if column.get("description"):
                described_column_count += 1
            description_source = str(column.get("description_source") or "missing")
            description_source_counts[description_source] = (
                description_source_counts.get(description_source, 0) + 1
            )
    contracts["summary"]["described_column_count"] = described_column_count
    contracts["summary"]["missing_description_count"] = (
        contracts["summary"]["column_count"] - described_column_count
    )
    contracts["summary"]["description_source_counts"] = dict(
        sorted(description_source_counts.items())
    )
    digest_payload = {
        key: value for key, value in contracts.items() if key != "source_bundle_digest"
    }
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    contracts["bronze_contract_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return contracts


def build_nba_api_upstream_contract_bundle(docs_root: Path | str | None) -> dict[str, Any]:
    root = Path(docs_root) if docs_root is not None else None
    if root is None:
        metadata_ledger = build_nba_api_metadata_ledger(None)
        bundle: dict[str, Any] = {
            "enabled": False,
            "schema_version": 1,
            "docs_root": None,
            "upstream_git_sha": None,
            "source_inventory": {},
            "stats_contracts": [],
            "live_contracts": [],
            "metadata_ledger": metadata_ledger,
            "warnings": ["endpoint_analysis_docs_root_not_configured"],
        }
    else:
        stats_dir = _endpoint_docs_dir(root)
        live_dir = _live_endpoint_docs_dir(root)
        static_dir = _stats_static_docs_dir(root)
        output_dir = _endpoint_output_docs_dir(root)
        responses_dir = _endpoint_response_fixtures_dir(root)
        parameter_doc = _parameter_library_doc_path(root)
        tools_dir = _tools_dir(root)
        stats_contracts, malformed_stats_docs = (
            _discover_endpoint_analysis_doc_contracts_with_warnings(root)
        )
        metadata_ledger = build_nba_api_metadata_ledger(root)
        live_supplements_by_slug = {
            endpoint.get("endpoint_slug"): endpoint
            for endpoint in metadata_ledger.get("live_endpoint_metadata", [])
            if isinstance(endpoint, dict) and endpoint.get("endpoint_slug")
        }
        live_contracts = discover_runtime_live_endpoint_contracts(live_supplements_by_slug)
        stats_docs = _relative_paths(root, stats_dir, "*.md")
        live_docs = _relative_paths(root, live_dir, "*.md")
        static_docs = _relative_paths(root, static_dir, "*.md")
        output_docs = _relative_paths(root, output_dir, "*_output.md")
        response_fixtures = _relative_paths(root, responses_dir, "*.json")
        tools_files = _relative_paths(root, tools_dir, "*.py")
        parameter_docs = [_source_path(root, parameter_doc)] if parameter_doc is not None else []
        bundle = {
            "enabled": True,
            "schema_version": 1,
            "docs_root": str(root),
            "upstream_git_sha": _git_sha(root),
            "source_inventory": {
                "stats_endpoint_doc_count": (
                    len(list(stats_dir.glob("*.md"))) if stats_dir.is_dir() else 0
                ),
                "parsed_stats_contract_count": len(stats_contracts),
                "live_endpoint_doc_count": (
                    len(list(live_dir.glob("*.md")))
                    if live_dir is not None and live_dir.is_dir()
                    else 0
                ),
                "parsed_live_contract_count": len(live_contracts),
                "static_doc_count": len(static_docs),
                "parameter_library_doc_count": len(parameter_docs),
                "endpoint_output_doc_count": len(output_docs),
                "response_fixture_count": len(response_fixtures),
                "tools_python_file_count": len(tools_files),
                **metadata_ledger.get("summary", {}),
            },
            "source_files": {
                "stats_endpoint_docs": stats_docs,
                "live_endpoint_docs": live_docs,
                "static_docs": static_docs,
                "parameter_library_docs": parameter_docs,
                "endpoint_output_docs": output_docs,
                "response_fixtures": response_fixtures,
                "tools": tools_files,
            },
            "source_file_digests": {
                "stats_endpoint_docs": _source_file_digests(root, stats_docs),
                "live_endpoint_docs": _source_file_digests(root, live_docs),
                "static_docs": _source_file_digests(root, static_docs),
                "parameter_library_docs": _source_file_digests(root, parameter_docs),
                "endpoint_output_docs": _source_file_digests(root, output_docs),
                "response_fixtures": _source_file_digests(root, response_fixtures),
                "tools": _source_file_digests(root, tools_files),
            },
            "malformed_stats_docs": malformed_stats_docs,
            "stats_contracts": [
                contract_to_json(contract) for _name, contract in sorted(stats_contracts.items())
            ],
            "live_contracts": [
                contract_to_json(contract) for _name, contract in sorted(live_contracts.items())
            ],
            "metadata_ledger": metadata_ledger,
            "warnings": (["malformed_stats_docs_detected"] if malformed_stats_docs else []),
        }

    bronze_contracts = build_nba_api_bronze_contracts_from_bundle(bundle)
    bundle["bronze_contracts_summary"] = bronze_contracts["summary"]
    bundle["bronze_contract_digest"] = bronze_contracts["bronze_contract_digest"]
    digest_payload = {key: value for key, value in bundle.items() if key != "docs_root"}
    metadata_ledger_payload = digest_payload.get("metadata_ledger")
    if isinstance(metadata_ledger_payload, dict):
        digest_payload["metadata_ledger"] = {
            key: value for key, value in metadata_ledger_payload.items() if key != "docs_root"
        }
    digest_source = json.dumps(digest_payload, sort_keys=True, separators=(",", ":"))
    bundle["bundle_digest"] = hashlib.sha256(digest_source.encode("utf-8")).hexdigest()
    return bundle


@lru_cache(maxsize=1)
def discover_runtime_endpoint_contracts() -> dict[str, NbaApiEndpointContract]:
    try:
        from nba_api.stats import endpoints
    except Exception:
        return {}

    contracts: dict[str, NbaApiEndpointContract] = {}
    package_path = getattr(endpoints, "__path__", None)
    if package_path is None:
        return contracts

    for module_info in pkgutil.iter_modules(package_path):
        try:
            module = importlib.import_module(f"{endpoints.__name__}.{module_info.name}")
        except Exception:
            continue
        for name, obj in inspect.getmembers(module, inspect.isclass):
            if obj.__module__ != module.__name__:
                continue
            if name.startswith("_") or name == "Endpoint":
                continue
            contracts[name] = build_endpoint_contract(obj)
    return contracts


def contract_to_json(contract: NbaApiEndpointContract) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "runtime_class_name": contract.runtime_class_name,
        "module_name": contract.module_name,
        "endpoint_slug": contract.endpoint_slug,
        "parameters": list(contract.parameters),
        "required_parameters": list(contract.required_parameters),
        "nullable_parameters": list(contract.nullable_parameters),
        "deprecated": contract.deprecated,
        "warnings": list(contract.warnings),
        "result_sets": [
            {
                "runtime_class_name": result_set.runtime_class_name,
                "result_set_index": result_set.result_set_index,
                "result_set_name": result_set.result_set_name,
                "expected_columns": list(result_set.expected_columns),
                "source": result_set.source,
                "confidence": result_set.confidence,
            }
            for result_set in contract.result_sets
        ],
    }
    optional_values: dict[str, Any] = {
        "parameter_patterns": dict(contract.parameter_patterns),
        "endpoint_url": contract.endpoint_url,
        "valid_url": contract.valid_url,
        "last_validated_date": contract.last_validated_date,
        "source_path": contract.source_path,
        "source_family": contract.source_family,
        "status": contract.status,
    }
    for key, value in optional_values.items():
        if value not in (None, {}, ()):
            payload[key] = value
    return payload
