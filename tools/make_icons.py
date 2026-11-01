"""Draw the program icon and the per-file-type icons (Explorer / Finder): Monkey Viewer's monkey with the magnifier.

    python tools/make_icons.py

Writes monkeyviewer.ico / monkeyviewer.icns (the program) and packaging/icons/<type>.ico (Windows, 16-256 px) and
packaging/icons/doc-<type>.icns (macOS): a page with the type's coloured label and the monkey badge.
<type> is the ProgID suffix (MonkeyViewer.pdf -> pdf.ico). The generated files are committed, so a build never
needs this script; run it again only after changing a design here.
"""

import os
import sys

from PIL import ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from viewer import monkey  # noqa: E402

OUT = os.path.join(ROOT, "packaging", "icons")

ICONS = monkey.TYPES
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)

FONTS = ("/usr/share/fonts/opentype/inter/Inter-Black.otf", "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def font(px):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def render(name, size):
    """One file icon at *size* px (viewer/monkey.py draws it; the label is set in this script's font)."""
    return monkey.file_icon(name, size, font)


def app_icon(size):
    return monkey.render(monkey.logo_svg(True, tiny=size <= 24), size)


def save_ico(path, draw):
    frames = {s: draw(s) for s in ICO_SIZES}
    frames[256].save(path, sizes=[(s, s) for s in ICO_SIZES],
                     append_images=[frames[s] for s in ICO_SIZES if s != 256],
                     bitmap_format="bmp")   # classic BMP entries: every Windows version / icon API reads them


def main():
    os.makedirs(OUT, exist_ok=True)
    save_ico(os.path.join(ROOT, "monkeyviewer.ico"), app_icon)
    app_icon(1024).save(os.path.join(ROOT, "monkeyviewer.icns"))
    for name in ICONS:
        save_ico(os.path.join(OUT, f"{name}.ico"), lambda s, name=name: render(name, s))
        render(name, 1024).save(os.path.join(OUT, f"doc-{name}.icns"))
    print("icons written to", OUT)


if __name__ == "__main__":
    main()
