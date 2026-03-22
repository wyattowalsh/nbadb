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


def test_metric_calculator_functions():
    """Metric calculator has correct formulas."""
    import importlib.util

    from apps.chat.server.agent import SKILLS_DIR

    spec = importlib.util.spec_from_file_location(
        "metric_calculator",
        SKILLS_DIR / "nba-data-analytics" / "scripts" / "metric_calculator.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    true_shooting_pct = mod.true_shooting_pct
    effective_fg_pct = mod.effective_fg_pct

    # TS% for 30 pts on 20 FGA and 10 FTA
    ts = true_shooting_pct(30, 20, 10)
    assert 0.0 < ts < 1.0

    # eFG% for 8 FGM, 3 3PM, 18 FGA
    efg = effective_fg_pct(8, 3, 18)
    expected = (8 + 0.5 * 3) / 18
    assert abs(efg - expected) < 0.001

    # Edge case: zero attempts
    assert true_shooting_pct(0, 0, 0) == 0.0
    assert effective_fg_pct(0, 0, 0) == 0.0
