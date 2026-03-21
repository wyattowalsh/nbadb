"""Unit tests for pure functions extracted from the nbadb companion notebooks.

Functions tested:
  - gaussian_aging          (nba_aging_curves.ipynb)
  - DIS formula             (nba_defense_decoded.ipynb)
  - draw_court_plotly       (nbadb_utils.py — shared)
  - takeaway                (nbadb_utils.py — shared)
  - render_cross_links      (nbadb_utils.py — shared)
  - get_connection          (nbadb_utils.py — shared)
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

# ---------------------------------------------------------------------------
# Inline definitions for functions still living inside notebook cells
# ---------------------------------------------------------------------------


def gaussian_aging(
    x: float | np.ndarray, a: float, peak: float, width: float, c: float,
) -> float | np.ndarray:
    """Gaussian aging curve: performance peaks at *peak* and decays with *width*.

    Taken from nba_aging_curves.ipynb, cell 11.
    """
    return a * np.exp(-0.5 * ((x - peak) / width) ** 2) + c


def dis_score(pc1_norm: float, pc2_norm: float, pc3_norm: float) -> float:
    """Defensive Impact Score from nba_defense_decoded.ipynb, cell 23.

    DIS = 0.35 * PC1_norm + 0.35 * PC2_norm + 0.30 * PC3_norm
    where each PCx_norm is min-max normalized to [0, 100].
    """
    return 0.35 * pc1_norm + 0.35 * pc2_norm + 0.30 * pc3_norm


# ===================================================================
# gaussian_aging
# ===================================================================


class TestGaussianAging:
    """Tests for the Gaussian aging model."""

    def test_maximum_at_peak(self) -> None:
        """At x == peak the function should return a + c."""
        a, peak, width, c = 10.0, 27.0, 5.0, 3.0
        result = gaussian_aging(peak, a, peak, width, c)
        assert result == pytest.approx(a + c)

    def test_symmetry(self) -> None:
        """Output is symmetric around the peak."""
        a, peak, width, c = 8.0, 27.0, 4.0, 2.0
        left = gaussian_aging(peak - 2, a, peak, width, c)
        right = gaussian_aging(peak + 2, a, peak, width, c)
        assert left == pytest.approx(right)

    def test_output_always_ge_baseline(self) -> None:
        """Output is always >= c for a >= 0."""
        a, peak, width, c = 12.0, 28.0, 6.0, 1.5
        xs = np.linspace(15, 45, 200)
        results = gaussian_aging(xs, a, peak, width, c)
        assert np.all(results >= c - 1e-12)

    def test_approaches_baseline_far_from_peak(self) -> None:
        """At extreme x values the output approaches the baseline c."""
        a, peak, width, c = 10.0, 27.0, 4.0, 2.0
        far_away = gaussian_aging(1000.0, a, peak, width, c)
        assert far_away == pytest.approx(c, abs=1e-6)

    def test_zero_amplitude_always_baseline(self) -> None:
        """With a == 0, output is always exactly c."""
        c = 5.0
        xs = np.linspace(18, 40, 50)
        results = gaussian_aging(xs, a=0.0, peak=27.0, width=5.0, c=c)
        np.testing.assert_allclose(results, c)

    @pytest.mark.parametrize(
        "offset",
        [1, 3, 5, 10],
    )
    def test_decreasing_away_from_peak(self, offset: int) -> None:
        """Value at peak is always >= value at peak +/- offset."""
        a, peak, width, c = 10.0, 27.0, 5.0, 2.0
        peak_val = gaussian_aging(peak, a, peak, width, c)
        assert gaussian_aging(peak + offset, a, peak, width, c) <= peak_val + 1e-12
        assert gaussian_aging(peak - offset, a, peak, width, c) <= peak_val + 1e-12

    def test_vectorized(self) -> None:
        """Function works with numpy arrays."""
        a, peak, width, c = 10.0, 27.0, 5.0, 2.0
        xs = np.array([20.0, 25.0, 27.0, 30.0, 35.0])
        results = gaussian_aging(xs, a, peak, width, c)
        assert results.shape == (5,)
        assert results[2] == pytest.approx(a + c)  # peak index


# ===================================================================
# DIS formula
# ===================================================================


class TestDISFormula:
    """Tests for the Defensive Impact Score composite."""

    def test_all_zeros_gives_zero(self) -> None:
        assert dis_score(0.0, 0.0, 0.0) == pytest.approx(0.0)

    def test_all_hundreds_gives_hundred(self) -> None:
        # 0.35*100 + 0.35*100 + 0.30*100 = 35 + 35 + 30 = 100
        assert dis_score(100.0, 100.0, 100.0) == pytest.approx(100.0)

    @pytest.mark.parametrize(
        "pc1, pc2, pc3",
        [
            (0, 0, 0),
            (50, 50, 50),
            (100, 100, 100),
            (0, 100, 0),
            (100, 0, 0),
            (0, 0, 100),
            (25, 75, 50),
            (100, 50, 25),
        ],
    )
    def test_output_in_range(self, pc1: float, pc2: float, pc3: float) -> None:
        """DIS is always in [0, 100] when inputs are in [0, 100]."""
        result = dis_score(pc1, pc2, pc3)
        assert 0.0 <= result <= 100.0 + 1e-12

    def test_weights_sum_to_one(self) -> None:
        """Sanity: 0.35 + 0.35 + 0.30 == 1.0."""
        assert pytest.approx(1.0) == 0.35 + 0.35 + 0.30

    def test_single_component_contribution(self) -> None:
        """Only PC1 at 100, others at 0 -> 35."""
        assert dis_score(100.0, 0.0, 0.0) == pytest.approx(35.0)
        assert dis_score(0.0, 100.0, 0.0) == pytest.approx(35.0)
        assert dis_score(0.0, 0.0, 100.0) == pytest.approx(30.0)

    def test_midpoint(self) -> None:
        """All components at 50 -> 50."""
        assert dis_score(50.0, 50.0, 50.0) == pytest.approx(50.0)


# ===================================================================
# nbadb_utils shared functions (import from nbadb_utils if available)
# ===================================================================


def _try_import_utils():
    """Attempt to import nbadb_utils; return None if not yet created."""
    try:
        import nbadb_utils  # noqa: F811

        return nbadb_utils
    except ImportError:
        return None


_UTILS_AVAILABLE = _try_import_utils() is not None
_SKIP_REASON = "nbadb_utils not importable (plotly/duckdb not installed)"


# ---------------------------------------------------------------------------
# draw_court_plotly
# ---------------------------------------------------------------------------


class TestDrawCourtPlotly:
    """Tests for draw_court_plotly (shared utility)."""

    @pytest.fixture(autouse=True)
    def _load_utils(self):
        self.utils = _try_import_utils()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_returns_list(self) -> None:
        shapes = self.utils.draw_court_plotly()
        assert isinstance(shapes, list)

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_elements_are_dicts_with_type(self) -> None:
        shapes = self.utils.draw_court_plotly()
        for shape in shapes:
            assert isinstance(shape, dict)
            assert "type" in shape

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_contains_expected_shape_types(self) -> None:
        shapes = self.utils.draw_court_plotly()
        types_found = {s["type"] for s in shapes}
        expected = {"rect", "circle", "line", "path"}
        assert types_found & expected, f"Expected some of {expected}, got {types_found}"

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_non_empty(self) -> None:
        shapes = self.utils.draw_court_plotly()
        assert len(shapes) >= 5


# ---------------------------------------------------------------------------
# takeaway
# ---------------------------------------------------------------------------


class TestTakeaway:
    """Tests for the takeaway display helper."""

    @pytest.fixture(autouse=True)
    def _load_utils(self):
        self.utils = _try_import_utils()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_calls_display(self) -> None:
        with patch("nbadb_utils.display") as mock_display:
            self.utils.takeaway("Test message")
            mock_display.assert_called_once()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_html_contains_key_takeaway(self) -> None:
        with patch("nbadb_utils.display") as mock_display:
            self.utils.takeaway("Test message")
            html_obj = mock_display.call_args[0][0]
            assert "Key Takeaway:" in html_obj.data

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_html_contains_provided_text(self) -> None:
        msg = "Scoring peaks at age 27."
        with patch("nbadb_utils.display") as mock_display:
            self.utils.takeaway(msg)
            html_obj = mock_display.call_args[0][0]
            assert msg in html_obj.data


# ---------------------------------------------------------------------------
# render_cross_links
# ---------------------------------------------------------------------------


class TestRenderCrossLinks:
    """Tests for cross-link table rendering."""

    @pytest.fixture(autouse=True)
    def _load_utils(self):
        self.utils = _try_import_utils()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_returns_string(self) -> None:
        result = self.utils.render_cross_links(current="nba_aging_curves")
        assert isinstance(result, str)

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_contains_table_headers(self) -> None:
        result = self.utils.render_cross_links(current="nba_aging_curves")
        assert "|" in result  # markdown table pipe

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_excludes_current_notebook(self) -> None:
        result = self.utils.render_cross_links(current="nba_aging_curves")
        # The current notebook name should not appear as a link row
        assert "nba_aging_curves" not in result or "this notebook" in result.lower()


# ---------------------------------------------------------------------------
# get_connection
# ---------------------------------------------------------------------------


class TestGetConnection:
    """Tests for the database connection helper."""

    @pytest.fixture(autouse=True)
    def _load_utils(self):
        self.utils = _try_import_utils()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_raises_when_no_db_found(self) -> None:
        with patch("nbadb_utils.Path.exists", return_value=False), pytest.raises(FileNotFoundError):
                self.utils.get_connection()

    @pytest.mark.skipif(not _UTILS_AVAILABLE, reason=_SKIP_REASON)
    def test_calls_duckdb_connect(self) -> None:
        mock_conn = MagicMock()
        with (
            patch("nbadb_utils.Path.exists", return_value=True),
            patch("nbadb_utils.duckdb.connect", return_value=mock_conn) as mock_connect,
        ):
            conn = self.utils.get_connection()
            mock_connect.assert_called_once()
            assert conn is mock_conn
