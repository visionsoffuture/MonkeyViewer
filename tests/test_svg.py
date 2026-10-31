"""SVG preview: SMIL and CSS animations evaluated per frame, rendering, Run SVG from the code view."""

import io
import re

import pytest

from viewer import svg_anim

SPINNER = """<svg width="400" height="400" viewBox="0 0 400 400" xmlns="http://www.w3.org/2000/svg">
  <style>
    .core { transform-origin: 200px 160px; animation: breathe 2s linear infinite; }
    .dot { animation: blink 1s infinite both; fill: #ffffff; }
    .dot2 { animation-delay: .5s; }
    @keyframes breathe { 50% { transform: scale(.5); } }
    @keyframes blink { 0%, 100% { opacity: 0; } 50% { opacity: 1; } }
  </style>
  <rect width="400" height="400" fill="#000"/>
  <g id="ring" transform="rotate(0 200 160)">
    <animateTransform attributeName="transform" type="rotate" from="0 200 160" to="360 200 160" dur="4s"
                      repeatCount="indefinite"/>
    <circle cx="200" cy="160" r="90" stroke="#f00" stroke-width="10" fill="none" stroke-dasharray="100 500"/>
  </g>
  <circle class="core" cx="200" cy="160" r="40" fill="#00f"/>
  <circle class="dot" id="d1" cx="100" cy="320" r="5"/>
  <circle class="dot dot2" id="d2" cx="120" cy="320" r="5"/>
  <rect id="bar" x="0" y="380" width="0" height="10" fill="#0f0">
    <animate attributeName="width" values="0;400;0" keyTimes="0;0.5;1" dur="2s" begin="1s" fill="freeze"
             repeatCount="2"/>
  </rect>
  <circle id="c" cx="10" cy="10" r="5" fill="#ff0000">
    <animate attributeName="fill" from="#ff0000" to="#0000ff" dur="1s" fill="freeze"/>
    <set attributeName="r" to="9" begin="0.5s"/>
  </circle>
</svg>"""


def _el(svg, ident):
    from defusedxml import ElementTree as ET
    root = ET.fromstring(svg)
    return next(e for e in root.iter() if e.get("id") == ident or e.get("class") == ident)


def _style(el, prop):
    return dict(svg_anim.parse_decls(el.get("style"))).get(prop)


def test_values_colours_and_timing():
    assert svg_anim.clock("1.5s") == 1.5 and svg_anim.clock("200ms") == 0.2 and svg_anim.clock("0:01.5") == 1.5
    assert svg_anim.clock("click") is None
    assert svg_anim.interpolate("0 200 160", "360 200 160", 0.25) == "90 200 160"
    assert svg_anim.interpolate("#ff0000", "#0000ff", 0.5) == "#800080"
    assert svg_anim.parse_color("rgba(242,83,78,.18)")[3] == pytest.approx(0.18)
    assert svg_anim.parse_color("hsl(120, 100%, 25%)")[:3] == (0, 128, 0)
    ease = svg_anim.easing("ease-in-out")
    assert ease(0) == 0 and ease(1) == 1 and ease(0.25) < 0.25 < 0.75 < ease(0.75)
    assert svg_anim.easing("steps(4)")(0.3) == 0.25


def test_smil_and_css_frames():
    a = svg_anim.SvgAnimation(SPINNER)
    assert a.animated and a.end == float("inf")
    f1 = a.frame(1.0)
    assert re.search(r'id="ring" transform="rotate\(90 200 160\)"', f1)
    assert "scale(0.5 0.5)" in _el(f1, "core").get("transform")      # the 50% keyframe
    core = _el(a.frame(0.5), "core")               # half way to scale(.5), about the CSS transform-origin
    assert "scale(0.75 0.75)" in core.get("transform") and "translate(200 160)" in core.get("transform")
    assert _style(core, "transform-origin") == "0px 0px"
    f2 = a.frame(2.0)                              # bar: begins at 1 s, values 0;400;0 over 2 s
    assert _el(f2, "bar").get("width") == "400"
    assert _el(a.frame(1.5), "bar").get("width") == "200"
    assert _el(a.frame(9.0), "bar").get("width") == "0"           # frozen at the end of 2 repeats
    assert _el(a.frame(0.5), "d1") is not None
    assert float(_style(_el(a.frame(0.5), "d1"), "opacity")) == pytest.approx(1.0, abs=0.01)
    assert float(_style(_el(a.frame(0.5), "d2"), "opacity")) == pytest.approx(0.0, abs=0.01)   # delay .5 s
    c = _el(a.frame(0.75), "c")
    assert c.get("r") == "9" and _style(c, "fill").startswith("#")
    assert _el(a.frame(0.25), "c").get("r") == "5"
    assert _style(_el(a.frame(5.0), "c"), "fill") == "#0000ff"   # fill="freeze"


def test_static_css_transform_becomes_an_attribute():
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><style>.r { transform: rotate(45deg);'
           ' transform-box: fill-box; transform-origin: center; }</style>'
           '<rect class="r" id="r" x="10" y="10" width="20" height="20"/></svg>')
    a = svg_anim.SvgAnimation(svg)
    assert not a.animated
    r = _el(a.frame(0), "r")
    assert r.get("transform") == "translate(20 20) rotate(45) translate(-20 -20)"


def test_entities_are_refused_and_drawn_statically():
    from viewer import svg_view
    bomb = ('<?xml version="1.0"?><!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg" '
            'width="10" height="10"><text>&a;</text></svg>')
    with pytest.raises(Exception):
        svg_anim.SvgAnimation(bomb)
    assert svg_view.is_svg("x.svg") and svg_view.is_svg("x.xml", '<?xml version="1.0"?>\n<svg>')
    assert not svg_view.is_svg("x.xml", "<root/>")


def test_render_draws_dashes_and_css():
    from viewer import svg_view
    img = svg_view.render(svg_anim.SvgAnimation(SPINNER).frame(0.0), 0.5)
    assert img.size == (200, 200)
    px_ = img.convert("RGB").getpixel((100, 80))   # centre of the blue core circle (scaled)
    assert px_[2] > 200 and px_[0] < 60
    buf = io.BytesIO()
    img.save(buf, "PNG")
    assert buf.getvalue()[:4] == b"\x89PNG"
