from __future__ import annotations

from typing import TYPE_CHECKING

from nbadb.docs_gen.data_dictionary import DataDictionaryGenerator
from nbadb.docs_gen.er_diagram import ERDiagramGenerator
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.docs_gen.schema_docs import SchemaDocsGenerator

if TYPE_CHECKING:
    from pathlib import Path


# ---------------------------------------------------------------------------
# SchemaDocsGenerator
# ---------------------------------------------------------------------------


class TestSchemaDocsGenerator:
    def test_tier_mdx_starts_with_frontmatter(self) -> None:
        gen = SchemaDocsGenerator()
        content = gen.generate_tier_mdx("star")
        assert content.startswith("---"), "MDX must open with YAML frontmatter"
        assert "Schema Reference" in content

    def test_tier_mdx_unknown_tier(self) -> None:
        gen = SchemaDocsGenerator()
        content = gen.generate_tier_mdx("unknown")
        assert isinstance(content, str)
        assert "Unknown tier" in content or "unknown" in content.lower()

    def test_tier_mdx_contains_table_headers_or_returns_string(self) -> None:
        gen = SchemaDocsGenerator()
        content = gen.generate_tier_mdx("star")
        # Either schemas were discovered (table headers present) or not (empty tier).
        assert isinstance(content, str)
        if "schema(s)" in content and not content.count("0 schema(s)"):
            assert "| Column |" in content

    def test_write_creates_files(self, tmp_path: Path) -> None:
        gen = SchemaDocsGenerator(output_dir=tmp_path)
        written = gen.write(tiers=["star"])
        assert (tmp_path / "star-reference.mdx").exists()
        assert len(written) == 1
        assert written[0] == tmp_path / "star-reference.mdx"

    def test_write_all_tiers_creates_three_files(self, tmp_path: Path) -> None:
        gen = SchemaDocsGenerator(output_dir=tmp_path)
        written = gen.write()
        assert len(written) == 3
        for tier in ("raw", "staging", "star"):
            assert (tmp_path / f"{tier}-reference.mdx").exists()

    def test_tier_mdx_has_description_frontmatter(self) -> None:
        gen = SchemaDocsGenerator()
        content = gen.generate_tier_mdx("staging")
        assert "description:" in content


# ---------------------------------------------------------------------------
# ERDiagramGenerator
# ---------------------------------------------------------------------------


class TestERDiagramGenerator:
    def test_generate_mermaid_starts_with_erdiagram(self) -> None:
        gen = ERDiagramGenerator()
        content = gen.generate_mermaid()
        assert content.startswith("erDiagram")

    def test_generate_mdx_has_frontmatter(self) -> None:
        gen = ERDiagramGenerator()
        content = gen.generate_mdx()
        assert "---" in content
        assert "erDiagram" in content

    def test_generate_mdx_contains_mermaid_block(self) -> None:
        gen = ERDiagramGenerator()
        content = gen.generate_mdx()
        assert "```mermaid" in content

    def test_write_creates_file(self, tmp_path: Path) -> None:
        gen = ERDiagramGenerator(output_dir=tmp_path)
        path = gen.write()
        assert (tmp_path / "er-auto.mdx").exists()
        assert path == tmp_path / "er-auto.mdx"

    def test_generate_mermaid_with_filter_prefix(self) -> None:
        gen = ERDiagramGenerator()
        content = gen.generate_mermaid(filter_prefix="dim_")
        assert content.startswith("erDiagram")
        assert isinstance(content, str)

    def test_generate_mdx_has_title(self) -> None:
        gen = ERDiagramGenerator()
        content = gen.generate_mdx()
        assert "title:" in content


# ---------------------------------------------------------------------------
# LineageGenerator
# ---------------------------------------------------------------------------


class TestLineageGenerator:
    def test_lineage_mermaid_starts_with_flowchart(self) -> None:
        gen = LineageGenerator()
        content = gen.generate_mermaid()
        assert content.startswith("flowchart") or content.startswith("graph")

    def test_lineage_mermaid_is_string(self) -> None:
        gen = LineageGenerator()
        content = gen.generate_mermaid()
        assert isinstance(content, str)

    def test_lineage_write_creates_mdx(self, tmp_path: Path) -> None:
        gen = LineageGenerator(output_dir=tmp_path)
        written = gen.write()
        assert any(p.suffix == ".mdx" for p in written)
        assert (tmp_path / "lineage-auto.mdx").exists()

    def test_lineage_write_creates_json(self, tmp_path: Path) -> None:
        gen = LineageGenerator(output_dir=tmp_path)
        written = gen.write()
        assert (tmp_path / "lineage.json").exists()
        assert len(written) == 2

    def test_build_lineage_graph_returns_dict(self) -> None:
        gen = LineageGenerator()
        graph = gen.build_lineage_graph()
        assert isinstance(graph, dict)

    def test_generate_json_is_valid_json(self) -> None:
        import json

        gen = LineageGenerator()
        raw = gen.generate_json()
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_lineage_mdx_has_frontmatter(self) -> None:
        gen = LineageGenerator()
        content = gen.generate_mdx()
        assert content.startswith("---")
        assert "title:" in content


# ---------------------------------------------------------------------------
# DataDictionaryGenerator
# ---------------------------------------------------------------------------


class TestDataDictionaryGenerator:
    def test_data_dict_mdx_returns_string(self) -> None:
        gen = DataDictionaryGenerator()
        result = gen.generate_mdx("star")
        assert isinstance(result, str)

    def test_data_dict_has_frontmatter_or_fallback(self) -> None:
        gen = DataDictionaryGenerator()
        result = gen.generate_mdx("star")
        # Either proper MDX with frontmatter, or the "no schemas" fallback heading.
        assert "---" in result or result.startswith("#")

    def test_data_dict_write_creates_files(self, tmp_path: Path) -> None:
        gen = DataDictionaryGenerator(output_dir=tmp_path)
        written = gen.write()
        assert len(written) >= 1
        assert any(p.suffix == ".mdx" for p in written)

    def test_data_dict_write_default_tiers(self, tmp_path: Path) -> None:
        gen = DataDictionaryGenerator(output_dir=tmp_path)
        gen.write()
        for tier in ("star", "staging", "raw"):
            assert (tmp_path / f"{tier}.mdx").exists()

    def test_generate_json_returns_valid_json(self) -> None:
        import json

        gen = DataDictionaryGenerator()
        raw = gen.generate_json("star")
        parsed = json.loads(raw)
        assert isinstance(parsed, dict)

    def test_data_dict_staging_is_string(self) -> None:
        gen = DataDictionaryGenerator()
        result = gen.generate_mdx("staging")
        assert isinstance(result, str)
