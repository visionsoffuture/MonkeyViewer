"""The weather corner: current weather of a Georgian city at the right end of the status bar; a click opens the
forecast for the coming days. Turned off by the user (View > Weather) or by policy (DisableWeather)."""

import datetime
import time
import tkinter as tk

from PIL import ImageTk

from . import i18n, policy, theme, weather
from .i18n import T
from .theme import C, FONTS, ToolButton, px

CHECK_EVERY = 10 * 60 * 1000          # ms; the cache decides whether a request is really made


def allowed():
    return not policy.get_bool("DisableWeather")


def _deg(v):
    if v is None:
        return "–"
    r = round(v)
    return f"{0 if r == 0 else r}°"


class WeatherCorner:
    def __init__(self, app, bar):
        self.app = app
        self.summary = None
        self.fetched = None
        self.failed = False
        self.popup = None
        self._job = None
        self._photos = {}
        self.label = tk.Label(bar, bg=C["chrome"], fg=C["fg_dim"], font=FONTS["small"], padx=px(10),
                              cursor="hand2", compound="left")
        self.tip = theme.Tooltip(self.label, T("Weather - click for the forecast"))
        self.label.bind("<Button-1>", lambda e: self.toggle_popup())
        self.label.bind("<Enter>", lambda e: self.label.configure(bg=C["hover"]), add="+")
        self.label.bind("<Leave>", lambda e: self.label.configure(bg=C["chrome"]), add="+")
        self._menu_open = False
        self.apply_settings(initial=True)

    # ── settings ──
    @property
    def city(self):
        key = self.app.settings.get("weather_city", "tbilisi")
        return key if key in weather.CITY else "tbilisi"

    def enabled(self):
        return allowed() and bool(self.app.settings.get("weather", True))

    def apply_settings(self, initial=False):
        if self.enabled():
            if not self.label.winfo_manager():
                others = [w for w in self.label.master.pack_slaves() if w is not self.label]
                if others:                             # packed first = the far right corner
                    self.label.pack(side="right", fill="y", before=others[0])
                else:
                    self.label.pack(side="right", fill="y")
            self._show()
            self._schedule(1500 if initial else 10)
        else:
            self.label.pack_forget()
            self.close_popup()
            self._cancel()

    def set_city(self, key):
        self.app.settings["weather_city"] = key
        self.summary, self.fetched = None, None
        self._show()
        self._schedule(10)
        if self.popup is not None:
            self.close_popup()
            self.app.root.after(50, self.toggle_popup)

    def set_enabled(self, on):
        self.app.settings["weather"] = bool(on)
        self.apply_settings()

    def fill_menu(self, m):
        """View > Weather."""
        if not allowed():
            m.add_command(label=T("Turned off by your administrator"), state="disabled")
            return
        m.add_checkbutton(label=T("Show the weather"), command=lambda: self.set_enabled(not self.enabled()),
                          variable=theme.menu_var(m, "bool", self.enabled()))
        m.add_separator()
        ka = i18n.current() == "ka"
        var = theme.menu_var(m, "str", self.city)
        for key, *_rest in weather.CITIES:
            m.add_radiobutton(label=weather.city_name(key, ka), value=key, variable=var,
                              command=lambda k=key: self.set_city(k))

    # ── data ──
    def _cancel(self):
        if self._job is not None:
            try:
                self.app.root.after_cancel(self._job)
            except tk.TclError:
                pass
            self._job = None

    def _schedule(self, delay):
        self._cancel()
        self._job = self.app.root.after(delay, self.refresh)

    def refresh(self, force=False):
        self._job = None
        if not self.enabled():
            return
        city = self.city

        def done(ok, value):
            if city != self.city or not self.enabled():
                return
            if ok:
                self.summary, self.fetched = value
                self.failed = False
            else:
                self.failed = True
            self._show()
            if self.popup is not None and ok:
                self._fill_popup()
        self.app.run_in_thread(lambda: weather.get(city, force), done)
        self._schedule(CHECK_EVERY)

    def _photo(self, kind, night, size):
        key = (kind, night, size, theme.IS_DARK)
        if key not in self._photos:
            self._photos[key] = ImageTk.PhotoImage(weather.icon_image(kind, night, size, theme.IS_DARK))
        return self._photos[key]

    def _show(self):
        ka = i18n.current() == "ka"
        name = weather.city_name(self.city, ka)
        if not self.summary:
            self.label.configure(text=f"{name}  \u2013", image="", fg=C["fg_muted"] if self.failed else C["fg_dim"])
            self.tip.text = T("No connection to the weather service") if self.failed else \
                T("Weather - click for the forecast")
            return
        now = self.summary["now"]
        kind, text, night = weather.describe(now.get("symbol"))
        self.label.configure(image=self._photo(kind, night, px(16)), text=f" {name} {_deg(now.get('temp'))}", fg=C["fg_dim"])
        self.tip.text = f"{T(text)} · {T('click for the forecast')}"

    # ── popup ──
    def toggle_popup(self):
        if self.popup is not None:
            self.close_popup()
            return
        self.popup = tk.Toplevel(self.app.root)
        self.popup.withdraw()
        self.popup.overrideredirect(True)
        self.popup.configure(bg=C["border_strong"])
        self.body = tk.Frame(self.popup, bg=C["panel"], padx=px(16), pady=px(14))
        self.body.pack(fill="both", expand=True, padx=1, pady=1)
        self._fill_popup()
        self.popup.update_idletasks()
        w, h = max(px(340), self.popup.winfo_reqwidth()), self.popup.winfo_reqheight()
        x = self.label.winfo_rootx() + self.label.winfo_width() - w
        y = self.label.winfo_rooty() - h - px(4)
        self.popup.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.popup.deiconify()
        self.popup.lift()
        self.popup.bind("<Escape>", lambda e: self.close_popup())
        self.popup.focus_force()
        self.popup.bind("<FocusOut>", lambda e: self.app.root.after(150, self._maybe_close))
        if not self.summary or time.time() - (self.fetched or 0) > weather.MIN_REFRESH:
            self.refresh()

    def _maybe_close(self):
        if self.popup is None or self._menu_open:
            return
        try:
            focus = self.popup.focus_get()
        except (tk.TclError, KeyError):
            focus = None
        if focus is None or not str(focus).startswith(str(self.popup)):
            self.close_popup()

    def close_popup(self):
        if self.popup is not None:
            try:
                self.popup.destroy()
            except tk.TclError:
                pass
            self.popup = None

    def _fill_popup(self):
        b = self.body
        for w in b.winfo_children():
            w.destroy()
        ka = i18n.current() == "ka"
        head = tk.Frame(b, bg=C["panel"])
        head.pack(fill="x")
        self.city_btn = ToolButton(head, weather.city_name(self.city, ka) + "  \u25be", None, self._open_city_menu,
                                   T("Choose the city"), bg=C["panel"], hover=C["hover_strong"], pad=(6, 3))
        self.city_btn.pack(side="left")
        ToolButton(head, "", "close", self.close_popup, T("Close  (Esc)"), bg=C["panel"], hover=C["hover_strong"],
                   pad=(6, 3)).pack(side="right")
        ToolButton(head, "", "refresh", lambda: self.refresh(force=True), T("Refresh"), bg=C["panel"],
                   hover=C["hover_strong"], pad=(6, 3)).pack(side="right")
        if not self.summary:
            tk.Label(b, text=T("No connection to the weather service") if self.failed else T("Loading…"),
                     bg=C["panel"], fg=C["fg_muted"], font=FONTS["ui"], pady=px(24)).pack(fill="x")
            self._footer(b)
            return
        now = self.summary["now"]
        kind, text, night = weather.describe(now.get("symbol"))
        cur = tk.Frame(b, bg=C["panel"])
        cur.pack(fill="x", pady=(px(10), px(8)))
        tk.Label(cur, image=self._photo(kind, night, px(56)), bg=C["panel"]).pack(side="left")
        col = tk.Frame(cur, bg=C["panel"])
        col.pack(side="left", padx=(px(12), 0))
        tk.Label(col, text=_deg(now.get("temp")), font=FONTS["h1"], bg=C["panel"], fg=C["fg_bright"],
                 anchor="w").pack(fill="x")
        tk.Label(col, text=T(text), font=FONTS["ui"], bg=C["panel"], fg=C["fg"], anchor="w").pack(fill="x")
        facts = []
        if now.get("wind") is not None:
            facts.append(T("Wind {0} m/s", f"{now['wind']:.0f}"))
        if now.get("humidity") is not None:
            facts.append(T("Humidity {0}%", f"{now['humidity']:.0f}"))
        tk.Label(col, text="  ·  ".join(facts), font=FONTS["small"], bg=C["panel"], fg=C["fg_muted"],
                 anchor="w").pack(fill="x")
        tk.Frame(b, bg=C["border"], height=1).pack(fill="x", pady=(px(4), px(6)))
        grid = tk.Frame(b, bg=C["panel"])
        grid.pack(fill="x")
        today = datetime.datetime.now(weather.GEORGIA).date().isoformat()
        for r, day in enumerate(self.summary["days"][:7]):
            name = T("Today") if day["date"] == today else T(weather.WEEKDAYS[day["weekday"]])
            dkind, dtext, _n = weather.describe(day.get("symbol"))
            tk.Label(grid, text=name, font=FONTS["ui"], bg=C["panel"], fg=C["fg"], anchor="w").grid(
                row=r, column=0, sticky="w", pady=px(2))
            icon = tk.Label(grid, image=self._photo(dkind, False, px(22)), bg=C["panel"])
            icon.grid(row=r, column=1, padx=px(10))
            theme.Tooltip(icon, T(dtext))
            tk.Label(grid, text=_deg(day["max"]), font=FONTS["ui_bold"], bg=C["panel"], fg=C["fg_bright"],
                     anchor="e", width=4).grid(row=r, column=2, sticky="e")
            tk.Label(grid, text=_deg(day["min"]), font=FONTS["ui"], bg=C["panel"], fg=C["fg_muted"],
                     anchor="e", width=4).grid(row=r, column=3, sticky="e")
            rain = T("{0} mm", f"{day['rain']:.1f}") if day.get("rain", 0) >= 0.1 else ""
            tk.Label(grid, text=rain, font=FONTS["small"], bg=C["panel"], fg=C["accent"], anchor="e",
                     width=7).grid(row=r, column=4, sticky="e")
        grid.grid_columnconfigure(0, weight=1)
        self._footer(b)

    def _footer(self, b):
        when = ""
        if self.fetched:
            stamp = datetime.datetime.fromtimestamp(self.fetched).strftime("%H:%M")
            when = T("Updated {0}", stamp) + "  ·  "
        tk.Label(b, text=when + T("Data: MET Norway (CC BY 4.0)"), font=FONTS["tiny"], bg=C["panel"],
                 fg=C["fg_muted"], anchor="w").pack(fill="x", pady=(px(10), 0))

    def _open_city_menu(self):
        ka = i18n.current() == "ka"
        m = theme.popup_menu(self.app.root)
        var = theme.menu_var(m, "str", self.city)
        for key, *_rest in weather.CITIES:
            m.add_radiobutton(label=weather.city_name(key, ka), value=key, variable=var,
                              command=lambda k=key: self.set_city(k))
        self._menu_open = True                     # the menu takes the focus: keep the forecast open
        try:
            btn = self.city_btn
            theme.show_menu(m, btn.winfo_rootx(), btn.winfo_rooty() + btn.winfo_height(), anchor=btn)
        finally:
            self.app.root.after(300, lambda: setattr(self, "_menu_open", False))

    def destroy(self):
        self._cancel()
        self.close_popup()
