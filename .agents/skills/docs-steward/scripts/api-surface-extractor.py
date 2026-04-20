#!/usr/bin/env python3
"""Extract public API surface from source code.

Output JSON: {modules: [{name, path, exports: [{name, type, signature, docstring}]}]}
"""

import argparse
import ast
import json
import os
import re
import sys
import textwrap
from pathlib import Path


SKIP_DIRS = {
    "node_modules", ".git", "__pycache__", ".venv", "venv",
    "dist", "build", ".next", ".astro", "coverage", "tests", "test",
}


def format_signature(node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
    """Build a human-readable function signature from AST."""
    parts = []
    args = node.args

    # Positional args
    defaults_offset = len(args.args) - len(args.defaults)
    for i, arg in enumerate(args.args):
        name = arg.arg
        annotation = ast.unparse(arg.annotation) if arg.annotation else None
        default_idx = i - defaults_offset
        default = ast.unparse(args.defaults[default_idx]) if default_idx >= 0 else None

        part = f"{name}: {annotation}" if annotation else name
        if default:
            part += f" = {default}"
        parts.append(part)

    # *args
    if args.vararg:
        v = args.vararg
        part = f"*{v.arg}"
        if v.annotation:
            part = f"*{v.arg}: {ast.unparse(v.annotation)}"
        parts.append(part)
    elif args.kwonlyargs:
        parts.append("*")

    # Keyword-only args
    for i, arg in enumerate(args.kwonlyargs):
        name = arg.arg
        annotation = ast.unparse(arg.annotation) if arg.annotation else None
        default = ast.unparse(args.kw_defaults[i]) if args.kw_defaults[i] else None
        part = f"{name}: {annotation}" if annotation else name
        if default:
            part += f" = {default}"
        parts.append(part)

    # **kwargs
    if args.kwarg:
        k = args.kwarg
        part = f"**{k.arg}"
        if k.annotation:
            part = f"**{k.arg}: {ast.unparse(k.annotation)}"
        parts.append(part)

    sig = f"({', '.join(parts)})"
    if node.returns:
        sig += f" -> {ast.unparse(node.returns)}"
    return sig


def extract_python_exports(filepath: str) -> list[dict]:
    """Extract public classes, functions, and constants from a Python module."""
    try:
        with open(filepath) as f:
            source = f.read()
        tree = ast.parse(source, filename=filepath)
    except (SyntaxError, UnicodeDecodeError):
        return []

    # Check for __all__
    explicit_all = None
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if (
                    isinstance(target, ast.Name)
                    and target.id == "__all__"
                    and isinstance(node.value, (ast.List, ast.Tuple))
                ):
                    explicit_all = {
                        elt.value
                        for elt in node.value.elts
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str)
                    }

    exports = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name.startswith("_"):
                continue
            if explicit_all and node.name not in explicit_all:
                continue
            docstring = ast.get_docstring(node) or ""
            exports.append({
                "name": node.name,
                "type": "async function" if isinstance(node, ast.AsyncFunctionDef) else "function",
                "signature": format_signature(node),
                "docstring": textwrap.shorten(docstring, width=300, placeholder="..."),
                "line": node.lineno,
            })
        elif isinstance(node, ast.ClassDef):
            if node.name.startswith("_"):
                continue
            if explicit_all and node.name not in explicit_all:
                continue
            docstring = ast.get_docstring(node) or ""
            # Extract method signatures
            methods = []
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    if item.name.startswith("_") and item.name != "__init__":
                        continue
                    methods.append({
                        "name": item.name,
                        "signature": format_signature(item),
                        "docstring": textwrap.shorten(
                            ast.get_docstring(item) or "", width=200, placeholder="..."
                        ),
                    })
            entry = {
                "name": node.name,
                "type": "class",
                "signature": f"class {node.name}",
                "docstring": textwrap.shorten(docstring, width=300, placeholder="..."),
                "line": node.lineno,
            }
            if methods:
                entry["methods"] = methods
            exports.append(entry)

    return exports


def extract_js_ts_exports(filepath: str) -> list[dict]:
    """Extract exported symbols from JS/TS files using regex."""
    try:
        with open(filepath) as f:
            content = f.read()
            lines = content.splitlines()
    except UnicodeDecodeError:
        return []

    exports = []
    jsdoc_pattern = re.compile(r"/\*\*(.*?)\*/", re.DOTALL)
    export_pattern = re.compile(
        r"export\s+(?:default\s+)?(?:async\s+)?(function|class|const|let|var|interface|type|enum)\s+(\w+)"
        r"([^{;]*)"
    )

    # Collect JSDoc blocks by end line
    jsdoc_by_line = {}
    for m in jsdoc_pattern.finditer(content):
        end_pos = m.end()
        end_line = content[:end_pos].count("\n") + 1
        doc_text = re.sub(r"\n\s*\*\s?", " ", m.group(1)).strip()
        jsdoc_by_line[end_line] = textwrap.shorten(doc_text, width=300, placeholder="...")

    for i, line in enumerate(lines):
        m = export_pattern.search(line)
        if m:
            kind = m.group(1)
            name = m.group(2)
            sig_rest = m.group(3).strip().rstrip("{").rstrip(";").strip()
            signature = f"{kind} {name}{sig_rest}" if sig_rest else f"{kind} {name}"
            docstring = jsdoc_by_line.get(i, jsdoc_by_line.get(i + 1, ""))
            exports.append({
                "name": name,
                "type": kind,
                "signature": signature,
                "docstring": docstring,
                "line": i + 1,
            })

    return exports


EXTRACTORS = {
    ".py": extract_python_exports,
    ".js": extract_js_ts_exports,
    ".jsx": extract_js_ts_exports,
    ".ts": extract_js_ts_exports,
    ".tsx": extract_js_ts_exports,
}


def scan_modules(root: str, extensions: set | None = None) -> list[dict]:
    """Walk directory and extract API surface from all source files."""
    modules = []
    exts = extensions or set(EXTRACTORS.keys())

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in sorted(filenames):
            ext = os.path.splitext(fname)[1]
            if ext in exts and ext in EXTRACTORS:
                full = os.path.join(dirpath, fname)
                exports = EXTRACTORS[ext](full)
                if exports:
                    modules.append({
                        "name": os.path.splitext(fname)[0],
                        "path": full,
                        "exports": exports,
                    })

    return modules


def main():
    parser = argparse.ArgumentParser(description="Extract public API surface from code")
    parser.add_argument("path", help="Directory or file to analyze")
    parser.add_argument(
        "--extensions",
        help="Comma-separated file extensions (e.g. .py,.ts)",
        default=None,
    )
    args = parser.parse_args()

    exts = set(args.extensions.split(",")) if args.extensions else None
    target = Path(args.path)

    if target.is_file():
        ext = target.suffix
        if ext in EXTRACTORS:
            exports = EXTRACTORS[ext](str(target))
            result = {"modules": [{
                "name": target.stem,
                "path": str(target),
                "exports": exports,
            }]}
        else:
            print(f"Unsupported file type: {ext}", file=sys.stderr)
            sys.exit(1)
    elif target.is_dir():
        modules = scan_modules(str(target), exts)
        result = {"modules": modules}
    else:
        print(f"Path not found: {args.path}", file=sys.stderr)
        sys.exit(1)

    json.dump(result, sys.stdout, indent=2)
    print()


if __name__ == "__main__":
    main()
