#!/usr/bin/env python3
"""Analyze docstring and comment coverage across a codebase.

Output JSON: {coverage_pct, total_items, documented_items, modules, undocumented}
"""

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path


def analyze_python_file(filepath: str) -> dict:
    """Extract public symbols and their docstring status from a Python file."""
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError, PermissionError):
        return {"path": filepath, "items": [], "error": "parse_failed"}

    items = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if node.name.startswith("_") and not node.name.startswith("__"):
                continue
            has_doc = (
                isinstance(node.body[0], ast.Expr)
                and isinstance(node.body[0].value, ast.Constant)
                and isinstance(node.body[0].value.value, str)
                if node.body
                else False
            )
            items.append({
                "name": node.name,
                "type": "class" if isinstance(node, ast.ClassDef) else "function",
                "line": node.lineno,
                "documented": has_doc,
            })

    # Check module-level docstring
    module_doc = ast.get_docstring(tree) is not None
    items.insert(0, {
        "name": os.path.basename(filepath),
        "type": "module",
        "line": 1,
        "documented": module_doc,
    })

    return {"path": filepath, "items": items}


def analyze_js_ts_file(filepath: str) -> dict:
    """Extract exported symbols and JSDoc coverage from JS/TS files."""
    try:
        with open(filepath) as f:
            lines = f.readlines()
    except (UnicodeDecodeError, PermissionError):
        return {"path": filepath, "items": [], "error": "parse_failed"}

    items = []
    jsdoc_pattern = re.compile(r"^\s*/\*\*")
    export_pattern = re.compile(
        r"^\s*export\s+(?:default\s+)?(?:async\s+)?(?:function|class|const|let|var|interface|type|enum)\s+(\w+)"
    )

    has_jsdoc_above = False
    for i, line in enumerate(lines):
        if jsdoc_pattern.match(line):
            has_jsdoc_above = True
            continue
        m = export_pattern.match(line)
        if m:
            items.append({
                "name": m.group(1),
                "type": "export",
                "line": i + 1,
                "documented": has_jsdoc_above,
            })
            has_jsdoc_above = False
        elif (
            line.strip()
            and not line.strip().startswith("*")
            and not line.strip().startswith("*/")
        ):
            has_jsdoc_above = False

    return {"path": filepath, "items": items}


LANG_EXTENSIONS = {
    ".py": analyze_python_file,
    ".js": analyze_js_ts_file,
    ".jsx": analyze_js_ts_file,
    ".ts": analyze_js_ts_file,
    ".tsx": analyze_js_ts_file,
}

SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".astro", "coverage",
}


def scan_directory(root: str, extensions: set | None = None) -> list[dict]:
    """Walk directory and analyze all supported source files."""
    results = []
    exts = extensions or set(LANG_EXTENSIONS.keys())
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1]
            if ext in exts and ext in LANG_EXTENSIONS:
                full = os.path.join(dirpath, fname)
                results.append(LANG_EXTENSIONS[ext](full))
    return results


def compute_summary(modules: list[dict]) -> dict:
    """Aggregate coverage statistics."""
    total = 0
    documented = 0
    undocumented = []

    for mod in modules:
        if mod.get("error"):
            continue
        for item in mod["items"]:
            total += 1
            if item["documented"]:
                documented += 1
            else:
                undocumented.append({
                    "file": mod["path"],
                    "name": item["name"],
                    "type": item["type"],
                    "line": item["line"],
                })

    pct = round((documented / total) * 100, 1) if total > 0 else 0.0
    return {
        "coverage_pct": pct,
        "total_items": total,
        "documented_items": documented,
        "modules": [
            {
                "path": m["path"],
                "total": len(m["items"]),
                "documented": sum(1 for i in m["items"] if i["documented"]),
                "error": m.get("error"),
            }
            for m in modules
        ],
        "undocumented": undocumented,
    }


def main():
    parser = argparse.ArgumentParser(description="Analyze docstring/comment coverage")
    parser.add_argument("path", help="Directory or file to analyze")
    parser.add_argument(
        "--extensions",
        help="Comma-separated file extensions (e.g. .py,.ts)",
        default=None,
    )
    parser.add_argument(
        "--min-coverage",
        type=float,
        default=0.0,
        help="Exit non-zero if coverage below threshold",
    )
    args = parser.parse_args()

    exts = set(args.extensions.split(",")) if args.extensions else None
    target = Path(args.path)

    if target.is_file():
        ext = target.suffix
        if ext in LANG_EXTENSIONS:
            modules = [LANG_EXTENSIONS[ext](str(target))]
        else:
            print(f"Unsupported file type: {ext}", file=sys.stderr)
            sys.exit(1)
    elif target.is_dir():
        modules = scan_directory(str(target), exts)
    else:
        print(f"Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    summary = compute_summary(modules)
    json.dump(summary, sys.stdout, indent=2)
    print()

    if summary["coverage_pct"] < args.min_coverage:
        print(
            f"Coverage {summary['coverage_pct']}% below threshold {args.min_coverage}%",
            file=sys.stderr,
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
