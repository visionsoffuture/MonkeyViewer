"""Weather for Georgian cities from MET Norway (api.met.no, free - also for organisations - data under CC BY 4.0).

The ONLY network connection Monkey Viewer makes: one HTTPS request for the chosen city's coordinates, at most
every 30 minutes (cached on disk, the server's Expires respected). No files, names or user data are sent.
The Group Policy "Turn off the weather" (DisableWeather) stops it completely.
"""

import datetime
import json
import math
import os
import ssl
import time
import urllib.request

from . import app_info

API = "https://api.met.no/weatherapi/locationforecast/2.0/compact?lat={lat:.4f}&lon={lon:.4f}"
USER_AGENT = f"{app_info.APP_ID}/{app_info.VERSION} (+https://github.com/visionsoffuture/MonkeyViewer)"
MIN_REFRESH = 30 * 60                    # seconds between requests, even when the server allows more
GEORGIA = datetime.timezone(datetime.timedelta(hours=4))     # Georgia: UTC+4 all year

# key, English, Georgian, latitude, longitude
CITIES = [
    ("tbilisi", "Tbilisi", "თბილისი", 41.7151, 44.8271),
    ("batumi", "Batumi", "ბათუმი", 41.6168, 41.6367),
    ("kutaisi", "Kutaisi", "ქუთაისი", 42.2679, 42.6946),
    ("rustavi", "Rustavi", "რუსთავი", 41.5495, 44.9932),
    ("gori", "Gori", "გორი", 41.9842, 44.1158),
    ("zugdidi", "Zugdidi", "ზუგდიდი", 42.5088, 41.8709),
    ("poti", "Poti", "ფოთი", 42.1462, 41.6714),
    ("kobuleti", "Kobuleti", "ქობულეთი", 41.8214, 41.7792),
    ("ozurgeti", "Ozurgeti", "ოზურგეთი", 41.9244, 42.0070),
    ("zestaponi", "Zestaponi", "ზესტაფონი", 42.1100, 43.0522),
    ("samtredia", "Samtredia", "სამტრედია", 42.1537, 42.3517),
    ("ambrolauri", "Ambrolauri", "ამბროლაური", 42.5205, 43.1625),
    ("mestia", "Mestia", "მესტია", 43.0458, 42.7286),
    ("akhaltsikhe", "Akhaltsikhe", "ახალციხე", 41.6390, 42.9826),
    ("borjomi", "Borjomi", "ბორჯომი", 41.8394, 43.3794),
    ("mtskheta", "Mtskheta", "მცხეთა", 41.8458, 44.7208),
    ("gudauri", "Gudauri", "გუდაური", 42.4767, 44.4790),
    ("telavi", "Telavi", "თელავი", 41.9198, 45.4731),
    ("sighnaghi", "Sighnaghi", "სიღნაღი", 41.6197, 45.9219),
    ("marneuli", "Marneuli", "მარნეული", 41.4759, 44.8081),
]
CITY = {c[0]: c for c in CITIES}

# MET symbol (without _day / _night) -> (icon kind, description)
KINDS = [
    ("thunder", "thunder", "Thunder"), ("sleet", "sleet", "Sleet"), ("snowshowers", "snow", "Snow showers"),
    ("heavysnow", "snow", "Heavy snow"), ("lightsnow", "snow", "Light snow"), ("snow", "snow", "Snow"),
    ("lightrainshowers", "showers", "Light rain showers"), ("rainshowers", "showers", "Rain showers"),
    ("heavyrain", "rain", "Heavy rain"), ("lightrain", "rain", "Light rain"), ("rain", "rain", "Rain"),
    ("fog", "fog", "Fog"), ("partlycloudy", "partly", "Partly cloudy"), ("cloudy", "cloudy", "Cloudy"),
    ("fair", "fair", "Fair"), ("clearsky", "clear", "Clear sky"),
]
WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def city_name(key, georgian):
    c = CITY.get(key) or CITY["tbilisi"]
    return c[2] if georgian else c[1]


def describe(symbol):
    """'lightrainshowers_day' -> ('showers', 'Rain showers', night: False)"""
    base, _, period = (symbol or "").partition("_")
    for key, kind, text in KINDS:                  # most specific first: 'lightrainshowers' is showers
        if key in base:
            return kind, text, period == "night"
    return "cloudy", "Cloudy", period == "night"


# ─────────────────────────────── fetching ───────────────────────────────
def _ssl_context():
    ctx = ssl.create_default_context()
    try:
        if ctx.cert_store_stats().get("x509_ca", 0) == 0 and os.path.exists("/usr/bin/security"):
            # a frozen macOS app has no CA file of its own: use the system's root certificates
            import subprocess  # nosec B404 - fixed system tool, fixed arguments
            pem = subprocess.run(["/usr/bin/security", "find-certificate", "-a", "-p",  # nosec B603
                                  "/System/Library/Keychains/SystemRootCertificates.keychain"],
                                 capture_output=True, text=True, timeout=10).stdout
            if pem:
                ctx.load_verify_locations(cadata=pem)
    except (OSError, ssl.SSLError, ValueError):
        pass
    return ctx


def fetch(lat, lon, timeout=12):
    """(json dict, seconds until the server wants the next request)."""
    if os.environ.get("MONKEYVIEWER_OFFLINE"):
        raise OSError("offline (MONKEYVIEWER_OFFLINE)")
    req = urllib.request.Request(API.format(lat=lat, lon=lon), headers={"User-Agent": USER_AGENT,
                                                                        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:  # nosec B310 - fixed https URL
        data = json.loads(resp.read(4_000_000).decode("utf-8"))
        expires = resp.headers.get("Expires")
    wait = MIN_REFRESH
    if expires:
        try:
            from email.utils import parsedate_to_datetime
            wait = max(MIN_REFRESH, (parsedate_to_datetime(expires).timestamp() - time.time()))
        except (TypeError, ValueError):
            pass
    return data, wait


def cache_path():
    from . import winutil
    return os.path.join(winutil.config_dir(), "weather.json")


def load_cache(city):
    try:
        with open(cache_path(), encoding="utf-8") as fh:
            entry = json.load(fh).get(city)
    except (OSError, ValueError, AttributeError):
        return None
    return entry if isinstance(entry, dict) and "data" in entry else None


def save_cache(city, data, next_at):
    path = cache_path()
    try:
        with open(path, encoding="utf-8") as fh:
            store = json.load(fh)
        if not isinstance(store, dict):
            store = {}
    except (OSError, ValueError):
        store = {}
    store[city] = {"data": data, "fetched": time.time(), "next": next_at}
    store = dict(sorted(store.items(), key=lambda kv: -kv[1].get("fetched", 0))[:4])    # a few cities at most
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(store, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def get(city, force=False):
    """Forecast for a city key: (summary, fetched_at) from the cache when fresh, else from the server."""
    entry = load_cache(city)
    now = time.time()
    if entry and not force and now < entry.get("next", 0):
        return summarise(entry["data"]), entry["fetched"]
    c = CITY.get(city) or CITY["tbilisi"]
    try:
        data, wait = fetch(c[3], c[4])
    except Exception:
        if entry:                                   # offline: the last forecast, marked with its time
            return summarise(entry["data"]), entry["fetched"]
        raise
    save_cache(city, data, now + wait)
    return summarise(data), now


# ─────────────────────────────── summarising ───────────────────────────────
def _local(ts):
    return datetime.datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(GEORGIA)


def summarise(data, now=None):
    """{'now': {...}, 'days': [{date, min, max, symbol, rain}...]} from a locationforecast response."""
    series = (data or {}).get("properties", {}).get("timeseries") or []
    if not series:
        raise ValueError("no forecast data")
    now = now or datetime.datetime.now(GEORGIA)
    current = None
    for e in series:
        if _local(e["time"]) >= now - datetime.timedelta(minutes=30):
            current = e
            break
    current = current or series[0]
    d = current["data"]
    det = d.get("instant", {}).get("details", {})
    sym = ((d.get("next_1_hours") or d.get("next_6_hours") or d.get("next_12_hours") or {})
           .get("summary", {}).get("symbol_code"))
    out_now = {"temp": det.get("air_temperature"), "wind": det.get("wind_speed"),
               "humidity": det.get("relative_humidity"), "symbol": sym, "time": current["time"]}
    days = {}
    for e in series:
        t = _local(e["time"])
        if t.date() < now.date():
            continue
        day = days.setdefault(t.date(), {"temps": [], "rain": 0.0, "symbol": None, "sym_dist": 99})
        det = e["data"].get("instant", {}).get("details", {})
        if det.get("air_temperature") is not None:
            day["temps"].append(det["air_temperature"])
        n6 = e["data"].get("next_6_hours")
        n1 = e["data"].get("next_1_hours")
        if n6 and e["time"][11:13] in ("00", "06", "12", "18"):     # 6-hour totals, each counted once
            day["rain"] += n6.get("details", {}).get("precipitation_amount", 0.0) or 0.0
            for k in ("air_temperature_max", "air_temperature_min"):
                v = n6.get("details", {}).get(k)
                if v is not None:
                    day["temps"].append(v)
        period = n1 or n6 or e["data"].get("next_12_hours")
        if period and period.get("summary", {}).get("symbol_code"):
            dist = abs(t.hour - 13)                  # the day's symbol: the one nearest early afternoon
            if dist < day["sym_dist"]:
                day["symbol"], day["sym_dist"] = period["summary"]["symbol_code"], dist
    out_days = []
    for date in sorted(days)[:8]:
        d = days[date]
        if not d["temps"]:
            continue
        out_days.append({"date": date.isoformat(), "weekday": date.weekday(), "min": min(d["temps"]),
                         "max": max(d["temps"]), "symbol": d["symbol"], "rain": round(d["rain"], 1)})
    return {"now": out_now, "days": out_days}


# ─────────────────────────────── icons ───────────────────────────────
_ICONS = {}


def icon_image(kind, night=False, size=20, dark=True):
    """Weather pictogram drawn with Pillow (same look on every platform), as a PIL RGBA image."""
    key = (kind, night, size, dark)
    if key in _ICONS:
        return _ICONS[key]
    from PIL import Image, ImageDraw
    n = size * 4
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    sun, moon = (255, 196, 61, 255), (206, 214, 240, 255)
    cloud = (214, 221, 235, 255) if dark else (160, 170, 190, 255)
    cloud_dark = (150, 160, 182, 255) if dark else (118, 128, 150, 255)
    rain, snow, bolt = (94, 160, 255, 255), (235, 242, 255, 255) if dark else (120, 160, 230, 255), (255, 204, 0, 255)

    def body(cx, cy, r):
        if night:
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=moon)
            d.ellipse((cx - r * 0.35, cy - r * 1.15, cx + r * 1.45, cy + r * 0.65), fill=(0, 0, 0, 0))
        else:
            for i in range(8):
                a = i * math.pi / 4
                x0, y0 = cx + math.cos(a) * r * 1.35, cy + math.sin(a) * r * 1.35
                x1, y1 = cx + math.cos(a) * r * 1.75, cy + math.sin(a) * r * 1.75
                d.line((x0, y0, x1, y1), fill=sun, width=max(2, n // 22))
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=sun)

    def cloud_shape(x, y, w, color):
        h = w * 0.55
        d.ellipse((x, y + h * 0.35, x + w * 0.5, y + h), fill=color)
        d.ellipse((x + w * 0.2, y, x + w * 0.75, y + h * 0.85), fill=color)
        d.ellipse((x + w * 0.5, y + h * 0.25, x + w, y + h), fill=color)
        d.rectangle((x + w * 0.25, y + h * 0.6, x + w * 0.78, y + h), fill=color)

    if kind == "clear":
        body(n * 0.5, n * 0.5, n * 0.22)
    elif kind in ("fair", "partly"):
        body(n * 0.38, n * 0.38, n * 0.18)
        cloud_shape(n * 0.28, n * 0.42, n * (0.6 if kind == "partly" else 0.5), cloud)
    else:
        top = n * 0.12
        cloud_shape(n * 0.1, top, n * 0.8, cloud_dark if kind in ("rain", "thunder", "sleet") else cloud)
        base = top + n * 0.8 * 0.55
        if kind in ("rain", "showers", "sleet"):
            for i, x in enumerate((0.3, 0.5, 0.7)):
                if kind == "sleet" and i == 1:
                    d.ellipse((n * x - n * 0.05, base + n * 0.1, n * x + n * 0.05, base + n * 0.2), fill=snow)
                    continue
                d.line((n * x, base + n * 0.06, n * x - n * 0.06, base + n * 0.24), fill=rain, width=max(2, n // 16))
        elif kind == "snow":
            for x, dy in ((0.3, 0.1), (0.5, 0.2), (0.7, 0.1)):
                d.ellipse((n * x - n * 0.05, base + n * dy, n * x + n * 0.05, base + n * dy + n * 0.1), fill=snow)
        elif kind == "thunder":
            pts = [(n * 0.52, base + n * 0.02), (n * 0.38, base + n * 0.18), (n * 0.5, base + n * 0.18),
                   (n * 0.42, base + n * 0.32), (n * 0.62, base + n * 0.12), (n * 0.5, base + n * 0.12)]
            d.polygon(pts, fill=bolt)
        elif kind == "fog":
            for i in range(3):
                y = base + n * (0.04 + 0.09 * i)
                d.line((n * 0.18, y, n * 0.82, y), fill=cloud, width=max(2, n // 18))
    out = img.resize((size, size), Image.LANCZOS)
    _ICONS[key] = out
    return out
