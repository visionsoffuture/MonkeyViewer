"""Monkey Viewer's mark: a monkey looking through a magnifying glass (design "D").

One vector drawing is the source of everything branded: the logo in the window (toolbar, welcome screen, About,
diagnostics), the loading animation, the program icon and the file-type icons (tools/make_icons.py).
Rendered with resvg; callers fall back to a plain drawing when resvg is missing.
"""

import io
import math

TILE = "#ffc94d"                       # the yellow tile behind the monkey
TILE_DARK = "#e3a51c"                  # the same yellow, deep enough for a light background

# Pupils are drawn separately so the loading animation can move them ("looking around").
_FACE = """
  <circle cx="18" cy="50" r="14" fill="#5b3a26"/><circle cx="18" cy="50" r="8" fill="#e9b07d"/>
  <circle cx="82" cy="50" r="14" fill="#5b3a26"/><circle cx="82" cy="50" r="8" fill="#e9b07d"/>
  <circle cx="50" cy="48" r="33" fill="#6b4329"/>
  <circle cx="39" cy="45" r="12.5" fill="#f0c08f"/><circle cx="61" cy="45" r="12.5" fill="#f0c08f"/>
  <ellipse cx="50" cy="62" rx="21" ry="15" fill="#f0c08f"/>
  <ellipse cx="46" cy="58" rx="1.8" ry="1.3" fill="#5b3a26"/><ellipse cx="53" cy="58" rx="1.8" ry="1.3" fill="#5b3a26"/>
  <path d="M40 65 Q48 72 56 66" fill="none" stroke="#5b3a26" stroke-width="2.8" stroke-linecap="round"/>
"""
_LENS_GLASS = '<circle cx="62" cy="44" r="12" fill="#bfe6ff" fill-opacity=".55"/>'
_LENS_RIM = ('<circle cx="62" cy="44" r="12" fill="none" stroke="#1d1a24" stroke-width="4"/>'
             '<path d="M70.5 52.5 L83 65" stroke="#1d1a24" stroke-width="7" stroke-linecap="round"/>')


def _pupils(dx=0.0):
    return (f'<g transform="translate({dx:.2f} 0)">'
            '<circle cx="39" cy="45" r="4.2" fill="#1a1620"/><circle cx="40.5" cy="43.5" r="1.3" fill="#fff"/>'
            '<circle cx="62" cy="44" r="6" fill="#1a1620"/><circle cx="64.4" cy="41.6" r="2" fill="#fff"/></g>')


def monkey_body(dx=0.0):
    """The monkey in a 100 x 100 box (SVG elements, no <svg> wrapper)."""
    return (_FACE + _LENS_GLASS
            + '<clipPath id="eyes"><circle cx="39" cy="45" r="12.5"/><circle cx="62" cy="44" r="12"/></clipPath>'
            + f'<g clip-path="url(#eyes)">{_pupils(dx)}</g>' + _LENS_RIM)


def logo_svg(plate=True, tiny=False):
    """The program icon: the monkey on the yellow rounded tile (plate=True) or on its own.
    *tiny* (icons of 24 px and less): the monkey fills more of the tile so its face still reads."""
    if not plate:
        return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">{monkey_body()}</svg>'
    fit = "translate(3 4) scale(0.94)" if tiny else "translate(12 12) scale(0.76)"
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<rect width="100" height="100" rx="{18 if tiny else 23}" fill="{TILE}"/>'
            f'<g transform="{fit}">{monkey_body()}</g></svg>')


FRAMES = 48                              # one loop of the loading animation


def _look(t):
    """Pupil offset at loop position t (0..1): glance left, hold, glance right, hold."""
    return 2.6 * max(-1.0, min(1.0, 1.7 * math.sin(2 * math.pi * t)))


def spinner_svg(frame, dark=True):
    """Frame *frame* of the loading animation: a dashed ring turns while the monkey looks around."""
    t = (frame % FRAMES) / FRAMES
    ring = TILE if dark else TILE_DARK
    return ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
            f'<g transform="rotate({t * 360:.1f} 50 50)"><circle cx="50" cy="50" r="45" fill="none" stroke="{ring}" '
            'stroke-width="4" stroke-dasharray="18 10" stroke-linecap="round"/></g>'
            f'<g transform="translate(20 20) scale(0.6)">{monkey_body(_look(t))}</g></svg>')


# ── file-type icons ──
PAGE = ('<path d="M16 4 h36 l16 16 v58 a4 4 0 0 1 -4 4 h-48 a4 4 0 0 1 -4 -4 v-70 a4 4 0 0 1 4 -4z" '
        'fill="#ffffff" stroke="#b9b2c8" stroke-width="2"/>'
        '<path d="M52 4 v12 a4 4 0 0 0 4 4 h12" fill="#ebe7f2" stroke="#b9b2c8" stroke-width="2"/>')


def file_icon_svg(color, small=False):
    """A page with a coloured label band (the type name is drawn on it afterwards) and the monkey badge.
    84 x 84 box; *small* (16-32 px icons) gives a wider band and a bigger badge so both still read."""
    if small:
        band = f'<rect x="4" y="22" width="56" height="26" rx="5" fill="{color}"/>'
        badge = (f'<rect x="34" y="44" width="46" height="38" rx="9" fill="{TILE}" stroke="#7a5a1a" stroke-width="2"/>'
                 f'<g transform="translate(39 43) scale(0.38)">{monkey_body()}</g>')
    else:
        band = f'<rect x="8" y="26" width="44" height="20" rx="4" fill="{color}"/>'
        badge = (f'<rect x="42" y="52" width="30" height="30" rx="8" fill="{TILE}" stroke="#ffffff" stroke-width="2"/>'
                 f'<g transform="translate(44.5 54.5) scale(0.25)">{monkey_body()}</g>')
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 84 84">{PAGE}{band}{badge}</svg>'


def render(svg, size):
    """PIL RGBA image of *svg* at size x size pixels."""
    import resvg_py
    from PIL import Image
    data = resvg_py.svg_to_bytes(svg_string=svg, width=int(size), height=int(size), skip_system_fonts=True)
    img = Image.open(io.BytesIO(bytes(data))).convert("RGBA")
    if img.size != (size, size):
        img = img.resize((size, size), Image.LANCZOS)
    return img


# file type -> (label colour, label): the same in Explorer / Finder (tools/make_icons.py) and inside the program
TYPES = {
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
# the program's file categories (formats.CATEGORIES) -> icon type
CATEGORY_TYPE = {"pdf": "pdf", "cad": "cad", "gis": "gis", "secure": "secure", "code": "lua", "table": "data",
                 "image": "image"}


def _fit_text(draw, text, font_for, max_w, max_h):
    fs = max(6, round(max_h * 1.3))
    f = font_for(fs)
    box = draw.textbbox((0, 0), text, font=f)
    fs = max(6, round(fs * min(max_w / max(1, box[2] - box[0]), max_h / max(1, box[3] - box[1]))))
    return font_for(fs)


def file_icon(kind, size, font_for, label=None):
    """PIL image of the file icon for *kind* (a TYPES key) with its label set on the band.
    *font_for(px)* returns a bold PIL font. Below 24 px the band carries no text (it would not read)."""
    from PIL import Image, ImageDraw
    color, default = TYPES.get(kind, TYPES["file"])
    label = label or default
    small = size <= 32
    n = max(512, size * 8)
    img = render(file_icon_svg(color, small=small), n)
    if size >= 24:
        d = ImageDraw.Draw(img)
        u = n / 84                                       # SVG units -> pixels
        bx, by, bw, bh = (4, 22, 56, 26) if small else (8, 26, 44, 20)
        f = _fit_text(d, label, font_for, bw * u * 0.84, bh * u * (0.62 if small else 0.56))
        d.text(((bx + bw / 2) * u, (by + bh / 2) * u), label, font=f, fill=(255, 255, 255, 255), anchor="mm")
    return img.resize((size, size), Image.LANCZOS)


def type_chip(label, color, width, height, font_for):
    """The small type label inside the program (tabs, file lists): the type name on a solid band in the
    category colour, followed by the yellow monkey tile - the file icon's two parts side by side."""
    from PIL import Image, ImageDraw
    ss = 4
    w, h = width * ss, height * ss
    gap = max(1, round(h * 0.12))
    img = Image.new("RGBA", (w + gap + h, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rgb = tuple(int(color[i:i + 2], 16) for i in (1, 3, 5))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=round(h * 0.28), fill=rgb + (255,))
    light = (0.299 * rgb[0] + 0.587 * rgb[1] + 0.114 * rgb[2]) > 168      # pale band: dark text
    f = _fit_text(d, label, font_for, w * 0.8, h * 0.5)
    d.text((w / 2, h / 2), label, font=f, fill=(26, 22, 32, 255) if light else (255, 255, 255, 255), anchor="mm")
    img.alpha_composite(render(logo_svg(True, tiny=True), h), (w + gap, 0))
    return img.resize(((w + gap + h) // ss, height), Image.LANCZOS)


def available():
    try:
        import resvg_py  # noqa: F401
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False
