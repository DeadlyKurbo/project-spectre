"""Build AEGIS.exe and AEGIS-Setup.exe using PyInstaller.

Run from the aegis/ directory:
    python build_installer.py

Output:
    aegis/dist/AEGIS.exe         — Standalone launcher (no Python needed)
    aegis/dist/AEGIS-Setup.exe   — Installer that installs AEGIS.exe
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
    cmd = [sys.executable, "-m", "pyinstaller"] + args
    result = subprocess.run(cmd, cwd=AEGIS_DIR)
    if result.returncode != 0:
        raise SystemExit(result.returncode)


def main() -> None:
    print("Building A.E.G.I.S. installer...")
    print()

    # Ensure PyInstaller is available
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("Installing PyInstaller...")
        subprocess.run([sys.executable, "-m", "pip", "install", "pyinstaller"], check=True)

    DIST_DIR.mkdir(exist_ok=True)

    # Step 1: Build AEGIS.exe (standalone launcher)
    print("[1/2] Building AEGIS.exe (standalone launcher)...")
    run_pyinstaller([
        "--onefile",
        "--windowed",
        "--name", "AEGIS",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(AEGIS_DIR),
        "--clean",
        str(AEGIS_DIR / "aegis_app.py"),
    ])

    aegis_exe = DIST_DIR / "AEGIS.exe"
    if not aegis_exe.exists():
        raise SystemExit("AEGIS.exe was not created.")

    print(f"  -> {aegis_exe}")
    print()

    # Step 2: Build AEGIS-Setup.exe (installer that bundles AEGIS.exe)
    print("[2/2] Building AEGIS-Setup.exe (installer)...")
    run_pyinstaller([
        "--onefile",
        "--windowed",
        "--name", "AEGIS-Setup",
        "--distpath", str(DIST_DIR),
        "--workpath", str(BUILD_DIR),
        "--specpath", str(AEGIS_DIR),
        "--add-binary", f"{aegis_exe};.",
        "--clean",
        str(AEGIS_DIR / "installer_app.py"),
    ])

    setup_exe = DIST_DIR / "AEGIS-Setup.exe"
    if not setup_exe.exists():
        raise SystemExit("AEGIS-Setup.exe was not created.")

    print(f"  -> {setup_exe}")
    print()
    print("Done. Distribute AEGIS-Setup.exe to users — they double-click to install.")
