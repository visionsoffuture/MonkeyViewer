"""Virtual hex viewer — opens files of any size instantly (memory-mapped)."""

import mmap
import os
import re
import tkinter as tk
from tkinter import ttk

from . import formats, theme
from .base import BaseTab
from .theme import C, px
from .i18n import T

ROW = 16


class HexTab(BaseTab):
    kind = "hex"
    searchable = True

    def menu_title(self):
        return T("Bytes")

    def fill_menu(self, name, m):
        if name == "tools":
            m.add_command(label=T("Go to offset\u2026"), command=self.goto_dialog)
            m.add_command(label=T("Copy selection"), command=self.copy_selection)

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.top = 0
        self.sel = None          # (start, end) byte range highlighted
        self.cursor = None
        self.matches, self.current, self.needle = [], -1, b""
        self._job = None
        self.fh = self.data = None

    def badge(self):
        return theme.badge_image("HEX", theme.KIND_COLORS["binary"])

    def load(self):
        self.size = os.path.getsize(self.path)
        self.fh = open(self.path, "rb")
        self.data = mmap.mmap(self.fh.fileno(), 0, access=mmap.ACCESS_READ) if self.size else b""
        bar = self.bar
        bar.label(T("{0}  ·  {1:,} bytes", formats.human_size(self.size), self.size), muted=False)
        bar.button(T("Go to offset…"), "right", self.goto_dialog, T("Jump to a byte offset"))
        bar.button(T("Copy Hex"), "copy", self.copy_selection, T("Copy the highlighted bytes as hex"), side="right")
        self.canvas = tk.Canvas(self.body, bg=C["bg"], highlightthickness=0, bd=0, takefocus=1)
        self.vsb = ttk.Scrollbar(self.body, orient="vertical", command=self._on_scrollbar)
        self.vsb.pack(side="right", fill="y")
        self.canvas.pack(fill="both", expand=True)
        c = self.canvas
        c.bind("<Configure>", lambda e: self.redraw())
        c.bind("<MouseWheel>", lambda e: self.scroll_rows(theme.wheel_units(e, 3)))
        c.bind("<Button-4>", lambda e: self.scroll_rows(-3))
        c.bind("<Button-5>", lambda e: self.scroll_rows(3))
        c.bind("<Button-1>", self._on_click)
        for key, rows in (("<Prior>", -1), ("<Next>", 1)):
            c.bind(key, lambda e, r=rows: self.scroll_rows(r * self.visible_rows()))
        c.bind("<Up>", lambda e: self.scroll_rows(-1))
        c.bind("<Down>", lambda e: self.scroll_rows(1))
        c.bind("<Home>", lambda e: self.set_top(0))
        c.bind("<End>", lambda e: self.set_top(self.total_rows()))

    # ── geometry ──
    def metrics(self):
        f = theme.CODE_FONT
        return f.measure("0"), f.metrics("linespace") + px(3)

    def total_rows(self):
        return (self.size + ROW - 1) // ROW

    def visible_rows(self):
        return max(1, (self.canvas.winfo_height() - px(16)) // self.metrics()[1])

    def set_top(self, row):
        self.top = max(0, min(row, max(0, self.total_rows() - self.visible_rows())))
        self.redraw()

    def scroll_rows(self, n):
        self.set_top(self.top + n)
        return "break"

    def _on_scrollbar(self, *args):
        if args[0] == "moveto":
            self.set_top(int(float(args[1]) * self.total_rows()))
        elif args[0] == "scroll":
            n = int(args[1]) * (self.visible_rows() if args[2] == "pages" else 1)
            self.scroll_rows(n)

    def columns(self):
        cw, _lh = self.metrics()
        x_off = px(16)
        x_hex = x_off + cw * 10
        x_ascii = x_hex + cw * (ROW * 3 + 2)
        return cw, x_off, x_hex, x_ascii

    def redraw(self):
        c = self.canvas
        c.delete("all")
        font = theme.CODE_FONT
        cw, lh = self.metrics()
        _cw, x_off, x_hex, x_ascii = self.columns()
        rows = self.visible_rows()
        y = px(8)
        c.create_rectangle(0, 0, x_hex - cw, c.winfo_height(), fill=C["bg_deep"], outline="")
        for r in range(rows):
            row = self.top + r
            start = row * ROW
            if start >= self.size:
                break
            chunk = self.data[start:start + ROW]
            self._highlight(c, start, len(chunk), y, lh, cw, x_hex, x_ascii)
            hexs = " ".join(f"{b:02X}" for b in chunk[:8])
            if len(chunk) > 8:
                hexs += "  " + " ".join(f"{b:02X}" for b in chunk[8:])
            text = "".join(chr(b) if 32 <= b < 127 else "·" for b in chunk)
            c.create_text(x_off, y, text=f"{start:08X}", anchor="nw", font=font, fill=C["gutter"])
            c.create_text(x_hex, y, text=hexs, anchor="nw", font=font, fill=C["fg"])
            c.create_text(x_ascii, y, text=text, anchor="nw", font=font, fill=C["syn_string"])
            y += lh
        total = max(1, self.total_rows())
        self.vsb.set(self.top / total, min(1.0, (self.top + rows) / total))
        if self.app.active is self:
            self.app.update_status()

    def _highlight(self, c, start, n, y, lh, cw, x_hex, x_ascii):
        ranges = []
        if self.sel:
            ranges.append((self.sel, C["find_cur_bg"]))
        for m in self.matches:
            if m[0] < start + n and m[1] > start and m != self.sel:
                ranges.append((m, C["find"]))
        if self.cursor is not None and start <= self.cursor < start + n:
            ranges.append(((self.cursor, self.cursor + 1), C["selection"]))
        for (a, b), color in ranges:
            a, b = max(a, start), min(b, start + n)
            if a >= b:
                continue
            for i in range(a - start, b - start):
                gap = 1 if i >= 8 else 0
                x = x_hex + cw * (i * 3 + gap)
                c.create_rectangle(x - 1, y, x + cw * 2 + 1, y + lh - 2, fill=color, outline="")
                xa = x_ascii + cw * i
                c.create_rectangle(xa, y, xa + cw, y + lh - 2, fill=color, outline="")

    def _on_click(self, event):
        self.canvas.focus_set()
        cw, lh = self.metrics()
        _cw, _x_off, x_hex, x_ascii = self.columns()
        row = self.top + max(0, (event.y - px(8)) // lh)
        if x_hex <= event.x < x_ascii - cw:
            rel = (event.x - x_hex) / cw
            col = int(rel // 3) if rel < 24 else int((rel - 1) // 3)
        elif event.x >= x_ascii:
            col = int((event.x - x_ascii) // cw)
        else:
            return
        offset = row * ROW + max(0, min(ROW - 1, col))
        if offset < self.size:
            self.cursor = offset
            self.redraw()

    def goto_dialog(self):
        value = theme.ask_string(self.frame, T("Go to offset"), T("Byte offset (decimal, or hex like 0x1A2B):"),
                                 hint=T("File size: {0:,} bytes", self.size))
        if not value:
            return
        try:
            offset = int(value.strip(), 0)
        except ValueError:
            self.toast(T("That isn't a valid offset."), "warning")
            return
        offset = max(0, min(offset, max(0, self.size - 1)))
        self.cursor = offset
        self.set_top(offset // ROW - 2)

    def copy_selection(self):
        rng = self.sel or ((self.cursor, self.cursor + 1) if self.cursor is not None else None)
        if not rng:
            self.toast(T("Click a byte or search for something first."), "info")
            return
        a, b = rng
        self.app.set_clipboard(" ".join(f"{x:02X}" for x in self.data[a:min(b, a + 1_000_000)]))
        self.toast(T("Copied {0:,} bytes as hex", b - a))

    def edit_action(self, action):
        if action == "copy":
            self.copy_selection()
            return True
        return False

    # ── search: text (UTF-8) or hex bytes like "4D 5A 90" ──
    def find_update(self, needle, case, mode="jump"):
        self.matches, self.current, self.sel = [], -1, None
        parsed = self._parse_needle(needle)
        if not parsed:
            self.redraw()
            return -1, 0
        raw, is_hex = parsed
        pattern = re.compile(re.escape(raw), 0 if case or is_hex else re.IGNORECASE)
        for m in pattern.finditer(self.data):
            self.matches.append((m.start(), m.end()))
            if len(self.matches) >= 5000:
                break
        if self.matches and mode in ("jump", "keep"):
            self._goto(0)
        else:
            self.redraw()
        return self.current, len(self.matches)

    @staticmethod
    def _parse_needle(needle):
        text = needle.strip()
        if not text:
            return None
        compact = text.replace(" ", "")
        if compact.lower().startswith("0x"):
            compact = compact[2:]
            if re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", compact):
                return bytes.fromhex(compact), True
        if re.fullmatch(r"(?:[0-9A-Fa-f]{2})+", compact) and " " in text:
            return bytes.fromhex(compact), True
        return needle.encode("utf-8"), False

    def find_step(self, direction):
        if not self.matches:
            return -1, 0
        self._goto((self.current + direction) % len(self.matches))
        return self.current, len(self.matches)

    def _goto(self, i):
        self.current = i
        self.sel = self.matches[i]
        row = self.sel[0] // ROW
        if not self.top <= row < self.top + self.visible_rows():
            self.top = max(0, row - 3)
        self.set_top(self.top)

    def find_clear(self, commit=False):
        self.matches, self.current = [], -1
        if not commit:
            self.sel = None
        self.redraw()

    def status(self):
        segs = []
        if self.cursor is not None and self.cursor < self.size:
            b = self.data[self.cursor]
            segs.append(T("Offset {0:,}", self.cursor) + f" (0x{self.cursor:X})  =  0x{b:02X}  {b}")
        segs += [f"{formats.human_size(self.size)}", "Hex"]
        return segs

    def destroy(self):
        try:
            if isinstance(self.data, mmap.mmap):
                self.data.close()
            if self.fh:
                self.fh.close()
        except Exception:  # noqa: BLE001
            pass
        super().destroy()
