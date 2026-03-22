"""Tests for agent assembly and system prompt."""

from __future__ import annotations


def test_build_system_prompt_includes_schema():
    """System prompt includes the schema context."""
    from apps.chat.server.prompts import build_system_prompt

    schema = "dim_player:\n  - player_id (INTEGER)\n  - full_name (VARCHAR)"
    prompt = build_system_prompt(schema)
    assert "dim_player" in prompt
    assert "player_id" in prompt
    assert "DuckDB" in prompt


def test_build_system_prompt_has_instructions():
    """System prompt includes usage instructions."""
    from apps.chat.server.prompts import build_system_prompt

    prompt = build_system_prompt("test schema")
    assert "run_sql" in prompt
    assert "plotly" in prompt
    assert "is_current" in prompt


def test_skills_dir_exists():
    """Skills directory is correctly located."""
    from apps.chat.server.agent import SKILLS_DIR

    assert SKILLS_DIR.exists()
    skill_md = SKILLS_DIR / "nba-data-analytics" / "SKILL.md"
    assert skill_md.exists()


def test_skill_md_has_valid_frontmatter():
    """SKILL.md has valid YAML frontmatter with name and description."""
    from apps.chat.server.agent import SKILLS_DIR

    skill_md = SKILLS_DIR / "nba-data-analytics" / "SKILL.md"
    content = skill_md.read_text()

    assert content.startswith("---")
    # Extract frontmatter
    parts = content.split("---", 2)
    assert len(parts) >= 3
    frontmatter = parts[1]
    assert "name: nba-data-analytics" in frontmatter
    assert "description:" in frontmatter
    # Ensure description is non-empty (not just the key)
    import yaml

    parsed = yaml.safe_load(frontmatter)
    assert parsed.get("description") and len(parsed["description"].strip()) > 0


def test_skill_has_references():
    """Skill directory has references subdirectory."""
    from apps.chat.server.agent import SKILLS_DIR

    refs = SKILLS_DIR / "nba-data-analytics" / "references"
    assert refs.exists()
    assert (refs / "schema-guide.md").exists()


def test_skill_has_scripts():
    """Skill directory has scripts subdirectory with metric calculator."""
    from apps.chat.server.agent import SKILLS_DIR

    scripts = SKILLS_DIR / "nba-data-analytics" / "scripts"
    assert scripts.exists()
    assert (scripts / "metric_calculator.py").exists()


def test_skill_md_references_query_cookbook():
    """SKILL.md body references the query cookbook for complex patterns."""
    from apps.chat.server.agent import SKILLS_DIR

    content = (SKILLS_DIR / "nba-data-analytics" / "SKILL.md").read_text()
    assert "query-cookbook" in content
    assert "read_file" in content


def test_skill_md_documents_metric_calculator():
    """SKILL.md documents the metric calculator API with function examples."""
    from apps.chat.server.agent import SKILLS_DIR

    content = (SKILLS_DIR / "nba-data-analytics" / "SKILL.md").read_text()
    assert "metric_calculator" in content
    assert "mc.true_shooting_pct" in content
