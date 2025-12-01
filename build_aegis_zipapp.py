"""Build a downloadable A.E.G.I.S. welcome app zip archive.

This script packages the minimal Tkinter welcome UI into a standalone
``.pyz`` archive that can be downloaded directly from the repository and
executed with Python 3.
"""

from __future__ import annotations

import shutil
import tempfile
import zipapp
from pathlib import Path

APP_NAME = "aegis-welcome.pyz"
ROOT_DIR = Path(__file__).resolve().parent
DIST_DIR = ROOT_DIR / "dist"


def build_zipapp() -> Path:
    """Package the A.E.G.I.S. welcome app into a zipapp archive."""

    DIST_DIR.mkdir(exist_ok=True)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        shutil.copy(ROOT_DIR / "aegis_app.py", temp_path / "aegis_app.py")

        target = DIST_DIR / APP_NAME
        zipapp.create_archive(
            source=temp_path,
            target=target,
            main="aegis_app:run",
            interpreter="/usr/bin/env python3",
            compressed=True,
        )

    return target


if __name__ == "__main__":
    artifact = build_zipapp()
    print(f"Built {artifact.relative_to(ROOT_DIR)}")
