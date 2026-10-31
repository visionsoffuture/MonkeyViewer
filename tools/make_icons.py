"""Draw the program icon and the per-file-type icons (Explorer / Finder): Monkey Viewer's monkey with the magnifier.

    python tools/make_icons.py

Writes monkeyviewer.ico / monkeyviewer.icns (the program) and packaging/icons/<type>.ico (Windows, 16-256 px) and
packaging/icons/doc-<type>.icns (macOS): a page with the type's coloured label and the monkey badge.
<type> is the ProgID suffix (MonkeyViewer.pdf -> pdf.ico). The generated files are committed, so a build never
needs this script; run it again only after changing a design here.
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from viewer import monkey  # noqa: E402

OUT = os.path.join(ROOT, "packaging", "icons")

# type: (label colour, label) - the label sits on the page's coloured band
ICONS = {
    "pdf": ("#e5484d", "PDF"),
    "djvu": ("#d6406f", "DJVU"),
    "cad": ("#e0a23a", "CAD"),
    "gis": ("#46a758", "GIS"),
    "secure": ("#b8862a", "KEY"),
    "code": ("#5b6bd6", "</>"),
    "lua": ("#3e7bfa", "LUA"),
    "data": ("#12a594", "DATA"),
    "image": ("#8e4ec6", "IMG"),
    "file": ("#7d7f8c", "FILE"),
}
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 96, 128, 256)
SMALL = 32                                              # up to this size: wide band, big badge, no text below 24

FONTS = ("/usr/share/fonts/opentype/inter/Inter-Black.otf", "/usr/share/fonts/opentype/inter/Inter-Bold.otf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Supplemental/Arial Bold.ttf")


def font(px):
    for path in FONTS:
        if os.path.exists(path):
            return ImageFont.truetype(path, px)
    return ImageFont.load_default()


def render(name, size):
    """One file icon at *size* px: drawn large, the label set in the band, then scaled down."""
    color, label = ICONS[name]
    small = size <= SMALL
    n = max(512, size * 8)
    img = monkey.render(monkey.file_icon_svg(color, small=small), n)
    if size >= 24:
        d = ImageDraw.Draw(img)
        u = n / 84                                       # SVG units -> pixels
        bx, by, bw, bh = (4, 22, 56, 26) if small else (8, 26, 44, 20)
        target_w, target_h = bw * u * 0.84, bh * u * (0.62 if small else 0.56)
        fs = round(target_h * 1.3)
        f = font(fs)
        box = d.textbbox((0, 0), label, font=f)
        fs = max(8, round(fs * min(target_w / (box[2] - box[0]), target_h / (box[3] - box[1]))))
        f = font(fs)
        d.text(((bx + bw / 2) * u, (by + bh / 2) * u), label, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


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
