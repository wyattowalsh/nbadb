# Generate Mode Reference

Technical documentation generation from source code. This reference provides detailed procedures for each generate sub-mode.

## Contents

1. [API Reference](#generate-api)
2. [Architecture Decision Record](#generate-adr)
3. [Operational Runbook](#generate-runbook)
4. [Onboarding Guide](#generate-onboard)
5. [Glossary](#generate-glossary)
6. [Scripts](#scripts)
7. [Data Files](#data-files)

---

## Generate API

**Input:** `generate api <module-or-path>`

### Procedure

1. Run `scripts/api-surface-extractor.py <path>` to extract public API surface.
2. Run `scripts/doc-coverage-analyzer.py <path>` to assess current coverage.
3. For each module in the extraction output:
   a. Group exports by type (classes, functions, constants, types).
   b. Format each export with: name, signature, docstring (if present), and source line.
   c. Flag undocumented exports with a "needs docs" marker.
4. Choose docstring format from `data/docstring-formats.json` based on detected language and existing conventions.
5. Generate markdown with:
   - Module overview (from module docstring or inferred purpose)
   - Grouped export tables with signatures
   - Detailed sections per class/function with parameters, returns, examples
   - Coverage summary footer

### Output format

```markdown
# API Reference: <module>

> Coverage: X% (Y/Z items documented)

## Classes

### ClassName
<docstring>

#### Methods
| Method | Signature | Description |
|--------|-----------|-------------|

## Functions

### function_name
`signature`
<docstring>
```

### Quality checks

- Every public symbol must appear in the output
- Signatures must match source exactly (extracted, not hand-typed)
- Undocumented items flagged but not omitted
- Cross-references between related classes/functions where detectable

---

## Generate ADR

**Input:** `generate adr <decision-title>`

### Procedure

1. Load `data/adr-template.json` for MADR structure.
2. Ask clarifying questions if context/decision not provided:
   - What problem does this solve?
   - What alternatives were considered?
   - What are the expected consequences?
3. Run `scripts/adr-scaffolder.py "<title>"` with available arguments.
4. If an `docs/decisions/` or `docs/adr/` directory exists, auto-number based on existing ADRs.
5. Present the generated ADR for review before writing to disk.

### File placement

Search in order: `docs/decisions/`, `docs/adr/`, `adr/`, project root.
Create the directory if none exists (prefer `docs/decisions/`).

---

## Generate Runbook

**Input:** `generate runbook <process-name>`

### Procedure

1. Scan codebase for operational patterns:
   - Deployment scripts, Dockerfiles, CI configs
   - Error handling patterns, retry logic, health checks
   - Environment variables and configuration files
2. Ask clarifying questions about the target process scope.
3. Generate runbook with standard sections:

```markdown
# Runbook: <Process Name>

## Overview
Purpose, scope, and SLA/SLO context.

## Prerequisites
Required access, tools, and permissions.

## Procedure
Numbered steps with exact commands.

## Verification
How to confirm success.

## Rollback
How to undo if something goes wrong.

## Troubleshooting
Common failure modes and their fixes.

## Contacts
Escalation path and on-call references.
```

4. Include actual commands/scripts from the codebase where applicable.

---

## Generate Onboard

**Input:** `generate onboard`

### Procedure

1. Analyze repository structure:
   - Package manager and language(s)
   - Build system and test framework
   - Project layout conventions
2. Read existing docs: README, CONTRIBUTING, CLAUDE.md, AGENTS.md.
3. Scan for setup scripts, Makefiles, docker-compose files.
4. Generate onboarding guide:

```markdown
# Onboarding Guide

## Quick Start
Clone, install, run in < 5 steps.

## Architecture Overview
High-level component map with key directories.

## Development Workflow
Branch strategy, PR process, CI expectations.

## Key Concepts
Domain terms and patterns used in this codebase.

## Common Tasks
How to: add a feature, fix a bug, run tests, deploy.

## Resources
Links to deeper docs, team channels, design docs.
```

5. Keep commands concrete (not placeholder) using detected toolchain.

---

## Generate Glossary

**Input:** `generate glossary`

### Procedure

1. Extract candidate terms from:
   - Code identifiers (class names, enum values, constants)
   - Comments and docstrings containing definitions
   - README and docs files with term introductions
   - Domain-specific abbreviations and acronyms
2. Deduplicate and group related terms.
3. Generate alphabetical glossary:

```markdown
# Glossary

| Term | Definition | Source |
|------|-----------|--------|
| **term** | Definition extracted or inferred | `path/to/source.py:42` |
```

4. Flag terms with unclear or missing definitions for manual review.

---

## Scripts

| Script | Purpose | Input | Output |
|--------|---------|-------|--------|
| `scripts/doc-coverage-analyzer.py` | Docstring/comment coverage analysis | Directory or file path | `{coverage_pct, total_items, documented_items, modules, undocumented}` |
| `scripts/api-surface-extractor.py` | Public API surface extraction | Directory or file path | `{modules: [{name, path, exports: [{name, type, signature, docstring}]}]}` |
| `scripts/adr-scaffolder.py` | ADR generation in MADR format | Title + optional context args | MADR markdown or JSON |

All scripts use stdlib only (ast, re, argparse, json). Run with `uv run python scripts/<name>.py`.

---

## Data Files

| File | Content |
|------|---------|
| `data/docstring-formats.json` | Format standards per language: Google, NumPy, Sphinx (Python); JSDoc (JS); TSDoc (TS) |
| `data/adr-template.json` | MADR v3 template structure with section guidance and file naming conventions |
