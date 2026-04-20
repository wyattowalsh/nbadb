"""Fixtures for notebook helper tests.

No database connection is needed — all tests use synthetic data or mocks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# notebooks/ is not on PYTHONPATH; make it importable for nbadb_utils.
_NOTEBOOKS_DIR = Path(__file__).resolve().parents[3] / "notebooks"

# Add at module level so skipif decorators can resolve imports at collection time.
if str(_NOTEBOOKS_DIR) not in sys.path:
    sys.path.insert(0, str(_NOTEBOOKS_DIR))


@pytest.fixture(autouse=True)
def _patch_notebooks_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Temporarily add the notebooks directory to sys.path."""
    monkeypatch.syspath_prepend(str(_NOTEBOOKS_DIR))
