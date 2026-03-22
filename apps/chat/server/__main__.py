"""Entry point for running the chat server directly."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def main() -> None:
    """Launch the Chainlit chat application."""
    app_path = Path(__file__).resolve().parent.parent / "chainlit_app.py"
    subprocess.run(
        [
            sys.executable, "-m", "chainlit", "run", str(app_path),
            "--host", "0.0.0.0", "--port", "8421",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
