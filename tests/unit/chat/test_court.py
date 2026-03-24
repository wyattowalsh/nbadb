"""Tests for NBA court visualization helpers."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

# Load court module dynamically (skill script, not a package).
_COURT_PATH = (
    Path(__file__).resolve().parents[3]
    / "apps"
    / "chat"
    / "skills"
    / "nba-data-analytics"
    / "scripts"
    / "court.py"
)
_spec = importlib.util.spec_from_file_location("court", _COURT_PATH)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

draw_court = _mod.draw_court
shot_chart = _mod.shot_chart
shot_heatmap = _mod.shot_heatmap
zone_chart = _mod.zone_chart
compare_shots = _mod.compare_shots


# -- helpers -------------------------------------------------------------------


def _make_shot_df(n: int = 100, *, seed: int = 42) -> pd.DataFrame:
    """Synthetic shot data with loc_x, loc_y, shot_made_flag."""
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        {
            "loc_x": rng.integers(-250, 250, size=n),
            "loc_y": rng.integers(-50, 420, size=n),
            "shot_made_flag": rng.integers(0, 2, size=n),
        }
    )


def _make_zone_df() -> pd.DataFrame:
    """Synthetic zone-aggregated data."""
    rows = [
        ("Restricted Area", "", 0.62, 0.58),
        ("Mid-Range", "Center(C)", 0.40, 0.42),
        ("Above the Break 3", "Center(C)", 0.37, 0.36),
        ("Left Corner 3", "", 0.41, 0.39),
        ("Right Corner 3", "", 0.35, 0.39),
    ]
    return pd.DataFrame(rows, columns=["zone_basic", "zone_area", "fg_pct", "league_avg_fg_pct"])


# -- TestDrawCourt -------------------------------------------------------------


class TestDrawCourt:
    def teardown_method(self) -> None:
        plt.close("all")

    def test_returns_axes(self) -> None:
        ax = draw_court()
        assert isinstance(ax, plt.Axes)

    def test_creates_figure_when_no_ax(self) -> None:
        ax = draw_court()
        fig = ax.get_figure()
        assert fig is not None

    def test_uses_provided_axes(self) -> None:
        fig, ax = plt.subplots()
        returned = draw_court(ax=ax)
        assert returned is ax

    def test_has_expected_patches(self) -> None:
        ax = draw_court()
        patch_types = {type(p).__name__ for p in ax.patches}
        assert "Circle" in patch_types
        assert "Arc" in patch_types
        assert "Rectangle" in patch_types

    def test_respects_color_arg(self) -> None:
        ax = draw_court(color="yellow")
        # The hoop circle should use the specified colour
        circles = [p for p in ax.patches if isinstance(p, matplotlib.patches.Circle)]
        assert len(circles) >= 1
        assert circles[0].get_edgecolor()[:3] != (1.0, 1.0, 1.0)  # not white

    def test_respects_lw_arg(self) -> None:
        ax = draw_court(lw=3.0)
        circles = [p for p in ax.patches if isinstance(p, matplotlib.patches.Circle)]
        assert circles[0].get_linewidth() == 3.0

    def test_outer_lines_adds_boundary(self) -> None:
        ax_no = draw_court(outer_lines=False)
        ax_yes = draw_court(outer_lines=True)
        rects_no = [p for p in ax_no.patches if isinstance(p, matplotlib.patches.Rectangle)]
        rects_yes = [p for p in ax_yes.patches if isinstance(p, matplotlib.patches.Rectangle)]
        assert len(rects_yes) > len(rects_no)

    def test_axes_limits(self) -> None:
        ax = draw_court()
        assert ax.get_xlim() == (-250, 250)
        assert ax.get_ylim() == (-50, 420)

    def test_aspect_equal(self) -> None:
        ax = draw_court()
        # set_aspect("equal") stores 1.0 internally
        assert ax.get_aspect() in ("equal", 1.0)


# -- TestShotChart -------------------------------------------------------------


class TestShotChart:
    def teardown_method(self) -> None:
        plt.close("all")

    def test_returns_figure(self) -> None:
        df = _make_shot_df()
        fig = shot_chart(df)
        assert isinstance(fig, plt.Figure)

    def test_handles_empty_df(self) -> None:
        df = pd.DataFrame(columns=["loc_x", "loc_y", "shot_made_flag"])
        fig = shot_chart(df)
        assert isinstance(fig, plt.Figure)

    def test_has_scatter_collections(self) -> None:
        df = _make_shot_df()
        fig = shot_chart(df)
        ax = fig.axes[0]
        # PathCollections from scatter calls
        collections = ax.collections
        assert len(collections) >= 2  # made + missed

    def test_title_applied(self) -> None:
        df = _make_shot_df()
        fig = shot_chart(df, title="Test Title")
        ax = fig.axes[0]
        assert ax.get_title() == "Test Title"


# -- TestShotHeatmap -----------------------------------------------------------


class TestShotHeatmap:
    def teardown_method(self) -> None:
        plt.close("all")

    def test_returns_figure(self) -> None:
        df = _make_shot_df()
        fig = shot_heatmap(df)
        assert isinstance(fig, plt.Figure)

    def test_handles_empty_df(self) -> None:
        df = pd.DataFrame(columns=["loc_x", "loc_y"])
        fig = shot_heatmap(df)
        assert isinstance(fig, plt.Figure)

    def test_hexbin_collection_present(self) -> None:
        df = _make_shot_df()
        fig = shot_heatmap(df)
        ax = fig.axes[0]
        # hexbin creates a PolyCollection
        poly_collections = [c for c in ax.collections if type(c).__name__ == "PolyCollection"]
        assert len(poly_collections) >= 1

    def test_respects_bins_param(self) -> None:
        df = _make_shot_df()
        fig1 = shot_heatmap(df, bins=10)
        fig2 = shot_heatmap(df, bins=40)
        # Both should produce valid figures
        assert isinstance(fig1, plt.Figure)
        assert isinstance(fig2, plt.Figure)


# -- TestZoneChart -------------------------------------------------------------


class TestZoneChart:
    def teardown_method(self) -> None:
        plt.close("all")

    def test_returns_figure(self) -> None:
        df = _make_zone_df()
        fig = zone_chart(df)
        assert isinstance(fig, plt.Figure)

    def test_handles_empty_df(self) -> None:
        df = pd.DataFrame(columns=["zone_basic", "zone_area", "fg_pct", "league_avg_fg_pct"])
        fig = zone_chart(df)
        assert isinstance(fig, plt.Figure)

    def test_places_zone_circles(self) -> None:
        df = _make_zone_df()
        fig = zone_chart(df)
        ax = fig.axes[0]
        # Should have court patches + zone circles
        circles = [p for p in ax.patches if isinstance(p, matplotlib.patches.Circle)]
        # At least the hoop + zone circles from our 5-row df
        assert len(circles) >= 6  # 1 hoop + 5 zones


# -- TestCompareShotCharts -----------------------------------------------------


class TestCompareShotCharts:
    def teardown_method(self) -> None:
        plt.close("all")

    def test_returns_figure(self) -> None:
        df1 = _make_shot_df(80, seed=1)
        df2 = _make_shot_df(80, seed=2)
        fig = compare_shots(df1, df2)
        assert isinstance(fig, plt.Figure)

    def test_has_two_subplots(self) -> None:
        df1 = _make_shot_df(80, seed=1)
        df2 = _make_shot_df(80, seed=2)
        fig = compare_shots(df1, df2)
        # 2 main axes + potentially 2 colorbar axes
        main_axes = [ax for ax in fig.axes if ax.get_label() != "<colorbar>"]
        assert len(main_axes) >= 2

    def test_handles_empty_dfs(self) -> None:
        empty = pd.DataFrame(columns=["loc_x", "loc_y"])
        fig = compare_shots(empty, empty)
        assert isinstance(fig, plt.Figure)

    def test_subplot_titles(self) -> None:
        df1 = _make_shot_df(50, seed=1)
        df2 = _make_shot_df(50, seed=2)
        fig = compare_shots(df1, df2, name1="LeBron", name2="Curry")
        titles = [ax.get_title() for ax in fig.axes]
        assert "LeBron" in titles
        assert "Curry" in titles
