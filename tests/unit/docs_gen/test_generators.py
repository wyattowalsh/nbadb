from __future__ import annotations

from typing import TYPE_CHECKING

import pandera.polars as pa

from nbadb.docs_gen.data_dictionary import DataDictionaryGenerator
from nbadb.docs_gen.er_diagram import ERDiagramGenerator
from nbadb.docs_gen.lineage import LineageGenerator
from nbadb.docs_gen.schema_docs import SchemaDocsGenerator
from nbadb.schemas.base import BaseSchema
from nbadb.schemas.registry import _staging_schema_registry, _star_schema_registry

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
        assert (tmp_path / "star-reference.json").exists()
        assert (tmp_path / "star-reference.mdx").exists()
        assert len(written) == 2
        assert written == [
            tmp_path / "star-reference.json",
            tmp_path / "star-reference.mdx",
        ]

    def test_write_all_tiers_creates_three_files(self, tmp_path: Path) -> None:
        gen = SchemaDocsGenerator(output_dir=tmp_path)
        written = gen.write()
        assert len(written) == 6
        for tier in ("raw", "staging", "star"):
            assert (tmp_path / f"{tier}-reference.json").exists()
            assert (tmp_path / f"{tier}-reference.mdx").exists()

    def test_tier_mdx_has_description_frontmatter(self) -> None:
        gen = SchemaDocsGenerator()
        content = gen.generate_tier_mdx("staging")
        assert "description:" in content

    def test_tier_json_has_no_empty_column_descriptions(self) -> None:
        gen = SchemaDocsGenerator()

        for tier in ("raw", "staging", "star"):
            payload = gen.generate_tier_json(tier)
            columns = [column for table in payload for column in table["columns"]]
            assert columns
            assert all(column["description"] for column in columns)
            assert all(
                column["description_source"] in {"metadata", "generated"} for column in columns
            )

    def test_tier_json_uses_public_registry_names(self) -> None:
        gen = SchemaDocsGenerator()

        staging_tables = {entry["table_name"] for entry in gen.generate_tier_json("staging")}
        star_tables = {entry["table_name"] for entry in gen.generate_tier_json("star")}

        assert staging_tables == set(_staging_schema_registry())
        assert star_tables == set(_star_schema_registry())
        assert all(table.startswith("stg_") for table in staging_tables)
        assert not any(table.startswith("staging_") for table in staging_tables)
        assert "fact_estimated_metrics" not in star_tables
        assert not any(table.startswith("_") or table.endswith("_base") for table in star_tables)


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

    def test_video_details_columns_use_effective_inherited_metadata(self) -> None:
        tables = ERDiagramGenerator().generate_json()["tables"]

        for table_name in ("fact_video_details", "fact_video_details_asset"):
            columns = {column["name"]: column for column in tables[table_name]["columns"]}
            assert columns["request_player_id"]["key"] == "FK"
            assert columns["request_team_id"]["key"] == "FK"

    def test_dynamic_video_tables_have_no_fabricated_primary_keys(self) -> None:
        tables = ERDiagramGenerator().generate_json()["tables"]

        for table_name in (
            "fact_video_details",
            "fact_video_details_asset",
            "fact_video_events",
            "fact_video_events_asset",
            "fact_video_status",
        ):
            assert all(column["key"] != "PK" for column in tables[table_name]["columns"])

        video_status_columns = {
            column["name"]: column for column in tables["fact_video_status"]["columns"]
        }
        assert video_status_columns["visitor_team_id"]["key"] == ""

    def test_primary_keys_require_explicit_metadata(self) -> None:
        class ExplicitKeySchema(BaseSchema):
            record_id: int = pa.Field(metadata={"primary_key": True})
            related_id: int = pa.Field()

        columns = {
            column["name"]: column
            for column in ERDiagramGenerator()._extract_columns(ExplicitKeySchema)
        }

        assert columns["record_id"]["key"] == "PK"
        assert columns["related_id"]["key"] == ""

    def test_video_details_relationships_include_player_and_team_foreign_keys(self) -> None:
        tables = ERDiagramGenerator().generate_json()["tables"]
        expected = {
            ("request_player_id", "dim_player", "player_id"),
            ("request_team_id", "dim_team", "team_id"),
        }

        for table_name in ("fact_video_details", "fact_video_details_asset"):
            relationships = {
                (relationship["from_col"], relationship["to_table"], relationship["to_col"])
                for relationship in tables[table_name]["relationships"]
            }
            assert relationships == expected

    def test_mermaid_preserves_multiple_foreign_keys_between_same_tables(self) -> None:
        content = ERDiagramGenerator().generate_mermaid()

        assert 'dim_team ||--o{ fact_game_result : "home_team_id"' in content
        assert 'dim_team ||--o{ fact_game_result : "visitor_team_id"' in content

    def test_effective_pandera_aliases_are_emitted(self) -> None:
        tables = ERDiagramGenerator().generate_json()["tables"]
        columns = {column["name"] for column in tables["fact_player_matchups_detail"]["columns"]}

        assert "l" in columns
        assert "losses" not in columns


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
    def test_tier_json_has_no_empty_field_descriptions(self) -> None:
        gen = DataDictionaryGenerator()

        for tier in ("raw", "staging", "star"):
            payload = gen.generate_tier_json(tier)
            fields = [field for table in payload for field in table["fields"]]
            assert fields
            assert all(field["description"] for field in fields)
            assert all(field["description_source"] in {"metadata", "generated"} for field in fields)

    def test_tier_json_uses_public_registry_names(self) -> None:
        gen = DataDictionaryGenerator()

        staging_tables = {entry["table_name"] for entry in gen.generate_tier_json("staging")}
        star_tables = {entry["table_name"] for entry in gen.generate_tier_json("star")}

        assert staging_tables == set(_staging_schema_registry())
        assert star_tables == set(_star_schema_registry())
        assert all(table.startswith("stg_") for table in staging_tables)
        assert not any(table.startswith("staging_") for table in staging_tables)
        assert "fact_estimated_metrics" not in star_tables

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
