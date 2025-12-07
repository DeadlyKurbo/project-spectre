#!/usr/bin/env python3
"""Installer entry point for the A.E.G.I.S. welcome app.

Running this script from the repository root (``python aegis/run_me_to_install_aegis.py``)
will:
1. Validate the local Python version.
2. Create or reuse a virtual environment in ``aegis/.venv``.
3. Install the Python requirements inside that environment.
4. Build the downloadable ``aegis/dist/aegis-welcome.pyz`` archive.

The installer avoids modifying global site packages and keeps all
artifacts inside the ``aegis`` directory so it can be safely re-run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import venv
from pathlib import Path

import build_aegis_zipapp

AEGIS_DIR = Path(__file__).resolve().parent
VENV_DIR = AEGIS_DIR / ".venv"
REQUIREMENTS_FILE = AEGIS_DIR / "requirements.txt"


def _venv_python() -> Path:
    """Return the path to the virtual environment's Python executable."""

    if os.name == "nt":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


def _check_python_version(min_major: int = 3, min_minor: int = 10) -> None:
    """Exit with a clear message if the interpreter is too old."""

    current = sys.version_info
    if (current.major, current.minor) < (min_major, min_minor):
        raise SystemExit(
            f"Python {min_major}.{min_minor}+ is required. "
            f"Detected {current.major}.{current.minor}."
        )


def _create_or_verify_venv() -> Path:
    """Create a virtual environment if needed and return its Python path."""

    if not VENV_DIR.exists():
        print(f"[1/4] Creating virtual environment at {VENV_DIR}")
        venv.EnvBuilder(with_pip=True, upgrade_deps=True).create(VENV_DIR)
    python_executable = _venv_python()
    if not python_executable.exists():
        raise SystemExit(
            "Virtual environment is missing its Python executable. "
            "Remove .venv and rerun the installer."
        )
    return python_executable


def _install_requirements(python_executable: Path) -> None:
    """Install pinned dependencies inside the virtual environment."""

    if not REQUIREMENTS_FILE.exists():
        raise SystemExit("requirements.txt is missing from the AEGIS directory.")

    print("[2/4] Upgrading pip inside the virtual environment")
    subprocess.run(
        [str(python_executable), "-m", "pip", "install", "--upgrade", "pip"],
        check=True,
    )

    print(f"[3/4] Installing dependencies from {REQUIREMENTS_FILE}")
    subprocess.run(
        [str(python_executable), "-m", "pip", "install", "-r", str(REQUIREMENTS_FILE)],
        check=True,
    )


def _build_zipapp() -> Path:
    """Create the downloadable zipapp artifact and return its path."""

    print("[4/4] Building aegis/dist/aegis-welcome.pyz")
    return build_aegis_zipapp.build_zipapp()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install dependencies and build the A.E.G.I.S. welcome app zip archive.",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Install dependencies only without creating the zipapp artifact.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    _check_python_version()
    python_executable = _create_or_verify_venv()
    _install_requirements(python_executable)

    artifact = None
    if not args.skip_build:
        artifact = _build_zipapp()

    print("\nInstallation complete.")
    print(f"  Virtual environment: {VENV_DIR}")
    if artifact:
        print(f"  Downloadable archive: {artifact.relative_to(AEGIS_DIR)}")
    print(
        "\nNext steps: activate aegis/.venv and run the zipapp with your virtual environment's Python.\n"
        "Example (Unix/macOS):\n"
        "  source aegis/.venv/bin/activate\n"
        "  python aegis/dist/aegis-welcome.pyz\n\n"
        "Example (Windows):\n"
        "  aegis\\.venv\\Scripts\\activate\n"
        "  python aegis\\dist\\aegis-welcome.pyz"
    )


if __name__ == "__main__":
    main()
