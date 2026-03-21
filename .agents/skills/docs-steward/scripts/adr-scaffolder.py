#!/usr/bin/env python3
"""Generate an Architecture Decision Record (ADR) in MADR format.

Output: MADR-formatted markdown to stdout.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

TEMPLATE = """# {number}. {title}

Date: {date}

## Status

{status}

## Context

{context}

## Decision

{decision}

## Consequences

### Positive

{positive}

### Negative

{negative}

### Neutral

{neutral}
"""


def load_template_overrides(template_path: str | None) -> dict:
    """Load custom template structure from JSON if provided."""
    if not template_path:
        return {}
    path = Path(template_path)
    if path.exists():
        with open(path) as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    return {}


def format_list(items: list[str]) -> str:
    """Format a list of strings as markdown bullet points."""
    if not items:
        return "- None identified yet."
    return "\n".join(f"- {item}" for item in items)


def generate_adr(args: argparse.Namespace) -> str:
    """Generate MADR-formatted ADR content."""
    overrides = load_template_overrides(args.template)

    number = args.number or "NNNN"
    title = args.title
    status = args.status or "Proposed"
    context = args.context or "<!-- Describe the issue motivating this decision. -->"
    decision = args.decision or "<!-- Describe the change proposed or decided. -->"

    positive = format_list(args.positive.split("|") if args.positive else [])
    negative = format_list(args.negative.split("|") if args.negative else [])
    neutral = format_list(args.neutral.split("|") if args.neutral else [])

    return TEMPLATE.format(
        number=number,
        title=title,
        date=overrides.get("date_format", str(date.today())),
        status=status,
        context=context,
        decision=decision,
        positive=positive,
        negative=negative,
        neutral=neutral,
    ).strip() + "\n"


def main():
    parser = argparse.ArgumentParser(description="Generate MADR-format ADR")
    parser.add_argument("title", help="Decision title")
    parser.add_argument("--number", help="ADR sequence number (e.g. 0042)")
    parser.add_argument("--status", default="Proposed",
                        choices=["Proposed", "Accepted", "Deprecated", "Superseded"],
                        help="Decision status")
    parser.add_argument("--context", help="Context paragraph")
    parser.add_argument("--decision", help="Decision paragraph")
    parser.add_argument("--positive", help="Positive consequences (pipe-separated)")
    parser.add_argument("--negative", help="Negative consequences (pipe-separated)")
    parser.add_argument("--neutral", help="Neutral consequences (pipe-separated)")
    parser.add_argument("--template", help="Path to custom ADR template JSON")
    parser.add_argument("--output", help="Output file path (default: stdout)")
    parser.add_argument("--json", action="store_true", help="Output as JSON instead of markdown")
    args = parser.parse_args()

    content = generate_adr(args)

    if args.json:
        result = {
            "title": args.title,
            "number": args.number or "NNNN",
            "status": args.status,
            "content": content,
        }
        json.dump(result, sys.stdout, indent=2)
        print()
    elif args.output:
        Path(args.output).write_text(content)
        print(json.dumps({"written": args.output, "lines": len(content.splitlines())}))
    else:
        print(content)


if __name__ == "__main__":
    main()
