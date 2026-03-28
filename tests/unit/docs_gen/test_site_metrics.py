from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from nbadb.docs_gen.site_metrics import (
    build_site_metrics,
    generate_site_metrics_module,
    resolve_site_metrics_output_path,
)


def test_build_site_metrics_counts_docs_and_outputs(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "index.mdx").write_text("---\ntitle: Home\n---\n", encoding="utf-8")
    (tmp_path / "guides").mkdir()
    (tmp_path / "guides" / "overview.mdx").write_text("---\ntitle: Guide\n---\n", encoding="utf-8")

    fake_transformers = [
        SimpleNamespace(output_table="dim_player"),
        SimpleNamespace(output_table="fact_game_result"),
        SimpleNamespace(output_table="agg_player_season"),
        SimpleNamespace(output_table="analytics_player_game_complete"),
        SimpleNamespace(output_table="analytics_player_game_complete"),
    ]

    with (
        patch("nbadb.docs_gen.site_metrics._count_tables", return_value=4),
        patch("nbadb.docs_gen.site_metrics._count_endpoints", return_value=12),
        patch(
            "nbadb.docs_gen.site_metrics.discover_all_transformers",
            return_value=fake_transformers,
        ),
    ):
        metrics = build_site_metrics(tmp_path)

    assert [metric.label for metric in metrics] == [
        "Models",
        "Extractors",
        "Docs Pages",
        "Derived Models",
    ]
    assert [metric.value for metric in metrics] == ["4", "12", "2", "2"]


def test_generate_site_metrics_module_emits_typescript(tmp_path) -> None:  # noqa: ANN001
    (tmp_path / "index.mdx").write_text("---\ntitle: Home\n---\n", encoding="utf-8")

    with (
        patch("nbadb.docs_gen.site_metrics._count_tables", return_value=0),
        patch("nbadb.docs_gen.site_metrics._count_endpoints", return_value=12),
        patch("nbadb.docs_gen.site_metrics.discover_all_transformers", return_value=[]),
    ):
        content = generate_site_metrics_module(tmp_path)

    assert 'import type { SiteMetric } from "@/lib/site-config";' in content
    assert '"label": "Docs Pages"' in content
    assert '"value": "1"' in content


def test_resolve_site_metrics_output_path_for_docs_root() -> None:
    path = resolve_site_metrics_output_path(Path("docs/content/docs"))
    assert path.as_posix().endswith("docs/lib/site-metrics.generated.ts")
