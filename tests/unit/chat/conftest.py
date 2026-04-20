"""Conftest for chat app tests — ensures apps/ is importable."""

from __future__ import annotations

import sys
from pathlib import Path

# Add the project root to sys.path so `apps.chat` is importable
_project_root = Path(__file__).resolve().parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))
