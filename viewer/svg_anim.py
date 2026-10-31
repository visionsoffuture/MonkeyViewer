"""SVG animation: SMIL (<animate>, <animateTransform>, <set>) and CSS (@keyframes / animation) evaluated at a
moment in time, producing a plain SVG for that frame. The renderer (resvg) draws static SVG only, so every
frame is computed here. Also applies what the renderer does not: CSS `transform` from style sheets.

Usage:
    anim = SvgAnimation(svg_text)
    anim.animated, anim.end          # has animation? end time (math.inf when it loops forever)
    svg_at_t = anim.frame(1.25)      # seconds
"""

import bisect
import math
import re
import xml.etree.ElementTree as ET  # nosec B405 - only used to serialise trees parsed by defusedxml

from defusedxml import ElementTree as SafeET

SVG_NS = "http://www.w3.org/2000/svg"
XLINK_NS = "http://www.w3.org/1999/xlink"
INF = math.inf
NUM = re.compile(r"[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")

# properties written to the inline style (they beat style-sheet rules); everything else is an attribute
CSS_PROPS = {"fill", "stroke", "opacity", "fill-opacity", "stroke-opacity", "stroke-width", "stroke-dasharray",
             "stroke-dashoffset", "stroke-linecap", "stroke-linejoin", "stroke-miterlimit", "visibility", "display",
             "stop-color", "stop-opacity", "font-size", "font-weight", "letter-spacing", "color", "flood-color",
             "flood-opacity", "mix-blend-mode", "filter"}
COLOR_PROPS = {"fill", "stroke", "stop-color", "color", "flood-color", "lighting-color"}

NAMED = {"black": (0, 0, 0), "white": (255, 255, 255), "red": (255, 0, 0), "green": (0, 128, 0),
         "blue": (0, 0, 255), "yellow": (255, 255, 0), "cyan": (0, 255, 255), "aqua": (0, 255, 255),
         "magenta": (255, 0, 255), "fuchsia": (255, 0, 255), "gray": (128, 128, 128), "grey": (128, 128, 128),
         "silver": (192, 192, 192), "maroon": (128, 0, 0), "olive": (128, 128, 0), "lime": (0, 255, 0),
         "teal": (0, 128, 128), "navy": (0, 0, 128), "purple": (128, 0, 128), "orange": (255, 165, 0),
         "pink": (255, 192, 203), "gold": (255, 215, 0), "brown": (165, 42, 42), "transparent": (0, 0, 0)}


def local(tag):
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


# ─────────────────────────────── values ───────────────────────────────
def clock(text):
    """'1.8s', '200ms', '2', '1min', '0:02.5' -> seconds; None when it is not a plain time."""
    text = (text or "").strip()
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+))\s*(ms|s|min|h)?", text)
    if m:
        return float(m.group(1)) * {"ms": 0.001, "s": 1, "min": 60, "h": 3600, None: 1}[m.group(2)]
    m = re.fullmatch(r"(?:(\d+):)?(\d+):(\d+(?:\.\d+)?)", text)
    if m:
        return int(m.group(1) or 0) * 3600 + int(m.group(2)) * 60 + float(m.group(3))
    return None


def parse_color(text):
    """(r, g, b, a) with 0-255 channels and alpha 0-1, or None."""
    t = (text or "").strip().lower()
    if t in NAMED:
        return NAMED[t] + ((0.0,) if t == "transparent" else (1.0,))
    m = re.fullmatch(r"#([0-9a-f]{3,8})", t)
    if m:
        h = m.group(1)
        if len(h) in (3, 4):
            h = "".join(c * 2 for c in h)
        if len(h) in (6, 8):
            a = int(h[6:8], 16) / 255 if len(h) == 8 else 1.0
            return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16), a
        return None
    m = re.fullmatch(r"(rgba?|hsla?)\((.*)\)", t)
    if not m:
        return None
    parts = [p for p in re.split(r"[\s,/]+", m.group(2).strip()) if p]
    if len(parts) < 3:
        return None

    def num(p, scale):
        return float(p[:-1]) / 100 * scale if p.endswith("%") else float(p)
    try:
        a = num(parts[3], 1) if len(parts) > 3 else 1.0
        if m.group(1).startswith("rgb"):
            r, g, b = (max(0, min(255, round(num(p, 255)))) for p in parts[:3])
            return r, g, b, max(0.0, min(1.0, a))
        h = float(re.sub(r"deg$", "", parts[0])) % 360 / 360
        s, li = num(parts[1], 1), num(parts[2], 1)
        import colorsys
        r, g, b = colorsys.hls_to_rgb(h, li, s)
        return round(r * 255), round(g * 255), round(b * 255), max(0.0, min(1.0, a))
    except ValueError:
        return None


def color_text(c):
    r, g, b, a = c
    if a >= 0.999:
        return "#%02x%02x%02x" % (round(r), round(g), round(b))
    return "rgba(%d,%d,%d,%.3f)" % (round(r), round(g), round(b), a)


def _fmt(x):
    return ("%.4f" % x).rstrip("0").rstrip(".") if abs(x - round(x)) > 1e-9 else str(int(round(x)))


def interpolate(a, b, p, prop=None):
    """Value between the strings a and b at progress p (0..1): numbers, number lists, colours; else discrete."""
    if a == b or p <= 0:
        return a if p < 1 else b
    if p >= 1:
        return b
    if prop in COLOR_PROPS or (prop is None and parse_color(a) and parse_color(b)):
        ca, cb = parse_color(a), parse_color(b)
        if ca and cb:
            return color_text(tuple(x + (y - x) * p for x, y in zip(ca, cb)))
    na, nb = NUM.findall(a), NUM.findall(b)
    if na and len(na) == len(nb) and NUM.sub("#", a) == NUM.sub("#", b):
        vals = iter(_fmt(float(x) + (float(y) - float(x)) * p) for x, y in zip(na, nb))
        return NUM.sub(lambda _m: next(vals), a)
    return a if p < 0.5 else b


def add_values(a, b):
    """SMIL additive / 'by' animation for numbers and number lists."""
    na, nb = NUM.findall(a or ""), NUM.findall(b or "")
    if na and len(na) == len(nb):
        vals = iter(_fmt(float(x) + float(y)) for x, y in zip(na, nb))
        return NUM.sub(lambda _m: next(vals), a)
    return b


def bezier(x1, y1, x2, y2):
    """CSS / SMIL cubic-bezier easing function."""
    def sample(t, p1, p2):
        return ((1 - 3 * p2 + 3 * p1) * t + (3 * p2 - 6 * p1)) * t * t + 3 * p1 * t

    def ease(x):
        if x <= 0 or x >= 1:
            return max(0.0, min(1.0, x))
        lo, hi, t = 0.0, 1.0, x
        for _ in range(30):
            v = sample(t, x1, x2)
            if abs(v - x) < 1e-5:
                break
            if v < x:
                lo = t
            else:
                hi = t
            t = (lo + hi) / 2
        return sample(t, y1, y2)
    return ease


EASINGS = {"linear": lambda x: x, "ease": bezier(.25, .1, .25, 1), "ease-in": bezier(.42, 0, 1, 1),
           "ease-out": bezier(0, 0, .58, 1), "ease-in-out": bezier(.42, 0, .58, 1),
           "step-start": lambda x: 1.0 if x > 0 else 0.0, "step-end": lambda x: 1.0 if x >= 1 else 0.0}


def easing(text):
    t = (text or "ease").strip().lower()
    if t in EASINGS:
        return EASINGS[t]
    m = re.fullmatch(r"cubic-bezier\(([^)]*)\)", t)
    if m:
        try:
            x1, y1, x2, y2 = (float(v) for v in m.group(1).split(","))
            return bezier(x1, y1, x2, y2)
        except ValueError:
            return EASINGS["ease"]
    m = re.fullmatch(r"steps\(\s*(\d+)\s*(?:,\s*([\w-]+))?\s*\)", t)
    if m:
        n = max(1, int(m.group(1)))
        start = (m.group(2) or "end") in ("start", "jump-start")
        return lambda x: min(1.0, (math.floor(x * n) + (1 if start else 0)) / n)
    return EASINGS["ease"]


# ─────────────────────────────── CSS transforms ───────────────────────────────
def _angle(v):
    v = v.strip().lower()
    for unit, k in (("deg", 1), ("grad", 0.9), ("rad", 180 / math.pi), ("turn", 360)):
        if v.endswith(unit):
            return float(v[:-len(unit)]) * k
    return float(v or 0)


def _length(v, ref=0.0):
    v = v.strip().lower()
    if v.endswith("%"):
        return float(v[:-1]) / 100 * ref
    m = re.fullmatch(r"([-+]?(?:\d+\.?\d*|\.\d+)(?:e[-+]?\d+)?)(px|pt|em|rem)?", v)
    if not m:
        return 0.0
    return float(m.group(1)) * {"px": 1, "pt": 4 / 3, "em": 16, "rem": 16, None: 1}[m.group(2)]


def parse_css_transform(text, box=(0, 0, 0, 0)):
    """CSS transform -> [(name, [numbers])] in SVG units (degrees, user units)."""
    out = []
    bw, bh = box[2], box[3]
    for name, args in re.findall(r"([a-zA-Z0-9]+)\(([^)]*)\)", text or ""):
        a = [x for x in re.split(r"[\s,]+", args.strip()) if x]
        n = name.lower()
        try:
            if n in ("rotate", "rotatez"):
                out.append(("rotate", [_angle(a[0])]))
            elif n in ("translate", "translate3d"):
                out.append(("translate", [_length(a[0], bw), _length(a[1], bh) if len(a) > 1 else 0.0]))
            elif n == "translatex":
                out.append(("translate", [_length(a[0], bw), 0.0]))
            elif n == "translatey":
                out.append(("translate", [0.0, _length(a[0], bh)]))
            elif n in ("scale", "scale3d"):
                sx = float(a[0][:-1]) / 100 if a[0].endswith("%") else float(a[0])
                sy = (float(a[1][:-1]) / 100 if a[1].endswith("%") else float(a[1])) if len(a) > 1 else sx
                out.append(("scale", [sx, sy]))
            elif n == "scalex":
                out.append(("scale", [float(a[0]), 1.0]))
            elif n == "scaley":
                out.append(("scale", [1.0, float(a[0])]))
            elif n == "skew":
                out.append(("skewX", [_angle(a[0])]))
                if len(a) > 1:
                    out.append(("skewY", [_angle(a[1])]))
            elif n == "skewx":
                out.append(("skewX", [_angle(a[0])]))
            elif n == "skewy":
                out.append(("skewY", [_angle(a[0])]))
            elif n == "matrix" and len(a) == 6:
                out.append(("matrix", [float(x) for x in a]))
        except (ValueError, IndexError):
            continue
    return out


def _identity_like(funcs):
    ident = {"rotate": [0.0], "translate": [0.0, 0.0], "scale": [1.0, 1.0], "skewX": [0.0], "skewY": [0.0],
             "matrix": [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]}
    return [(n, list(ident[n])) for n, _a in funcs]


def _matrix(funcs):
    a, b, c, d, e, f = 1.0, 0.0, 0.0, 1.0, 0.0, 0.0

    def mul(m2):
        nonlocal a, b, c, d, e, f
        a2, b2, c2, d2, e2, f2 = m2
        a, b, c, d, e, f = (a * a2 + c * b2, b * a2 + d * b2, a * c2 + c * d2, b * c2 + d * d2,
                            a * e2 + c * f2 + e, b * e2 + d * f2 + f)
    for n, v in funcs:
        if n == "rotate":
            r = math.radians(v[0])
            mul((math.cos(r), math.sin(r), -math.sin(r), math.cos(r), 0, 0))
        elif n == "translate":
            mul((1, 0, 0, 1, v[0], v[1]))
        elif n == "scale":
            mul((v[0], 0, 0, v[1], 0, 0))
        elif n == "skewX":
            mul((1, 0, math.tan(math.radians(v[0])), 1, 0, 0))
        elif n == "skewY":
            mul((1, math.tan(math.radians(v[0])), 0, 1, 0, 0))
        elif n == "matrix":
            mul(tuple(v))
    return [a, b, c, d, e, f]


def interpolate_transform(fa, fb, p):
    if not fa:
        fa = _identity_like(fb)
    if not fb:
        fb = _identity_like(fa)
    if [n for n, _ in fa] == [n for n, _ in fb]:
        return [(n, [x + (y - x) * p for x, y in zip(va, vb)]) for (n, va), (_n, vb) in zip(fa, fb)]
    ma, mb = _matrix(fa), _matrix(fb)
    return [("matrix", [x + (y - x) * p for x, y in zip(ma, mb)])]


def svg_transform(funcs):
    parts = []
    for n, v in funcs:
        if n == "translate":
            parts.append(f"translate({_fmt(v[0])} {_fmt(v[1])})")
        elif n == "scale":
            parts.append(f"scale({_fmt(v[0])} {_fmt(v[1])})")
        else:
            parts.append(f"{n}({' '.join(_fmt(x) for x in v)})")
    return " ".join(parts)


# ─────────────────────────────── geometry (transform-box: fill-box, % origins) ───────────────────────────────
def _f(el, name, default=0.0):
    try:
        return float(NUM.match((el.get(name) or "").strip()).group(0))
    except (AttributeError, ValueError):
        return default


def _path_box(d):
    """Bounding box of path data from its end and control points (good enough for transform origins)."""
    xs, ys = [], []
    x = y = sx = sy = 0.0
    tokens = re.findall(r"[MmLlHhVvCcSsQqTtAaZz]|" + NUM.pattern, d or "")
    i, cmd = 0, None
    counts = {"m": 2, "l": 2, "h": 1, "v": 1, "c": 6, "s": 4, "q": 4, "t": 2, "a": 7, "z": 0}
    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd in "Zz":
                x, y = sx, sy
                continue
        if cmd is None:
            break
        n = counts[cmd.lower()]
        try:
            v = [float(t) for t in tokens[i:i + n]]
        except ValueError:
            break
        if len(v) < n:
            break
        i += n
        rel = cmd.islower()
        c = cmd.lower()
        if c == "h":
            x = x + v[0] if rel else v[0]
        elif c == "v":
            y = y + v[0] if rel else v[0]
        elif c == "a":
            x, y = (x + v[5], y + v[6]) if rel else (v[5], v[6])
        else:
            for k in range(0, n, 2):
                px_, py_ = (x + v[k], y + v[k + 1]) if rel else (v[k], v[k + 1])
                xs.append(px_)
                ys.append(py_)
            x, y = xs[-1], ys[-1]
        if c == "m":
            sx, sy = x, y
            cmd = "l" if rel else "L"
        xs.append(x)
        ys.append(y)
    if not xs:
        return None
    return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)


def bbox(el):
    tag = local(el.tag)
    if tag == "circle":
        r = _f(el, "r")
        return _f(el, "cx") - r, _f(el, "cy") - r, 2 * r, 2 * r
    if tag == "ellipse":
        rx, ry = _f(el, "rx"), _f(el, "ry")
        return _f(el, "cx") - rx, _f(el, "cy") - ry, 2 * rx, 2 * ry
    if tag in ("rect", "image", "use", "foreignObject", "svg"):
        return _f(el, "x"), _f(el, "y"), _f(el, "width"), _f(el, "height")
    if tag == "line":
        x1, y1, x2, y2 = _f(el, "x1"), _f(el, "y1"), _f(el, "x2"), _f(el, "y2")
        return min(x1, x2), min(y1, y2), abs(x2 - x1), abs(y2 - y1)
    if tag in ("polyline", "polygon"):
        n = [float(v) for v in NUM.findall(el.get("points") or "")]
        if len(n) >= 2:
            xs, ys = n[0::2], n[1::2]
            return min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)
    if tag == "path":
        return _path_box(el.get("d"))
    if tag == "text":
        size = _f(el, "font-size", 16.0)
        text = "".join(el.itertext())
        return _f(el, "x"), _f(el, "y") - size, len(text) * size * 0.55, size
    boxes = [b for b in (bbox(c) for c in el) if b]
    if boxes:
        x0, y0 = min(b[0] for b in boxes), min(b[1] for b in boxes)
        x1, y1 = max(b[0] + b[2] for b in boxes), max(b[1] + b[3] for b in boxes)
        return x0, y0, x1 - x0, y1 - y0
    return None


# ─────────────────────────────── CSS style sheets ───────────────────────────────
def parse_decls(text):
    out = []
    depth, cur = 0, ""
    for ch in (text or "") + ";":
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == ";" and depth <= 0:
            if ":" in cur:
                k, v = cur.split(":", 1)
                out.append((k.strip().lower(), re.sub(r"\s*!important\s*$", "", v.strip())))
            cur = ""
        else:
            cur += ch
    return out


def _blocks(text):
    """Top-level 'prelude { body }' pairs of a style sheet."""
    out, i, n = [], 0, len(text)
    while i < n:
        j = text.find("{", i)
        if j < 0:
            break
        depth, k = 1, j + 1
        while k < n and depth:
            if text[k] == "{":
                depth += 1
            elif text[k] == "}":
                depth -= 1
            k += 1
        out.append((text[i:j].strip(), text[j + 1:k - 1]))
        i = k
    return out


def parse_stylesheet(text):
    """(rules [(selector, specificity, order, decls)], keyframes {name: [(offset, decls)]})"""
    text = re.sub(r"/\*.*?\*/", "", text or "", flags=re.S)
    rules, frames, order = [], {}, 0
    for prelude, body in _blocks(text):
        low = prelude.lower()
        if low.startswith(("@keyframes", "@-webkit-keyframes", "@-moz-keyframes")):
            name = prelude.split(None, 1)[1].strip().strip("'\"") if " " in prelude else ""
            steps = []
            for sel, decls in _blocks(body):
                d = parse_decls(decls)
                for part in sel.split(","):
                    part = part.strip().lower()
                    off = 0.0 if part == "from" else 1.0 if part == "to" else (
                        float(part[:-1]) / 100 if part.endswith("%") and NUM.fullmatch(part[:-1]) else None)
                    if off is not None:
                        steps.append((off, dict(d)))
            steps.sort(key=lambda s: s[0])
            frames[name] = steps
        elif low.startswith(("@media", "@supports")):
            sub_rules, sub_frames = parse_stylesheet(body)
            for sel, spec, _o, decls in sub_rules:
                rules.append((sel, spec, order, decls))
                order += 1
            frames.update(sub_frames)
        elif not low.startswith("@"):
            decls = parse_decls(body)
            for sel in prelude.split(","):
                sel = sel.strip()
                if sel and ":" not in sel.replace(":root", ""):
                    rules.append((sel, _specificity(sel), order, decls))
                    order += 1
    return rules, frames


def _specificity(sel):
    ids = len(re.findall(r"#[\w-]+", sel))
    classes = len(re.findall(r"\.[\w-]+|\[[^\]]*\]", sel))
    tags = len(re.findall(r"(?:^|[\s>+~])([a-zA-Z][\w-]*)", sel))
    return ids, classes, tags


def _compound_matches(el, comp):
    if comp in ("*", ""):
        return True
    if comp == ":root":
        return local(el.tag) == "svg"
    m = re.match(r"([a-zA-Z][\w-]*|\*)?", comp)
    tag = m.group(1) if m else None
    if tag and tag != "*" and local(el.tag) != tag:
        return False
    classes = (el.get("class") or "").split()
    for kind, val in re.findall(r"([.#])([\w-]+)", comp):
        if kind == "." and val not in classes:
            return False
        if kind == "#" and el.get("id") != val:
            return False
    for attr, op, val in re.findall(r"\[\s*([\w:-]+)\s*(?:([~|^$*]?=)\s*[\"']?([^\"'\]]*)[\"']?)?\s*\]", comp):
        have = el.get(attr)
        if have is None or (op == "=" and have != val) or (op == "~=" and val not in have.split()):
            return False
    return True


def selector_matches(el, sel, parents):
    parts = re.findall(r"[^\s>]+|>", sel.strip())
    if not parts:
        return False

    def match_from(node, idx):
        if not _compound_matches(node, parts[idx]):
            return False
        if idx == 0:
            return True
        if parts[idx - 1] == ">":
            parent = parents.get(node)
            return parent is not None and idx >= 2 and match_from(parent, idx - 2)
        anc = parents.get(node)
        while anc is not None:
            if match_from(anc, idx - 1):
                return True
            anc = parents.get(anc)
        return False
    return match_from(el, len(parts) - 1)


# ─────────────────────────────── animations ───────────────────────────────
class Smil:
    def __init__(self, el, target, doc_order):
        self.el, self.target, self.order = el, target, doc_order
        self.tag = local(el.tag)
        self.attr = el.get("attributeName") or ("transform" if self.tag == "animateTransform" else "")
        self.type = el.get("type", "translate")
        self.dur = clock(el.get("dur"))
        if self.dur is not None and self.dur <= 0:
            self.dur = None
        rc = (el.get("repeatCount") or "").strip()
        self.repeat = INF if rc == "indefinite" else (float(rc) if NUM.fullmatch(rc or "x") else None)
        rd = el.get("repeatDur")
        self.repeat_dur = INF if rd == "indefinite" else clock(rd)
        self.freeze = el.get("fill") == "freeze"
        self.additive = el.get("additive") == "sum"
        self.accumulate = el.get("accumulate") == "sum"
        self.calc = el.get("calcMode", "paced" if self.tag == "animateMotion" else "linear")
        if self.tag == "set":
            self.calc = "discrete"
        self.values = [v.strip() for v in (el.get("values") or "").split(";") if v.strip()]
        self.frm, self.to, self.by = el.get("from"), el.get("to"), el.get("by")
        kt = [float(v) for v in NUM.findall(el.get("keyTimes") or "")]
        self.key_times = kt if self.values and len(kt) == len(self.values) else None
        ks = [float(v) for v in NUM.findall(el.get("keySplines") or "")]
        self.splines = [bezier(*ks[i:i + 4]) for i in range(0, len(ks) - 3, 4)] if self.calc == "spline" else None
        self.begin_spec = (el.get("begin") or "0s").split(";")[0].strip()
        self.begin = None

    def active_dur(self):
        if self.dur is None:
            return INF if self.tag == "set" or self.repeat_dur == INF else None
        ad = self.dur * (self.repeat if self.repeat is not None else 1)
        if self.repeat is None and self.repeat_dur is not None:
            ad = self.repeat_dur
        elif self.repeat_dur is not None:
            ad = min(ad, self.repeat_dur)
        return ad

    def end(self):
        if self.begin is None:
            return None
        ad = self.active_dur()
        return None if ad is None else self.begin + ad

    def _keyvalues(self, base):
        if self.values:
            return list(self.values)
        if self.tag == "set":
            return [self.to or base]
        if self.frm is not None and self.to is not None:
            return [self.frm, self.to]
        if self.frm is not None and self.by is not None:
            return [self.frm, add_values(self.frm, self.by)]
        if self.to is not None:
            return [base, self.to]
        if self.by is not None:
            return [base, add_values(base, self.by)]
        return [base]

    def _at(self, p, base, prop):
        vals = self._keyvalues(base)
        if len(vals) == 1:
            return vals[0]
        n = len(vals)
        if self.calc == "discrete":
            kt = self.key_times or [i / n for i in range(n)]
            i = max(0, bisect.bisect_right(kt, p) - 1)
            return vals[min(i, n - 1)]
        kt = self.key_times or [i / (n - 1) for i in range(n)]
        if p >= kt[-1]:
            return vals[-1]
        i = max(0, min(n - 2, bisect.bisect_right(kt, p) - 1))
        span = kt[i + 1] - kt[i]
        local_p = 0.0 if span <= 0 else (p - kt[i]) / span
        if self.splines and i < len(self.splines):
            local_p = self.splines[i](local_p)
        return interpolate(vals[i], vals[i + 1], local_p, prop)

    def value(self, t, base):
        """(value, contributes) at time t; base is the value below this animation in the sandwich."""
        if self.begin is None or t < self.begin:
            return None
        ad = self.active_dur()
        if ad is None:
            return None
        if self.dur is None:                      # <set> without dur: holds its value
            return self._keyvalues(base)[-1] if t - self.begin < ad or self.freeze else None
        el = t - self.begin
        if el >= ad:
            if not self.freeze:
                return None
            el = ad
            iteration = math.ceil(ad / self.dur) - 1 if ad > 0 else 0
            p = (ad - iteration * self.dur) / self.dur
        else:
            iteration = int(el // self.dur)
            p = (el - iteration * self.dur) / self.dur
        v = self._at(p, base, self.attr)
        if self.accumulate and iteration > 0:
            last = self._at(1.0, base, self.attr)
            for _ in range(min(iteration, 1000)):
                v = add_values(v, last)
        return v


class CssAnimation:
    def __init__(self, el, name, frames, dur, delay, ease, count, direction, fill):
        self.el, self.name, self.frames = el, name, frames
        self.dur, self.delay, self.ease = dur, delay, ease
        self.count, self.direction, self.fill = count, direction, fill

    def end(self):
        return INF if self.count == INF else self.delay + self.dur * self.count

    def progress(self, t):
        """(progress 0..1 within the iteration, before easing) or None when not applied at t."""
        if self.dur <= 0:
            return None
        active = t - self.delay
        if active < 0:
            if self.fill not in ("backwards", "both"):
                return None
            it, p = 0, 0.0
        else:
            total = self.dur * self.count
            if active >= total:
                if self.fill not in ("forwards", "both"):
                    return None
                it = math.ceil(self.count) - 1 if self.count > 0 else 0
                p = self.count - it if self.count != it else 1.0
                p = 1.0 if p == 0 else p
            else:
                it = int(active // self.dur)
                p = (active - it * self.dur) / self.dur
        reverse = self.direction == "reverse" or (self.direction == "alternate" and it % 2 == 1) or (
            self.direction == "alternate-reverse" and it % 2 == 0)
        return 1.0 - p if reverse else p


def _parse_animation_shorthand(value):
    """'breathe 1.6s ease-in-out infinite' (may be a comma list) -> [dict]"""
    out = []
    for part in re.split(r",(?![^(]*\))", value):
        tokens = re.findall(r"[\w.-]+\([^)]*\)|[^\s]+", part.strip())
        a = {}
        times = []
        for tok in tokens:
            low = tok.lower()
            if clock(low) is not None and re.search(r"[\d.]+m?s$", low):
                times.append(clock(low))
            elif low in EASINGS or low.startswith(("cubic-bezier(", "steps(")):
                a["timing"] = low
            elif low == "infinite" or NUM.fullmatch(low):
                a["count"] = INF if low == "infinite" else float(low)
            elif low in ("normal", "reverse", "alternate", "alternate-reverse"):
                a["direction"] = low
            elif low in ("none", "forwards", "backwards", "both"):
                a["fill"] = low
            elif low in ("running", "paused"):
                a["state"] = low
            else:
                a["name"] = tok.strip("'\"")
        if times:
            a["duration"] = times[0]
        if len(times) > 1:
            a["delay"] = times[1]
        out.append(a)
    return out


class SvgAnimation:
    def __init__(self, svg_text):
        self.text = svg_text
        self.root = SafeET.fromstring(svg_text.encode("utf-8") if isinstance(svg_text, str) else svg_text)
        for prefix, uri in re.findall(r"xmlns:([\w-]+)\s*=\s*[\"']([^\"']+)[\"']", svg_text[:20000]):
            if prefix not in ("xml",):
                try:
                    ET.register_namespace(prefix, uri)
                except ValueError:
                    pass
        ET.register_namespace("", SVG_NS)
        ET.register_namespace("xlink", XLINK_NS)
        self.parents = {c: p for p in self.root.iter() for c in p}
        self.ids = {el.get("id"): el for el in self.root.iter() if el.get("id")}
        self.originals = {}                       # (element, attribute) -> original value or None
        self._cascade = {}
        self.smil, self.css = [], []
        sheet = "\n".join("".join(el.itertext()) for el in self.root.iter() if local(el.tag) == "style")
        self.rules, self.keyframes = parse_stylesheet(sheet)
        self._collect_smil()
        self._collect_css()
        self.animated = bool(self.smil or self.css)
        ends = [a.end() for a in self.smil] + [a.end() for a in self.css]
        ends = [e for e in ends if e is not None]
        self.end = max(ends) if ends else 0.0
        self._static_css_transforms()

    # ── collection ──
    def _collect_smil(self):
        anims = []
        for n, el in enumerate(self.root.iter()):
            tag = local(el.tag)
            if tag not in ("animate", "animateTransform", "set", "animateColor"):
                continue
            href = el.get("href") or el.get(f"{{{XLINK_NS}}}href")
            target = self.ids.get(href[1:]) if href and href.startswith("#") else self.parents.get(el)
            if target is None:
                continue
            a = Smil(el, target, n)
            if a.attr:
                anims.append(a)
        by_id = {a.el.get("id"): a for a in anims if a.el.get("id")}
        for _ in range(4):                        # resolve 'x.begin+1s' / 'x.end' chains
            for a in anims:
                if a.begin is not None:
                    continue
                spec = a.begin_spec
                t = clock(spec)
                if t is not None:
                    a.begin = t
                    continue
                m = re.fullmatch(r"([\w-]+)\.(begin|end)\s*(?:([-+])\s*(.+))?", spec)
                if m and m.group(1) in by_id:
                    ref = by_id[m.group(1)]
                    base = ref.begin if m.group(2) == "begin" else ref.end()
                    if base is not None:
                        off = clock(m.group(4)) or 0.0 if m.group(4) else 0.0
                        a.begin = base + (-off if m.group(3) == "-" else off)
                elif not m and spec != "indefinite":
                    a.begin = 0.0                 # click, accessKey...: shown as if it had started
        for a in anims:                           # unresolvable references: start with the document
            if a.begin is None and a.begin_spec != "indefinite":
                a.begin = 0.0
        self.smil = [a for a in anims if a.begin is not None]

    def cascade(self, el):
        """Declarations for el from the style sheet (by specificity, then order) and its style attribute -
        of the original document (cached before anything is changed)."""
        cached = self._cascade.get(el)
        if cached is not None:
            return cached
        matched = [(spec, order, decls) for sel, spec, order, decls in self.rules
                   if selector_matches(el, sel, self.parents)]
        matched.sort(key=lambda m: (m[0], m[1]))
        out = []
        for _spec, _order, decls in matched:
            out.extend(decls)
        out.extend(parse_decls(el.get("style")))
        self._cascade[el] = out
        return out

    def _collect_css(self):
        if not self.keyframes:
            return
        for el in self.root.iter():
            decls = self.cascade(el)
            if not any(k.startswith("animation") for k, _v in decls):
                continue
            items = [{}]
            for k, v in decls:
                if k == "animation":
                    items = _parse_animation_shorthand(v)
                elif k.startswith("animation-"):
                    vals = [x.strip() for x in re.split(r",(?![^(]*\))", v)]
                    while len(items) < len(vals):
                        items.append(dict(items[-1]))
                    key = k[len("animation-"):]
                    for i, x in enumerate(vals):
                        low = x.lower()
                        if key == "name":
                            items[i]["name"] = x.strip("'\"")
                        elif key == "duration":
                            items[i]["duration"] = clock(low) or 0.0
                        elif key == "delay":
                            items[i]["delay"] = clock(low) or 0.0
                        elif key == "timing-function":
                            items[i]["timing"] = low
                        elif key == "iteration-count":
                            items[i]["count"] = INF if low == "infinite" else float(low) if NUM.fullmatch(low) else 1
                        elif key == "direction":
                            items[i]["direction"] = low
                        elif key == "fill-mode":
                            items[i]["fill"] = low
                        elif key == "play-state":
                            items[i]["state"] = low
            for a in items:
                frames = self.keyframes.get(a.get("name") or "")
                if not frames or not a.get("duration"):
                    continue
                self.css.append(CssAnimation(el, a["name"], frames, a["duration"], a.get("delay", 0.0),
                                             a.get("timing", "ease"), a.get("count", 1.0),
                                             a.get("direction", "normal"), a.get("fill", "none")))

    # ── helpers ──
    def _origin(self, el, decls):
        origin = "0 0"
        box_mode = "view-box"
        for k, v in decls:
            if k == "transform-origin":
                origin = v
            elif k == "transform-box":
                box_mode = v.strip()
        if el.get("transform-origin") and not any(k == "transform-origin" for k, _v in decls):
            origin = el.get("transform-origin")
        if box_mode in ("fill-box", "stroke-box", "content-box", "border-box"):
            box = bbox(el) or (0, 0, 0, 0)
        else:
            vb = [float(v) for v in NUM.findall(self.root.get("viewBox") or "")]
            box = (vb[0], vb[1], vb[2], vb[3]) if len(vb) == 4 else (
                0, 0, _f(self.root, "width", 300), _f(self.root, "height", 150))
        words = origin.replace(",", " ").split() or ["0", "0"]
        kw = {"left": "0%", "center": "50%", "right": "100%", "top": "0%", "bottom": "100%"}
        if len(words) == 1:
            words = [words[0], "center"]
        if words[0] in ("top", "bottom") or words[1] in ("left", "right"):
            words = [words[1], words[0]]
        # offsets from the reference box's corner (view box, or the element's own box for fill-box)
        ox = box[0] + _length(kw.get(words[0], words[0]), box[2])
        oy = box[1] + _length(kw.get(words[1], words[1]), box[3])
        return ox, oy, box

    def _set(self, el, attr, value):
        key = (el, attr)
        if key not in self.originals:
            self.originals[key] = el.get(attr)
        if value is None:
            el.attrib.pop(attr, None)
        else:
            el.set(attr, value)

    def _set_style(self, el, props):
        decls = dict(parse_decls(el.get("style")))
        decls.update(props)
        self._set(el, "style", "; ".join(f"{k}: {v}" for k, v in decls.items()))

    def _put(self, el, prop, value):
        """Write one animated value: CSS properties go to the inline style, the rest to attributes."""
        if prop in CSS_PROPS:
            self._pending_style.setdefault(el, {})[prop] = value
            if prop in el.attrib or (el, prop) in self.originals:
                self._set(el, prop, value)
        else:
            self._set(el, prop, value)

    def _base(self, el, prop):
        """Value under the animations: original attribute / inline style / style sheet / default."""
        if (el, prop) in self.originals:
            v = self.originals[(el, prop)]
            if v is not None:
                return v
        for k, v in reversed(self.cascade(el)):
            if k == prop:
                return v
        v = el.get(prop)
        if v is not None:
            return v
        return {"opacity": "1", "fill-opacity": "1", "stroke-opacity": "1", "stroke-dashoffset": "0",
                "transform": ""}.get(prop, "0")

    def _static_css_transforms(self):
        """resvg ignores the CSS `transform` property: turn it into the transform attribute once."""
        self._static = {}
        for el in self.root.iter():
            decls = self.cascade(el) if self.rules or el.get("style") else []
            css_t = [v for k, v in decls if k == "transform"]
            if not css_t or css_t[-1].strip() == "none":
                continue
            ox, oy, box = self._origin(el, decls)
            funcs = parse_css_transform(css_t[-1], box)
            value = f"translate({_fmt(ox)} {_fmt(oy)}) {svg_transform(funcs)} translate({_fmt(-ox)} {_fmt(-oy)})"
            el.set("transform", value)
            self._neutral_origin(el)
            self._static[el] = value

    def _neutral_origin(self, el):
        """The origin is baked into the transform: stop the renderer from applying transform-origin again."""
        decls = dict(parse_decls(el.get("style")))
        decls["transform-origin"] = "0px 0px"
        el.set("style", "; ".join(f"{k}: {v}" for k, v in decls.items()))
        el.attrib.pop("transform-origin", None)

    # ── frames ──
    def frame(self, t):
        """The SVG document (text) at time t seconds."""
        for (el, attr), value in self.originals.items():   # back to the original document
            if value is None:
                el.attrib.pop(attr, None)
            else:
                el.set(attr, value)
        self._pending_style = {}
        # SMIL: per element and attribute, the animation sandwich in begin / document order
        groups = {}
        for a in self.smil:
            groups.setdefault((a.target, a.attr), []).append(a)
        for (el, attr), anims in groups.items():
            anims.sort(key=lambda a: (a.begin, a.order))
            base = self._base(el, attr) if attr != "transform" else (self._static.get(el) or el.get("transform")
                                                                      or "")
            value, touched = base, False
            for a in anims:
                if a.tag == "animateTransform":
                    v = a.value(t, "")
                    if v is None:
                        continue
                    this = f"{a.type}({v})"
                    value = f"{value} {this}".strip() if a.additive else this
                    touched = True
                else:
                    v = a.value(t, value)
                    if v is None:
                        continue
                    value = add_values(value, v) if a.additive else v
                    touched = True
            if touched:
                self._put(el, attr, value)
        # CSS animations, in style-sheet order (later ones win for the same property)
        for a in self.css:
            p = a.progress(t)
            if p is None:
                continue
            props = set()
            for _off, decls in a.frames:
                props.update(k for k in decls if k not in ("animation-timing-function",))
            decls_el = self.cascade(a.el)
            for prop in props:
                steps = [(off, d[prop], d.get("animation-timing-function")) for off, d in a.frames if prop in d]
                base = self._base(a.el, prop) if prop != "transform" else next(
                    (v for k, v in reversed(decls_el) if k == "transform"), "none")
                if not steps or steps[0][0] > 0:
                    steps.insert(0, (0.0, base, None))
                if steps[-1][0] < 1:
                    steps.append((1.0, base, None))
                i = max(0, min(len(steps) - 2, bisect.bisect_right([s[0] for s in steps], p) - 1))
                (o0, v0, e0), (o1, v1) = steps[i], steps[i + 1][:2]
                lp = 0.0 if o1 <= o0 else max(0.0, min(1.0, (p - o0) / (o1 - o0)))
                lp = easing(e0 or a.ease)(lp)
                if prop == "transform":
                    ox, oy, box = self._origin(a.el, decls_el)
                    funcs = interpolate_transform(parse_css_transform(v0, box), parse_css_transform(v1, box), lp)
                    self._set(a.el, "transform", f"translate({_fmt(ox)} {_fmt(oy)}) {svg_transform(funcs)} "
                                                 f"translate({_fmt(-ox)} {_fmt(-oy)})")
                    self._pending_style.setdefault(a.el, {})["transform-origin"] = "0px 0px"
                    if a.el.get("transform-origin") is not None:
                        self._set(a.el, "transform-origin", None)
                else:
                    self._put(a.el, prop, interpolate(v0, v1, lp, prop))
        for el, props in self._pending_style.items():
            self._set_style(el, props)
        return ET.tostring(self.root, encoding="unicode")


def has_animation(svg_text):
    low = svg_text.lower()
    return "<animate" in low or "<set" in low or "@keyframes" in low
