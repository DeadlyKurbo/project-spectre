"""Build AEGIS.exe — a single portable EXE. No installer, no Python required.

Run from the aegis/ directory:
    python build_installer.py

Output:
    aegis/dist/AEGIS.exe — Single file. Users double-click to run. Done.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

AEGIS_DIR = Path(__file__).resolve().parent
DIST_DIR = AEGIS_DIR / "dist"
BUILD_DIR = AEGIS_DIR / "build"


def run_pyinstaller(args: list[str]) -> None:
    """Run PyInstaller with the given arguments."""
    cmd = [sys.executable, "-m", "PyInstaller"] + args
    result = subprocess.run(cmd, cwd=AEGIS_DIR)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    print("Building A.E.G.I.S. (single EXE)...")
    print()

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    DIST_DIR.mkdir(exist_ok=True)

    print("Building AEGIS.exe...")
    run_pyinstaller([
        "--onefile",
        "--windowed",
        "--name", "AEGIS",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(AEGIS_DIR),
        "--hidden-import", "chat_store",
        "--clean",
        str(AEGIS_DIR / "aegis_app.py"),
    ])

    aegis_exe = DIST_DIR / "AEGIS.exe"
    if not aegis_exe.exists():
        raise SystemExit("AEGIS.exe was not created.")

    print(f"  -> {aegis_exe}")
    print()
    print("Done. Distribute AEGIS.exe - users double-click to run. No installation needed.")


if __name__ == "__main__":
    main()
