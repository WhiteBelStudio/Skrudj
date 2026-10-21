"""Pterodactyl-friendly launcher for the Skrudj application."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent


def run_command(command: list[str]) -> None:
    """Run a command from the repository root and stop on failure."""
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    """Install the project in editable mode if needed, then start the app."""
    os.chdir(ROOT)

    try:
        import skrudj  # noqa: F401
    except ImportError:
        run_command(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "-e",
                ".",
            ]
        )

    run_command([sys.executable, "-m", "skrudj"])


if __name__ == "__main__":
    main()
