"""Unit tests for nbadb.docs_gen.lineage module."""

from __future__ import annotations

import json

from nbadb.docs_gen.lineage import LineageGenerator

# ---------------------------------------------------------------------------
# _table_name_from_class
# ---------------------------------------------------------------------------


class TestTableNameFromClass:
    def test_simple_schema_suffix(self):
        gen = LineageGenerator()
        assert gen._table_name_from_class("FactGameResultSchema") == "fact_game_result"

    def test_model_suffix(self):
        gen = LineageGenerator()
        assert gen._table_name_from_class("DimPlayerModel") == "dim_player"

    def test_no_suffix(self):
        gen = LineageGenerator()
        assert gen._table_name_from_class("FactDraft") == "fact_draft"

    def test_acronym_uppercase_chars(self):
        gen = LineageGenerator()
        # Each uppercase char gets an underscore prefix
        assert gen._table_name_from_class("ISTStandingsSchema") == "i_s_t_standings"

    def test_single_word(self):
        gen = LineageGenerator()
        assert gen._table_name_from_class("PlayerSchema") == "player"

    def test_multiple_suffixes_only_strips_one(self):
        gen = LineageGenerator()
        # "SchemaModel" — strips "Model" first since it comes second in the loop
        result = gen._table_name_from_class("FooSchemaModel")
        # Strips "Model" suffix, leaves "FooSchema"
        assert result == "foo_schema"


# ---------------------------------------------------------------------------
# build_lineage_graph
# ---------------------------------------------------------------------------


class TestBuildLineageGraph:
    def test_returns_dict(self):
        gen = LineageGenerator()
        graph = gen.build_lineage_graph()
        assert isinstance(graph, dict)
        assert graph

    def test_graph_entries_have_expected_keys(self):
        gen = LineageGenerator()
        graph = gen.build_lineage_graph()
        for _table_name, info in graph.items():
            assert "class" in info
            assert "columns" in info
            assert isinstance(info["columns"], dict)

    def test_graph_includes_source_metadata(self):
        gen = LineageGenerator()
        graph = gen.build_lineage_graph()

        assert graph["fact_player_game_advanced"]["columns"]["game_id"] == {
            "endpoint": "BoxScoreAdvancedV3",
            "result_set": "PlayerStats",
            "field": "GAME_ID",
            "fk_ref": "dim_game.game_id",
        }


# ---------------------------------------------------------------------------
# generate_mermaid
# ---------------------------------------------------------------------------


class TestGenerateMermaid:
    def test_starts_with_flowchart(self):
        gen = LineageGenerator()
        mermaid = gen.generate_mermaid()
        assert isinstance(mermaid, str)
        assert mermaid.startswith("flowchart LR")

    def test_contains_newlines(self):
        gen = LineageGenerator()
        mermaid = gen.generate_mermaid()
        # Should have at least the header line
        assert "\n" in mermaid or mermaid == "flowchart LR"

    def test_contains_table_lineage_edges(self):
        gen = LineageGenerator()
        mermaid = gen.generate_mermaid()

        assert "BoxScoreAdvancedV3 --> fact_player_game_advanced" in mermaid


# ---------------------------------------------------------------------------
# generate_json
# ---------------------------------------------------------------------------


class TestGenerateJson:
    def test_returns_valid_json(self):
        gen = LineageGenerator()
        result = gen.generate_json()
        parsed = json.loads(result)
        assert isinstance(parsed, dict)

    def test_json_contains_schema_lineage(self):
        gen = LineageGenerator()
        parsed = json.loads(gen.generate_json())
        # Combined JSON includes schema_lineage and/or sql_lineage per table
        schema_tables = {k for k, v in parsed.items() if "schema_lineage" in v}
        assert schema_tables, "Expected at least one table with schema_lineage"

    def test_json_contains_sql_lineage(self):
        gen = LineageGenerator()
        parsed = json.loads(gen.generate_json())
        sql_tables = {k for k, v in parsed.items() if "sql_lineage" in v}
        assert sql_tables, "Expected at least one table with sql_lineage"


# ---------------------------------------------------------------------------
# generate_mdx
# ---------------------------------------------------------------------------


class TestGenerateMdx:
    def test_has_frontmatter(self):
        gen = LineageGenerator()
        mdx = gen.generate_mdx()
        assert mdx.startswith("---")
        assert "title: Data Lineage" in mdx

    def test_has_mermaid_block(self):
        gen = LineageGenerator()
        mdx = gen.generate_mdx()
        assert "```mermaid" in mdx

    def test_has_section_headers(self):
        gen = LineageGenerator()
        mdx = gen.generate_mdx()
        assert "# Data Lineage" in mdx
        assert "## Extraction Layer" in mdx
        assert "## Transform Layer" in mdx
        assert "## Column-Level Lineage" in mdx


# ---------------------------------------------------------------------------
# write
# ---------------------------------------------------------------------------


class TestWrite:
    def test_writes_files(self, tmp_path):
        gen = LineageGenerator(output_dir=tmp_path)
        written = gen.write()
        assert len(written) == 2
        assert (tmp_path / "lineage-auto.mdx").exists()
        assert (tmp_path / "lineage.json").exists()

    def test_written_json_is_valid(self, tmp_path):
        gen = LineageGenerator(output_dir=tmp_path)
        gen.write()
        content = (tmp_path / "lineage.json").read_text(encoding="utf-8")
        parsed = json.loads(content)
        assert isinstance(parsed, dict)
        assert parsed

    def test_written_mdx_has_frontmatter(self, tmp_path):
        gen = LineageGenerator(output_dir=tmp_path)
        gen.write()
        content = (tmp_path / "lineage-auto.mdx").read_text(encoding="utf-8")
        assert content.startswith("---")
