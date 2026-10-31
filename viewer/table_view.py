"""Data grid for specialist data files: SQLite / GeoPackage / MBTiles databases, dBASE (DBF) attribute tables
and Group Policy Registry.pol files. Everything is opened read-only."""

import csv
import io
import os
import sqlite3
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont

from . import formats, safeio, theme
from .base import BaseTab
from .theme import C, FONTS, px
from .i18n import T

MAX_ROWS = 200_000


# ─────────────────────────────── readers ───────────────────────────────
REG_TYPES = {0: "REG_NONE", 1: "REG_SZ", 2: "REG_EXPAND_SZ", 3: "REG_BINARY", 4: "REG_DWORD", 5: "REG_DWORD_BE",
             7: "REG_MULTI_SZ", 11: "REG_QWORD"}


def read_pol(path):
    """Registry.pol (Group Policy 'PReg' format) -> rows of Key, Value, Type, Data."""
    import struct
    data = open(path, "rb").read()
    if data[:4] != b"PReg":
        raise ValueError(T("Not a Group Policy registry file"))
    pos, rows = 8, []

    def wstr(p):
        end = p
        while data[end:end + 2] != b"\x00\x00":
            end += 2
        return data[p:end].decode("utf-16-le", "replace"), end + 2

    while pos + 2 <= len(data):
        if data[pos:pos + 2] != b"[\x00":
            break
        key, pos = wstr(pos + 2)
        pos += 2
        value, pos = wstr(pos)
        pos += 2
        rtype = struct.unpack_from("<I", data, pos)[0]
        pos += 6
        size = struct.unpack_from("<I", data, pos)[0]
        pos += 6
        raw = data[pos:pos + size]
        pos += size + 2
        if rtype in (1, 2):
            shown = raw.decode("utf-16-le", "replace").rstrip("\x00")
        elif rtype == 4 and size >= 4:
            n = struct.unpack("<I", raw[:4])[0]
            shown = f"{n}  (0x{n:X})"
        elif rtype == 11 and size >= 8:
            shown = str(struct.unpack("<Q", raw[:8])[0])
        elif rtype == 7:
            shown = " | ".join(x for x in raw.decode("utf-16-le", "replace").split("\x00") if x)
        else:
            shown = raw.hex(" ").upper()[:300]
        action = T("Delete value") if value.lower().startswith("**del.") else \
            T("Delete all values") if value.lower().startswith("**delvals") else T("Set")
        rows.append([key, value, REG_TYPES.get(rtype, str(rtype)), shown, action])
    return [T("Key"), T("Value"), T("Type"), T("Data"), T("Action")], rows, len(rows)


def _sqlite(path):
    return safeio.sqlite_readonly(path)


def list_sheets(path):
    ext = formats.ext_of(path)
    if ext == ".pol":
        return ["Policy settings"]
    if ext == ".dbf":
        return [os.path.splitext(os.path.basename(path))[0]]
    con = _sqlite(path)
    try:
        rows = con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view') "
                           "AND name NOT LIKE 'sqlite_%' ORDER BY type, name").fetchall()
        return [r[0] for r in rows]
    finally:
        con.close()


def read_sheet(path, sheet=None, max_rows=MAX_ROWS):
    """Returns (header, rows, total_rows_or_None)."""
    ext = formats.ext_of(path)
    if ext == ".pol":
        return read_pol(path)
    if ext == ".dbf":
        import shapefile
        from .gis import _shp_encoding
        with open(path, "rb") as fh:
            r = shapefile.Reader(dbf=fh, encoding=_shp_encoding(path), encodingErrors="replace")
            header = [f[0] for f in r.fields[1:]]
            rows = []
            for rec in r.iterRecords():
                rows.append(list(rec))
                if len(rows) >= max_rows:
                    break
            return header, rows, len(r)
    con = _sqlite(path)
    try:
        names = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','view')")]
        if sheet is None:
            sheet = next((n for n in names if not n.startswith("sqlite_")), None)
        if sheet not in names:                 # never interpolate a name that is not in the schema
            raise ValueError(T("Unknown table") if names else T("This database has no tables"))
        # the table name was checked against the database's own schema above and is quoted
        query = "SELECT * FROM " + safeio.quote_ident(sheet) + " LIMIT ?"  # nosec B608
        cur = con.execute(query, (int(max_rows),))
        header = [d[0] for d in cur.description]
        rows = [list(r) for r in cur.fetchall()]
        try:
            total = con.execute(f"SELECT COUNT(*) FROM {safeio.quote_ident(sheet)}").fetchone()[0]  # nosec B608
        except sqlite3.Error:
            total = None
        return header, rows, total
    finally:
        con.close()


def _col_name(i):
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def fmt(v):
    if v is None:
        return ""
    if isinstance(v, float):
        if v.is_integer() and abs(v) < 1e15:
            return str(int(v))
        return f"{v:.10g}"
    if isinstance(v, bytes):
        return f"<blob {len(v):,} bytes>"
    if hasattr(v, "strftime"):
        text = v.isoformat(sep=" ") if hasattr(v, "hour") else v.isoformat()
        return text[:-9] if text.endswith(" 00:00:00") else text
    return str(v)


def sort_key(text):
    t = text.replace(",", "").strip()
    try:
        return 0, float(t), ""
    except ValueError:
        return 1, 0.0, text.lower()


# ─────────────────────────────── the tab ───────────────────────────────
class TableTab(BaseTab):
    kind = "table"
    searchable = True

    def menu_title(self):
        return T("Table")

    def fill_menu(self, name, m):
        if name == "tools":
            if len(self.sheets) > 1:
                sub = theme.popup_menu(m)
                self._sheet_menu(sub)
                m.add_cascade(label=T("Sheet"), menu=sub)
            m.add_command(label=T("Copy selected rows"), command=self.copy_rows)
            m.add_command(label=T("Copy all"), command=self.copy_all)
            m.add_separator()
            m.add_command(label=T("Export as CSV\u2026"), command=self.export_csv)

    def print_document(self):
        if not self.header and not self.view_rows:
            return None
        from . import printing
        return printing.table_document(self.header, (r for _i, r in self.view_rows), self.title)

    def __init__(self, app, path=None, title=None):
        super().__init__(app, path, title)
        self.sheets = []
        self.sheet = None
        self.header, self.rows, self.view_rows, self.total = [], [], [], 0
        self._job = self._filter_job = None
        self.sort_col, self.sort_rev = None, False
        self.matches, self.match_i = [], -1
        self._build()

    def _build(self):
        bar = self.bar
        self.sheet_btn = bar.button(T("Sheet"), "table", tooltip=T("Sheet / table"), menu=self._sheet_menu)
        self.filter_var = tk.StringVar()
        box, self.filter_entry = theme.styled_entry(bar.left, self.filter_var, width=22, font=FONTS["small"])
        box.pack(side="left", padx=px(6), pady=px(8))
        self.filter_entry.insert(0, "")
        self.filter_hint = tk.Label(box, text=T("Filter rows…"), bg=C["input"], fg=C["fg_muted"], font=FONTS["small"])
        self.filter_hint.place(x=px(8), rely=0.5, anchor="w")
        self.filter_hint.bind("<Button-1>", lambda e: self.filter_entry.focus_set())
        self.filter_var.trace_add("write", lambda *_: self._on_filter())
        bar.divider()
        bar.button(T("Copy"), "copy", self.copy_rows, T("Copy selected rows (or all rows) as tab-separated text"))
        bar.button(T("Export CSV"), "export", self.export_csv, T("Save this sheet as CSV"))
        self.count_lbl = bar.label("", side="right")
        holder = tk.Frame(self.body, bg=C["bg"])
        holder.pack(fill="both", expand=True)
        holder.grid_rowconfigure(0, weight=1)
        holder.grid_columnconfigure(0, weight=1)
        self.tree = ttk.Treeview(holder, style="Grid.Treeview", show="headings", selectmode="extended")
        vsb = ttk.Scrollbar(holder, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(holder, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        hsb.grid(row=1, column=0, sticky="ew")
        self.tree.tag_configure("odd", background=C["row_alt"])
        self.tree.bind("<<TreeviewSelect>>", lambda e: self.app.update_status())

    def _sheet_menu(self, m):
        for name in self.sheets:
            m.add_command(label=name, command=lambda n=name: self.load_sheet(n))

    def load(self):
        src = self.path

        def work():
            sheets = list_sheets(src)
            first = sheets[0] if sheets else None
            return sheets, first, read_sheet(src, first if formats.ext_of(src) not in (".dbf", ".pol") else None)

        self.run_async(work, self._loaded, error=lambda exc: self.app.replace_with(self, "info", error=str(exc)),
                       text=T("Reading data…"))

    def _loaded(self, result):
        self.sheets, self.sheet, (header, rows, total) = result
        self.sheet_btn.set_text(T(self.sheet) if self.sheet == "Policy settings" else (self.sheet or T("Sheet")))
        if len(self.sheets) <= 1:
            self.sheet_btn.pack_forget()
        self._show(header, rows, total)

    def load_sheet(self, name):
        self.sheet = name
        self.sheet_btn.set_text(name)
        self.run_async(lambda: read_sheet(self.path, name), lambda r: self._show(*r), text=T("Reading {0}…", name))

    def _show(self, header, rows, total):
        self.header = header
        self.rows = [[fmt(v) for v in r] + [""] * (len(header) - len(r)) for r in rows]
        self.total = total if total is not None else len(rows)
        self.sort_col, self.sort_rev = None, False
        t = self.tree
        cols = ["#"] + [f"c{i}" for i in range(len(header))]
        t.configure(columns=cols)
        font = tkfont.Font(self.app.root, font=FONTS["small"])
        bold = tkfont.Font(self.app.root, font=FONTS["small_bold"])
        t.heading("#", text="#", anchor="e")
        t.column("#", width=px(56), stretch=False, anchor="e")
        sample = self.rows[:300]
        for i, name in enumerate(header):
            width = bold.measure(str(name)) + px(30)
            for r in sample:
                if i < len(r):
                    width = max(width, font.measure(r[i][:60]) + px(20))
            t.heading(f"c{i}", text=str(name), anchor="w", command=lambda k=i: self.sort_by(k))
            t.column(f"c{i}", width=min(px(340), max(px(60), width)), stretch=False, anchor="w")
        self._apply_filter()

    def _apply_filter(self):
        needle = self.filter_var.get().strip().lower()
        self.filter_hint.place_forget() if self.filter_var.get() else self.filter_hint.place(
            x=px(8), rely=0.5, anchor="w")
        if needle:
            self.view_rows = [(i, r) for i, r in enumerate(self.rows) if any(needle in c.lower() for c in r)]
        else:
            self.view_rows = list(enumerate(self.rows))
        if self.sort_col is not None:
            k = self.sort_col
            self.view_rows.sort(key=lambda ir: sort_key(ir[1][k] if k < len(ir[1]) else ""), reverse=self.sort_rev)
        self._refill()

    def _on_filter(self):
        if self._filter_job:
            self.app.root.after_cancel(self._filter_job)
        self._filter_job = self.app.root.after(200, self._run_filter)

    def _run_filter(self):
        self._filter_job = None
        self._apply_filter()

    def _refill(self):
        if self._job:
            self.app.root.after_cancel(self._job)
            self._job = None
        t = self.tree
        t.delete(*t.get_children())
        self._insert(0)
        shown = len(self.view_rows)
        more = f" (showing first {len(self.rows):,})" if self.total > len(self.rows) else ""
        flt = f"{shown:,} of " if shown != len(self.rows) else ""
        self.count_lbl.configure(text=T("{0}{1:,} rows{2}  ·  {3} columns", flt, self.total, more, len(self.header)))
        self.app.update_status()

    def _insert(self, start):
        t = self.tree
        end = min(len(self.view_rows), start + 2000)
        for k in range(start, end):
            i, r = self.view_rows[k]
            t.insert("", "end", iid=str(i), values=[i + 1] + [c[:300] for c in r], tags=("odd",) if k % 2 else ())
        if end < len(self.view_rows):
            self._job = self.app.root.after(5, lambda: self._insert(end))
        else:
            self._job = None

    def sort_by(self, k):
        if self.sort_col == k:
            self.sort_rev = not self.sort_rev
        else:
            self.sort_col, self.sort_rev = k, False
        for i, name in enumerate(self.header):
            arrow = (" ▼" if self.sort_rev else " ▲") if i == k else ""
            self.tree.heading(f"c{i}", text=f"{name}{arrow}")
        self._apply_filter()

    # ── actions ──
    def selected_rows(self):
        sel = self.tree.selection()
        if sel:
            return [self.rows[int(i)] for i in sel]
        return [r for _i, r in self.view_rows]

    def copy_rows(self):
        rows = self.selected_rows()
        buf = io.StringIO()
        w = csv.writer(buf, delimiter="\t", lineterminator="\n")
        w.writerow(self.header)
        w.writerows(rows)
        self.app.set_clipboard(buf.getvalue())
        self.toast(T("Copied {0:,} row{1}", len(rows), 's' if len(rows) != 1 else ''))

    def copy_all(self):
        self.tree.selection_remove(self.tree.selection())
        self.copy_rows()

    def edit_action(self, action):
        if action == "copy":
            self.copy_rows()
            return True
        if action == "selectall":
            self.tree.selection_set(self.tree.get_children())
            return True
        return False

    def export_csv(self):
        name = os.path.splitext(self.title)[0] + (f" - {self.sheet}" if len(self.sheets) > 1 else "") + ".csv"
        path = filedialog.asksaveasfilename(parent=self.app.root, title=T("Export CSV"), initialfile=name,
                                            defaultextension=".csv", filetypes=[("CSV", "*.csv")])
        if not path:
            return
        with open(path, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(self.header)
            w.writerows(r for _i, r in self.view_rows)
        self.toast(T("Saved {0}", os.path.basename(path)))

    # ── find ──
    def find_update(self, needle, case, mode="jump"):
        self.matches, self.match_i = [], -1
        if needle:
            n = needle if case else needle.lower()
            for k, (_i, r) in enumerate(self.view_rows):
                if any(n in (c if case else c.lower()) for c in r):
                    self.matches.append(k)
        if self.matches and mode == "jump":
            self._goto(0)
        return self.match_i, len(self.matches)

    def find_step(self, d):
        if not self.matches:
            return -1, 0
        self._goto((self.match_i + d) % len(self.matches))
        return self.match_i, len(self.matches)

    def _goto(self, k):
        self.match_i = k
        iid = str(self.view_rows[self.matches[k]][0])
        if self.tree.exists(iid):
            self.tree.selection_set(iid)
            self.tree.see(iid)

    def find_clear(self, commit=False):
        self.matches, self.match_i = [], -1

    def focus(self):
        self.tree.focus_set()

    def status(self):
        sel = len(self.tree.selection())
        segs = [T("{0:,} selected", sel)] if sel else []
        segs += [T("{0:,} rows", self.total), T("{0} columns", len(self.header))]
        if self.sheet and len(self.sheets) > 1:
            segs.append(self.sheet)
        return segs + [self.type_label()]

    def destroy(self):
        if self._job:
            try:
                self.app.root.after_cancel(self._job)
            except tk.TclError:
                pass
        super().destroy()
