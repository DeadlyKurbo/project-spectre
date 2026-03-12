"""Generate AEGIS app assets: shield icon and tactical background.

Run from aegis/ directory:
    pip install pillow
    python generate_assets.py

Creates:
    assets/aegis_icon.ico  — Shield logo for window/taskbar
    assets/background.png  — Dark tactical grid for chat area
"""

from __future__ import annotations

import math
from pathlib import Path

try:
    from PIL import Image, ImageDraw
except ImportError:
    raise SystemExit("Install Pillow first: pip install pillow")

ASSETS_DIR = Path(__file__).resolve().parent / "assets"
ACCENT = (0, 150, 255)  # Neon blue
ACCENT_DIM = (0, 80, 140)
BG_DARK = (18, 20, 24)
GRID_COLOR = (35, 45, 55)
GRID_ACCENT = (0, 80, 120)


def _draw_shield(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int) -> None:
    """Draw a simple shield shape centered at (cx, cy)."""
    r = size // 2
    # Shield: rounded top, pointed bottom
    points = [
        (cx, cy - r),           # top center
        (cx + r * 0.9, cy - r * 0.3),
        (cx + r * 0.9, cy + r * 0.5),
        (cx, cy + r),           # bottom point
        (cx - r * 0.9, cy + r * 0.5),
        (cx - r * 0.9, cy - r * 0.3),
    ]
    draw.polygon(points, fill=ACCENT, outline=ACCENT_DIM)


def generate_icon() -> Path:
    """Create aegis_icon.ico with shield logo."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    images = []

    for w, h in sizes:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        _draw_shield(draw, w // 2, h // 2, int(min(w, h) * 0.85))
        images.append(img)

    out_path = ASSETS_DIR / "aegis_icon.ico"
    images[0].save(
        out_path,
        format="ICO",
        sizes=[(img.width, img.height) for img in images],
    )
    print(f"  -> {out_path}")
    return out_path


def generate_background() -> Path:
    """Create background.png: dark tactical grid, military ops look."""
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    w, h = 1200, 800  # Base size; will scale
    img = Image.new("RGB", (w, h), BG_DARK)
    draw = ImageDraw.Draw(img)

    # Subtle grid
    step = 40
    for x in range(0, w + 1, step):
        alpha = 0.15 if x % (step * 4) == 0 else 0.06
        r = int(BG_DARK[0] + (GRID_COLOR[0] - BG_DARK[0]) * alpha)
        g = int(BG_DARK[1] + (GRID_COLOR[1] - BG_DARK[1]) * alpha)
        b = int(BG_DARK[2] + (GRID_COLOR[2] - BG_DARK[2]) * alpha)
        draw.line([(x, 0), (x, h)], fill=(r, g, b))
    for y in range(0, h + 1, step):
        alpha = 0.15 if y % (step * 4) == 0 else 0.06
        r = int(BG_DARK[0] + (GRID_COLOR[0] - BG_DARK[0]) * alpha)
        g = int(BG_DARK[1] + (GRID_COLOR[1] - BG_DARK[1]) * alpha)
        b = int(BG_DARK[2] + (GRID_COLOR[2] - BG_DARK[2]) * alpha)
        draw.line([(0, y), (w, y)], fill=(r, g, b))

    # Faint radial sweeps (radar-style) from top-left — sparse for speed
    cx, cy = 0, 0
    for angle in range(0, 360, 8):
        for radius in [250, 500, 750]:
            ex = cx + radius * math.cos(math.radians(angle))
            ey = cy + radius * math.sin(math.radians(angle))
            alpha = 0.02
            r = min(255, int(BG_DARK[0] + GRID_ACCENT[0] * alpha))
            g = min(255, int(BG_DARK[1] + GRID_ACCENT[1] * alpha))
            b = min(255, int(BG_DARK[2] + GRID_ACCENT[2] * alpha))
            draw.line([(cx, cy), (int(ex), int(ey))], fill=(r, g, b))

    out_path = ASSETS_DIR / "background.png"
    img.save(out_path)
    print(f"  -> {out_path}")
    return out_path


def main() -> None:
    print("Generating AEGIS assets...")
    generate_icon()
    generate_background()
    print("Done.")


if __name__ == "__main__":
    main()
