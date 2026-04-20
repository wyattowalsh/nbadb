# Advanced Components Reference

## 1. Usage Goal

Use this guide in `sync` and `enhance` runs to choose framework-native patterns for Mermaid, codeblocks, tables, and embeds while keeping safe fallbacks ready.

## 2. Framework Pattern Matrix

| Framework | Mermaid | Codeblocks | Tables | Embeds | Safe fallbacks |
|-----------|---------|------------|--------|--------|----------------|
| Astro + Starlight | Prefer fenced `mermaid` blocks in Markdown/MDX when Mermaid integration is enabled. | Use fenced blocks with explicit language tags and optional title metadata. | Use Markdown tables for simple comparisons; use MDX components for rich cells. | Use MDX `iframe`/component embeds with explicit titles. | Replace diagrams with numbered flow steps + linked image/text alternative; replace embeds with screenshot + canonical link. |
| Docusaurus | Enable `@docusaurus/theme-mermaid` and use fenced `mermaid` blocks. | Use fenced blocks with language, and titles when needed for context. | Use Markdown tables for portability; MDX tables for richer layouts. | Use MDX embeds (for example `iframe`) with accessible titles/captions. | If Mermaid/theme support is unavailable, convert to ordered steps or static SVG/PNG plus alt text and link. |
| Fumadocs (Next + MDX) | Use project-configured Mermaid support (`mermaid` fences or MDX Mermaid components). | Use MDX/code fences with language labels and focused snippets per task. | Use Markdown tables first; switch to MDX table components only when needed. | Use MDX React embeds with title and nearby summary text. | If rendering is uncertain, use static diagrams or pseudocode and link out to canonical demo/media. |
| Sphinx | Use `.. mermaid::` via `sphinxcontrib-mermaid` when available. | Use `.. code-block:: <lang>` (or `.. literalinclude::`) with captions as needed. | Use grid/simple tables for light data, `.. list-table::` for structured datasets. | Use extension directives (for example video) or `.. raw:: html` carefully. | If directives/extensions are missing, replace with plain rst lists/tables and external links to media. |
| MkDocs (+ Material/plugins) | Use fenced `mermaid` blocks with `pymdownx.superfences`/`mkdocs-mermaid2-plugin`. | Use fenced blocks with language tags and optional highlight annotations. | Use Markdown tables; keep structure simple for theme portability. | Use raw HTML embeds only when trusted and supported by markdown extensions/plugins. | If plugin support is absent, use static image diagrams, concise comparison bullets, and direct links instead of embeds. |

## 3. Accessibility and Safety Baseline

- Always add plain-language context before or after advanced components.
- Mermaid diagrams need text equivalents (summary, ordered steps, or both).
- Codeblocks must include language labels and avoid hiding critical steps in tabs only.
- Embedded media must have titles and a text-link fallback to the source.
