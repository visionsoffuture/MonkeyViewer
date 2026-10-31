"""Calculator and weather (no network: the forecast comes from a recorded-format sample)."""

import datetime
from decimal import Decimal

import pytest

import samples
from viewer import calc_view, weather


@pytest.mark.parametrize("expr, result", [
    ("0.1+0.2", "0.3"), ("200+10%", "220"), ("200-10%", "180"), ("50*10%", "5"), ("2(3+4)", "14"),
    ("2^10", "1 024"), ("√16+1", "5"), ("(1+2)²", "9"), ("7÷2", "3.5"), ("-(-3)", "3"), ("((2+3)", "5"),
    ("3,5*2", "7"), ("1e20*1e5", "1e+25"), ("123456789*1000", "123 456 789 000"),
    ("2×3−1÷4", "5.75"), ("1/3", "0.333333333333333"),
])
def test_calculator_arithmetic(expr, result):
    assert calc_view.format_number(calc_view.evaluate(expr)) == result


@pytest.mark.parametrize("expr", ["10/0", "7/", "abc", "", "√-4", "(-8)^0.5", "9^999999"])
def test_calculator_refuses_nonsense(expr):
    with pytest.raises(calc_view.CalcError):
        calc_view.evaluate(expr)


def test_calculator_never_evaluates_code():
    for evil in ("__import__('os')", "1;2", "open('x')", "2**2**2**2**2"):
        with pytest.raises(calc_view.CalcError):
            calc_view.evaluate(evil)
    assert calc_view.evaluate("2^2^3") == Decimal(256)                    # right-associative power


def test_weather_summary_and_symbols():
    data = samples.met_forecast()
    now = datetime.datetime(2026, 10, 27, 12, 10, tzinfo=weather.GEORGIA)
    s = weather.summarise(data, now)
    assert s["now"]["temp"] == pytest.approx(10.0) and s["now"]["symbol"] == "partlycloudy_day"
    assert s["days"][0]["date"] == "2026-10-27" and len(s["days"]) >= 7
    day2 = s["days"][1]
    assert day2["min"] <= day2["max"] and day2["rain"] == pytest.approx(6.0)   # 4 x 1.5 mm
    assert weather.describe("heavysnowshowers_day")[:2] == ("snow", "Snow showers")
    assert weather.describe("lightrainshowers_night") == ("showers", "Light rain showers", True)
    assert weather.describe("partlycloudy_day")[0] == "partly"
    assert weather.describe("rainandthunder")[0] == "thunder"
    assert weather.describe(None)[0] == "cloudy"
    for kind in ("clear", "fair", "partly", "cloudy", "fog", "rain", "showers", "sleet", "snow", "thunder"):
        img = weather.icon_image(kind, night=kind == "clear", size=24)
        assert img.size == (24, 24) and img.getbbox() is not None


def test_weather_cache_and_offline(monkeypatch):
    calls = []

    def fake_fetch(lat, lon, timeout=12):
        calls.append((lat, lon))
        return samples.met_forecast(), weather.MIN_REFRESH
    monkeypatch.setattr(weather, "fetch", fake_fetch)
    summary, fetched = weather.get("batumi")
    assert calls == [(41.6168, 41.6367)] and summary["days"]
    weather.get("batumi")                                   # fresh in the cache: no second request
    assert len(calls) == 1

    def offline(*_a, **_k):
        raise OSError("no network")
    monkeypatch.setattr(weather, "fetch", offline)
    again, _ = weather.get("batumi", force=True)            # offline: the last forecast stays available
    assert again["days"]
    with pytest.raises(OSError):
        weather.get("mestia")
    assert "MonkeyViewer/" in weather.USER_AGENT and "github.com" in weather.USER_AGENT


def test_monkey_mark_logo_spinner_and_icons():
    """The monkey renders as logo, its loading animation moves, and every icon file is the monkey design."""
    import os
    from PIL import Image
    from viewer import monkey
    logo = monkey.render(monkey.logo_svg(), 64)
    assert logo.size == (64, 64) and logo.getpixel((4, 32))[:3] == (0xff, 0xc9, 0x4d)    # yellow tile
    a, b = (monkey.render(monkey.spinner_svg(i), 48).tobytes() for i in (0, monkey.FRAMES // 4))
    assert a != b                                                                        # it moves
    assert monkey.spinner_svg(0) == monkey.spinner_svg(monkey.FRAMES)                    # and loops
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with Image.open(os.path.join(root, "monkeyviewer.ico")) as ico:
        assert (16, 16) in ico.info["sizes"] and (256, 256) in ico.info["sizes"]
    for name in ("pdf", "lua", "cad", "file"):
        with Image.open(os.path.join(root, "packaging", "icons", f"{name}.ico")) as ico:
            ico.size = (48, 48)
            px = ico.convert("RGBA").getpixel((30, 32))
        assert px[3] == 255 and px[0] > 200 and px[1] > 150                              # the yellow badge
