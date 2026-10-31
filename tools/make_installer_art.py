"""Draw the installer artwork in Monkey Viewer's style (instead of WiX's red CD / a plain disk image).

    python tools/make_installer_art.py

Writes (committed, so builds never need this script):
    packaging/windows/dialog.bmp     493x312  welcome / finish page of the MSI wizard
    packaging/windows/banner.bmp     493x58   top banner of the other wizard pages
    packaging/macos/dmg-background.png (+ @2x)  disk-image window: app -> arrow -> Applications
"""

import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from viewer import monkey  # noqa: E402

DARK, DARK2 = (26, 27, 38), (36, 40, 59)
ACCENT = (122, 162, 247)
FONTS = {
    "bold": ("/usr/share/fonts/opentype/inter/Inter-Bold.otf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
             "C:/Windows/Fonts/segoeuib.ttf"),
    "regular": ("/usr/share/fonts/opentype/inter/Inter-Regular.otf",
                "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/segoeui.ttf"),
    "georgian": ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", "C:/Windows/Fonts/sylfaen.ttf"),
}


def font(kind, size):
    for path in FONTS[kind]:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def logo(size):
    """The app logo: the monkey with the magnifier on its yellow tile (viewer/monkey.py)."""
    return monkey.render(monkey.logo_svg(True, tiny=size <= 24), size)


def gradient(w, h, top, bottom):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line((0, y, w, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    return img


def windows_dialog(path):
    """WixUI dialog bitmap: the left 164 px are artwork, the wizard draws its text on the white right part."""
    img = Image.new("RGB", (493, 312), (255, 255, 255))
    img.paste(gradient(164, 312, DARK2, DARK), (0, 0))
    mark = logo(96)
    img.paste(mark, ((164 - 96) // 2, 78), mark)
    d = ImageDraw.Draw(img)
    d.text((82, 196), "Monkey Viewer", font=font("bold", 19), fill=(238, 240, 255), anchor="mm")
    d.text((82, 220), "PDF \u00b7 CAD \u00b7 GIS \u00b7 DjVu", font=font("regular", 11), fill=(154, 165, 206), anchor="mm")
    img.save(path)


def windows_banner(path):
    """WixUI banner: title text is drawn on the left, the logo sits where WiX shows its CD icon."""
    img = Image.new("RGB", (493, 58), (255, 255, 255))
    mark = logo(44)
    img.paste(mark, (493 - 44 - 8, 7), mark)
    img.save(path)


def dmg_background(path, scale=1):
    """Disk-image window 640x400: the app at (160, 190), an arrow, Applications at (480, 190)."""
    w, h = 640 * scale, 400 * scale
    img = gradient(w, h, (247, 248, 251), (233, 236, 243))
    d = ImageDraw.Draw(img)
    mark = logo(40 * scale)
    title = font("bold", 24 * scale)
    tw = d.textlength("Monkey Viewer", font=title)
    gap = 12 * scale
    x = round((w - (40 * scale + gap + tw)) / 2)
    img.paste(mark, (x, 26 * scale), mark)
    d.text((x + 40 * scale + gap, 46 * scale), "Monkey Viewer", font=title, fill=(21, 26, 48), anchor="lm")
    # arrow between the two icons
    y = 190 * scale
    x0, x1 = 250 * scale, 390 * scale
    col = (201, 137, 26)
    d.line((x0, y, x1 - 14 * scale, y), fill=col, width=6 * scale)
    d.polygon([(x1, y), (x1 - 24 * scale, y - 16 * scale), (x1 - 24 * scale, y + 16 * scale)], fill=col)
    d.text((w // 2, 300 * scale), "გადაათრიეთ Monkey Viewer საქაღალდეზე Applications",
           font=font("georgian", 14 * scale), fill=(52, 59, 88), anchor="mm")
    d.text((w // 2, 324 * scale), "Drag Monkey Viewer onto Applications to install",
           font=font("regular", 13 * scale), fill=(122, 129, 156), anchor="mm")
    img.save(path, dpi=(72 * scale, 72 * scale))


def main():
    windows_dialog(os.path.join(ROOT, "packaging", "windows", "dialog.bmp"))
    windows_banner(os.path.join(ROOT, "packaging", "windows", "banner.bmp"))
    dmg_background(os.path.join(ROOT, "packaging", "macos", "dmg-background.png"))
    dmg_background(os.path.join(ROOT, "packaging", "macos", "dmg-background@2x.png"), scale=2)
    print("installer artwork written")


if __name__ == "__main__":
    main()
