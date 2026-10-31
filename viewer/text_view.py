"""Text / code editor tab with syntax highlighting for many languages."""

import bisect
import os
import re
import time
import tkinter as tk
from tkinter import ttk

from . import formats, theme
from .base import BaseTab
from .theme import C, px
from .i18n import T

HIGHLIGHT_LIMIT = 2_000_000
HIGHLIGHT_SYNC = 60_000          # smaller files are coloured at once; bigger ones in the background
SLICE = 1500                     # ranges per tag_add call
MAX_EDITABLE = 40_000_000
SHIFT, CONTROL = 0x0001, 0x0004

# ─────────────────────────────── languages ───────────────────────────────
NUMBER = (r"(?P<number>\b0[xX][0-9a-fA-F_]+\b|\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b"
          r"|(?<![\w.])\.\d+(?:[eE][+-]?\d+)?)")
GROUP_TAGS = {
    "comment": "syn_comment", "string": "syn_string", "number": "syn_number", "keyword": "syn_keyword",
    "const": "syn_const", "builtin": "syn_builtin", "func": "syn_func", "key": "syn_func",
    "tag": "syn_tag", "attr": "syn_func", "var": "syn_const", "preproc": "syn_builtin",
    "heading": "syn_keyword", "section": "syn_keyword", "decorator": "syn_builtin", "entity": "syn_const",
    "code": "syn_string", "link": "syn_builtin", "error": "syn_tag", "warn": "syn_const",
    "ok": "syn_builtin", "time": "syn_comment", "op": "syn_keyword",
}
SYNTAX_TAGS = tuple(dict.fromkeys(GROUP_TAGS.values()))


def _words(words, ci=False):
    body = "|".join(sorted(set(words.split()), key=len, reverse=True))
    return (r"(?i:\b(?:%s)\b)" if ci else r"\b(?:%s)\b") % body


def _string_patterns(quotes):
    out = []
    for q in quotes:
        if q == "`":
            out.append(r"`(?:\\.|[^`\\])*`?")
        else:
            out.append(q + r"(?:\\.|[^" + q + r"\\\n])*" + q + "?")
    return out


def make_lang(keywords="", consts="", builtins="", line=(), block=None, quotes="\"'", triple=False,
              ci=False, pre=(), func=True):
    parts = []
    comments = [re.escape(block[0]) + r".*?(?:" + re.escape(block[1]) + r"|\Z)"] if block else []
    comments += [re.escape(tok) + r"[^\n]*" for tok in line]
    if comments:
        parts.append("(?P<comment>" + "|".join(comments) + ")")
    parts += [f"(?P<{name}>{pattern})" for name, pattern in pre]
    strings = [r'"""[\s\S]*?(?:"""|\Z)', r"'''[\s\S]*?(?:'''|\Z)"] if triple else []
    strings += _string_patterns(quotes)
    if strings:
        parts.append("(?P<string>" + "|".join(strings) + ")")
    parts.append(NUMBER)
    if keywords:
        parts.append("(?P<keyword>" + _words(keywords, ci) + ")")
    if consts:
        parts.append("(?P<const>" + _words(consts, ci) + ")")
    if builtins:
        parts.append("(?P<builtin>" + _words(builtins, ci) + ")")
    if func:
        parts.append(r"(?P<func>[A-Za-z_][\w]*(?=\s*\())")
    parts.append(r"(?P<ident>[A-Za-z_]\w*)")
    return re.compile("|".join(parts), re.DOTALL | re.MULTILINE)


LUA_RE = re.compile(
    r"(?P<comment>--\[(?P<ceq>=*)\[.*?\](?P=ceq)\]|--[^\n]*)"
    r"|(?P<string>\[(?P<seq>=*)\[.*?\](?P=seq)\]|\"(?:\\.|[^\"\\\n])*\"?|'(?:\\.|[^'\\\n])*'?)"
    r"|" + NUMBER +
    r"|(?P<keyword>" + _words("and break do else elseif end for function goto if in local not or "
                              "repeat return then until while") + r")"
    r"|(?P<const>" + _words("true false nil self") + r")"
    r"|(?P<builtin>" + _words("assert collectgarbage dofile error getmetatable ipairs load loadfile "
                              "loadstring next pairs pcall print rawequal rawget rawlen rawset require "
                              "select setmetatable tonumber tostring type unpack xpcall coroutine debug io "
                              "math os package string table utf8 _G _ENV _VERSION") + r")"
    r"|(?P<func>[A-Za-z_]\w*(?=\s*[(\"'{]))|(?P<ident>[A-Za-z_]\w*)", re.DOTALL)

C_KEYWORDS = ("auto break case catch class const constexpr continue default delete do else enum explicit "
              "export extends extern final finally for foreach friend func fn go goto if impl implements "
              "import in inline interface internal let long loop match mod module move mut namespace new "
              "operator override package private protected pub public readonly ref register return sealed "
              "short signed sizeof static struct super switch template this throw throws trait try type "
              "typedef typename union unsafe unsigned using var virtual void volatile where while yield "
              "async await defer select chan map range fallthrough lock object out params base event "
              "delegate is as when val fun data companion init")
LANGS = {
    "lua": ("Lua", LUA_RE, r"(?:\b(?:then|do|else|repeat)|\bfunction\b[^)]*\)|[{(\[])\s*$", "--"),
    "python": ("Python", make_lang(
        "and as assert async await break class continue def del elif else except finally for from global "
        "if import in is lambda nonlocal not or pass raise return try while with yield match case",
        "True False None self cls", "print len range str int float list dict set tuple open isinstance "
        "super enumerate zip map filter sorted min max sum abs any all type object Exception bool bytes",
        line=("#",), triple=True, pre=(("decorator", r"^[ \t]*@[\w.]+"),)), r":\s*$", "#"),
    "js": ("JavaScript / TypeScript", make_lang(
        "break case catch class const continue debugger default delete do else export extends finally for "
        "function if import in instanceof let new return super switch this throw try typeof var void while "
        "with yield async await of static get set interface type enum implements private public protected "
        "readonly declare namespace abstract as from", "true false null undefined NaN Infinity",
        "console window document Math JSON Object Array String Number Promise Date RegExp Map Set Error",
        line=("//",), block=("/*", "*/"), quotes="\"'`"), r"[{(\[]\s*$", "//"),
    "json": ("JSON", make_lang("", "true false null", line=("//",), block=("/*", "*/"), quotes="",
                               pre=(("key", r'"(?:\\.|[^"\\\n])*"(?=\s*:)'),
                                    ("string", r'"(?:\\.|[^"\\\n])*"?')), func=False),
             r"[{\[]\s*$", None),
    "xml": ("XML / HTML", re.compile(
        r"(?P<comment><!--.*?(?:-->|\Z))|(?P<string><!\[CDATA\[.*?(?:\]\]>|\Z)|\"[^\"]*\"|'[^'\n]*')"
        r"|(?P<tag></?[\w:.-]+|/?>|<\?[\w:.-]+|\?>|<![A-Za-z]+)|(?P<attr>[\w:.-]+(?=\s*=))"
        r"|(?P<entity>&#?\w+;)", re.DOTALL), r"<[A-Za-z][^<>]*(?<!/)>\s*$", None),
    "css": ("CSS", make_lang("", "", "", block=("/*", "*/"), quotes="\"'",
                             pre=(("keyword", r"@[\w-]+"), ("const", r"#[0-9a-fA-F]{3,8}\b"),
                                  ("key", r"[\w-]+(?=\s*:[^:])")), func=True), r"[{(]\s*$", None),
    "markdown": ("Markdown", re.compile(
        r"(?P<code>```.*?(?:```|\Z)|`[^`\n]+`)|(?P<heading>^[ \t]{0,3}#{1,6}[^\n]*)"
        r"|(?P<comment>^[ \t]*>[^\n]*)|(?P<const>\*\*[^*\n]+\*\*|__[^_\n]+__)"
        r"|(?P<link>!?\[[^\]\n]*\]\([^)\n]*\))", re.DOTALL | re.MULTILINE), None, None),
    "ini": ("INI / TOML / Config", re.compile(
        r"(?P<comment>^[ \t]*[;#][^\n]*)|(?P<section>^[ \t]*\[[^\]\n]*\])"
        r"|(?P<key>^[ \t]*[^=:\n;#\[\s][^=\n]*?(?=[ \t]*[=:]))|(?P<string>\"[^\"\n]*\"|'[^'\n]*')|" + NUMBER +
        r"|(?P<const>(?i:\b(?:true|false|yes|no|on|off|null|none)\b))", re.MULTILINE), None, "#"),
    "yaml": ("YAML", re.compile(
        r"(?P<comment>(?:^|(?<=\s))#[^\n]*)|(?P<key>^[ \t-]*[^\s#:\-][^:\n]*?(?=:(?:\s|$)))"
        r"|(?P<string>\"(?:\\.|[^\"\\\n])*\"?|'[^'\n]*'?)|" + NUMBER +
        r"|(?P<const>\b(?:true|false|null|yes|no|on|off)\b|~)|(?P<tag>^---|^\.\.\.|[&*][\w-]+|!!?\w+)",
        re.MULTILINE), r":\s*$", "#"),
    "sql": ("SQL", make_lang(
        "select from where insert into values update set delete create table alter drop index view join "
        "left right inner outer full cross on group by order having limit offset as and or not is in exists "
        "between like union all distinct case when then else end primary key foreign references default "
        "constraint unique begin commit rollback transaction declare exec execute procedure function "
        "returns return if while top with over partition asc desc database schema trigger grant revoke "
        "truncate merge using cascade check nocount go", "null true false",
        "count sum avg min max coalesce cast convert isnull nullif getdate now substring len length upper "
        "lower trim round abs date year month day row_number rank",
        line=("--",), block=("/*", "*/"), quotes="'\"", ci=True), r"\(\s*$", "--"),
    "powershell": ("PowerShell", make_lang(
        "begin break catch class continue data do dynamicparam else elseif end exit filter finally for "
        "foreach from function if in param process return switch throw trap try until using while "
        "workflow enum", "",
        line=("#",), block=("<#", "#>"), quotes="\"'", ci=True, pre=(
            ("code", r"@\"[\s\S]*?\"@|@'[\s\S]*?'@"),
            ("var", r"\$(?:\{[^}\n]*\}|[\w:]+)"),
            ("op", r"(?i:-(?:eq|ne|gt|ge|lt|le|like|notlike|match|notmatch|contains|notcontains|in|"
                        r"notin|and|or|not|xor|replace|split|join|is|isnot|as|band|bor|f)\b)"),
            ("builtin", r"\b[A-Z][a-zA-Z]+-[A-Z][\w]+"), ("attr", r"(?<![\w$])-[A-Za-z]\w*"),
            ("tag", r"\[[\w.]+(?:\[\])?\]"))),
        r"[{(]\s*$", "#"),
    "batch": ("Batch", re.compile(
        r"(?P<comment>^[ \t]*@?(?i:rem\b|::)[^\n]*)|(?P<func>^[ \t]*:\w+)"
        r"|(?P<var>%~?[\w]+%?|![\w]+!)|(?P<string>\"[^\"\n]*\"?)|" + NUMBER +
        r"|(?P<keyword>" + _words("echo set if else goto call exit for in do not exist defined errorlevel "
                                  "setlocal endlocal enabledelayedexpansion pause shift start cd chdir copy "
                                  "xcopy robocopy del erase move mkdir md rmdir rd title cls equ neq lss leq "
                                  "gtr geq nul off on", True) + r")", re.MULTILINE), r"\(\s*$", "::"),
    "shell": ("Shell", make_lang(
        "if then else elif fi case esac for while until do done in function return local export readonly "
        "declare select break continue shift trap source alias unset", "true false",
        "echo printf read cd ls cp mv rm mkdir grep sed awk cat chmod chown sudo test exit",
        line=("#",), quotes="\"'`", pre=(("var", r"\$\{[^}\n]*\}|\$[\w@#?$!*-]"),)), r"(?:\bthen|\bdo|\{)\s*$", "#"),
    "clike": ("C / C# / Java / Go / Rust", make_lang(
        C_KEYWORDS, "true false null nullptr nil None NULL self Self",
        "int char float double bool boolean string String var byte uint size_t i32 i64 u8 u32 u64 f32 f64 "
        "usize isize str Vec Option Result Some Ok Err println printf std",
        line=("//",), block=("/*", "*/"), quotes="\"'`",
        pre=(("preproc", r"^[ \t]*#[ \t]*\w+"), ("decorator", r"^[ \t]*@\w+"))), r"[{(\[]\s*$", "//"),
    "script": ("Ruby / Perl / R / Tcl", make_lang(
        "if else elsif elif unless while until for foreach do end def sub function return in next last "
        "break module class require use my our local library proc", "true false nil TRUE FALSE NULL NA undef",
        line=("#",)), r"(?:\bdo|[{(\[])\s*$", "#"),
    "log": ("Log", re.compile(
        r"(?P<time>\b\d{4}[-/.]\d{2}[-/.]\d{2}[ T]\d{1,2}:\d{2}(?::\d{2}(?:[.,]\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?"
        r"|\b\d{1,2}:\d{2}:\d{2}(?:[.,]\d+)?)"
        r"|(?P<error>(?i:\b(?:error|fatal|critical|crit|exception|fail(?:ed|ure)?|panic|denied)\b))"
        r"|(?P<warn>(?i:\b(?:warn(?:ing)?|deprecated|timeout)\b))"
        r"|(?P<ok>(?i:\b(?:info|debug|trace|notice|ok|success(?:ful)?|done|started)\b))"
        r"|(?P<string>\"[^\"\n]*\"|'[^'\n]*')|" + NUMBER), None, None),
    "step": ("STEP / IFC / WKT", re.compile(
        r"(?P<comment>/\*.*?(?:\*/|\Z))|(?P<string>'[^']*'|\"[^\"\n]*\")|(?P<var>#\d+)|" + NUMBER +
        r"|(?P<keyword>\b[A-Z][A-Z0-9_]{2,}\b)", re.DOTALL), None, None),
    "plain": ("Plain Text", None, None, None),
}
EXT_LANG = {}
for _lang, _exts in {
    "lua": "lua luau rockspec wlua p8", "python": "py pyw pyi", "js": "js mjs cjs jsx ts tsx",
    "json": "json jsonc json5 geojson topojson ipynb webmanifest geojsonl",
    "xml": "xml xsd xsl xslt xaml resx csproj vbproj vcxproj props targets nuspec config manifest plist qgs "
           "qml sld gml x3d dae wsdl rss atom html htm xhtml svg kml gpx vue svelte",
    "css": "css scss sass less", "markdown": "md markdown mdx", "yaml": "yaml yml",
    "ini": "ini cfg conf toml reg inf editorconfig gitattributes properties env npmrc gitignore dockerignore",
    "sql": "sql psql", "powershell": "ps1 psm1 psd1", "batch": "bat cmd", "shell": "sh bash zsh fish",
    "clike": "c h cpp hpp cc cxx hh cs java kt kts go rs php swift scala dart m mm groovy gradle sol zig "
             "fs vb proto graphql gql tf hcl",
    "script": "rb pl pm r tcl jl ex exs nim mtl obj makefile dockerfile cmake", "log": "log out",
    "step": "ifc step stp iges igs prj wkt",
}.items():
    for _e in _exts.split():
        EXT_LANG["." + _e] = _lang


def language_for(path):
    name = os.path.basename(path or "").lower()
    if name in ("makefile", "dockerfile", "cmakelists.txt"):
        return "script"
    if not path:
        return "lua"
    return EXT_LANG.get(formats.ext_of(path), "plain")


def _tokenise(regex, content):
    """[(tag, [start, end, start, end, ...])] Tk indices for every syntax token (safe in a worker thread)."""
    mapper = OffsetMapper(content)
    buckets = {tag: [] for tag in SYNTAX_TAGS}
    for m in regex.finditer(content):
        tag = GROUP_TAGS.get(m.lastgroup)
        if tag and m.end() > m.start():
            bucket = buckets[tag]
            bucket.append(mapper.index(m.start()))
            bucket.append(mapper.index(m.end()))
    return [(tag, idx) for tag, idx in buckets.items() if idx]


class OffsetMapper:
    """Fast string offset -> Tk text index conversion."""
    _NL = re.compile("\n")
    _ASTRAL = re.compile("[\U00010000-\U0010FFFF]")
    _TK_SURROGATES = tk.TkVersion < 9.0

    def __init__(self, content):
        self.content = content
        self.starts = [0]
        self.starts.extend(m.end() for m in self._NL.finditer(content))
        self.astral = self._TK_SURROGATES and self._ASTRAL.search(content) is not None

    def pos(self, offset):
        line = bisect.bisect_right(self.starts, offset) - 1
        start = self.starts[line]
        col = offset - start
        if self.astral and col:
            col += len(self._ASTRAL.findall(self.content, start, offset))
        return line + 1, col

    def index(self, offset):
        line, col = self.pos(offset)
        return f"{line}.{col}"


def detect_indent(content):
    tabs = two = four = 0
    for line in content.split("\n", 3000)[:3000]:
        if line.startswith("\t"):
            tabs += 1
        elif line.startswith("  "):
            n = len(line) - len(line.lstrip(" "))
            if n % 4:
                two += 1
            else:
                four += 1
    if tabs > two + four:
        return "\t"
    if two and two * 3 >= four:
        return "  "
    return "    "


_PROXY_TCL = r"""
rename %(w)s %(w)s_orig
proc %(w)s {args} {
    set result [%(w)s_orig {*}$args]
    set cmd [lindex $args 0]
    set content [expr {$cmd in {insert delete replace} || ($cmd eq "edit" && [lindex $args 1] in {undo redo})}]
    if {$content} {
        event generate %(w)s <<ContentChanged>> -when tail
    }
    if {$content || $cmd eq "see" || ($cmd in {xview yview} && [llength $args] > 1) ||
        ($cmd eq "mark" && [lindex $args 1] eq "set" && [lindex $args 2] eq "insert")} {
        event generate %(w)s <<ViewChanged>> -when tail
    }
    return $result
}
"""


# ─────────────────────────────── the tab ───────────────────────────────
class TextTab(BaseTab):
    kind = "text"
    savable = searchable = zoomable = True

    def __init__(self, app, path=None, title=None, content=None):
        super().__init__(app, path, title)
        self.encoding = "utf-8"
        self.eol = "\r\n" if theme.IS_WIN else "\n"
        self.indent = "    "
        self.lang = language_for(path or title or "x.lua") if (path or title) else "lua"
        self.truncated = False
        self.wrap = app.settings.get("wrap", False)
        self.needs_highlight = True
        self._hl_job = self._ui_job = None
        self._gutter_width = 0
        self.spacing = px(2)
        self.matches, self.keys, self.current = [], [], -1
        self._initial_content = content
        self._build()

    def _build(self):
        bar = self.bar
        bar.button(T("Copy All"), "copy", self.copy_all, T("Copy the whole file  (Ctrl+Shift+C)"))
        bar.button(T("Select All"), "selectall", self.select_all, T("Select all  (Ctrl+A)"))
        bar.divider()
        self.wrap_btn = bar.button(T("Wrap"), "wrap", self.toggle_wrap, T("Word wrap  (Alt+Z)"))
        self.lang_btn = bar.button(T(LANGS[self.lang][0]), "code", tooltip=T("Syntax highlighting: which language the code is coloured as"),
                                   menu=self._lang_menu)
        self.run_btn = None
        if self._is_svg():
            self._add_run_button()
        self.zoom_lbl = bar.label("", side="right")
        bar.button("", "zoomin", lambda: self.app.zoom_code(1), T("Zoom in  (Ctrl +)"), side="right", compact=True)
        bar.button("", "zoomout", lambda: self.app.zoom_code(-1), T("Zoom out  (Ctrl \u2212)"), side="right",
                   compact=True)
        self.zoom_lbl.pack_forget()
        self.zoom_lbl.pack(side="left", padx=px(6))
        self.zoom_lbl.bind("<Button-1>", lambda e: self.app.zoom_code(0))

        f = self.body
        self.banner = tk.Label(f, bg=C["panel"], fg=C["warning"], font=theme.FONTS["small"], anchor="w",
                               padx=px(12), pady=px(5))
        self.gutter = tk.Canvas(f, bg=C["bg"], highlightthickness=0, bd=0, width=px(56))
        self.text = tk.Text(
            f, wrap="word" if self.wrap else "none", undo=True, autoseparators=True, maxundo=-1,
            font=theme.CODE_FONT, bg=C["bg"], fg=C["fg"], insertbackground=C["caret"], insertwidth=px(2),
            selectbackground=C["selection"], inactiveselectbackground=C["selection_inactive"], relief="flat",
            bd=0, highlightthickness=0, padx=px(10), pady=px(6), spacing1=self.spacing, spacing3=self.spacing,
            exportselection=False)
        self.vsb = ttk.Scrollbar(f, orient="vertical", command=self.text.yview)
        self.hsb = ttk.Scrollbar(f, orient="horizontal", command=self.text.xview)
        self.text.configure(yscrollcommand=self._on_yscroll, xscrollcommand=self._on_xscroll)
        f.grid_rowconfigure(1, weight=1)
        f.grid_columnconfigure(1, weight=1)
        self.gutter.grid(row=1, column=0, sticky="ns")
        self.text.grid(row=1, column=1, sticky="nsew")
        self.vsb.grid(row=1, column=2, sticky="ns")
        self.hsb.grid(row=2, column=0, columnspan=2, sticky="ew")
        self.hsb.grid_remove()
        self.wrap_btn.set_toggled(self.wrap)

        t = self.text
        t.tag_configure("curline", background=C["curline"])
        for tag in SYNTAX_TAGS:
            t.tag_configure(tag, foreground=C[tag])
        t.tag_configure("syn_comment", font=theme.CODE_FONT_ITALIC)
        t.tag_configure("find", background=C["find"])
        t.tag_configure("find_cur", background=C["find_cur_bg"], foreground=C["find_cur_fg"])
        t.tag_raise("sel")
        self._keep_colors_in_selection()
        t.tk.eval(_PROXY_TCL % {"w": str(t)})
        self._bind()
        self.update_tabstops()
        self.app.register_drop(t)

    # ── SVG: Run shows the drawing and plays its animation ──
    def _is_svg(self, text=None):
        from .svg_view import is_svg
        return is_svg(self.path or self.title, text)

    def _add_run_button(self):
        if self.run_btn is None:
            self.bar.divider()
            self.run_btn = self.bar.button(T("Run SVG"), "play", self.run_svg,
                                           T("Show the drawing and play its animation  (F5)"), variant="primary")

    def run_svg(self):
        """Open (or refresh) the preview tab with the code as it is now - saved or not."""
        if not self._is_svg(self.get_content()):
            self.toast(T("This is not SVG code."), "info", 2500)
            return
        content = self.get_content()
        preview = next((t for t in self.app.tabs if t.kind == "svg" and getattr(t, "source", None) is self), None)
        if preview is not None:
            preview.set_svg(content)
            self.app.select_tab(preview)
            return
        name = os.path.basename(self.path) if self.path else self.title
        index = self.app.tabs.index(self) + 1 if self in self.app.tabs else None
        tab = self.app.create_tab(None, "svg", title=f"{name} \u25b6", index=index, content=content, source=self)
        if tab:
            self.app.refresh_sidebar()
            self.app.select_tab(tab)

    def _keep_colors_in_selection(self):
        try:
            self.text.tag_configure("sel", foreground="")
        except tk.TclError:
            pass

    def _bind(self):
        t = self.text
        t.bind(f"<{theme.PRIMARY}-MouseWheel>", lambda e: (self.app.zoom_code(1 if e.delta > 0 else -1), "break")[1])
        t.bind("<Tab>", self._on_tab)
        t.bind("<Shift-Tab>", self._on_shift_tab)
        try:
            t.bind("<ISO_Left_Tab>", self._on_shift_tab)
        except tk.TclError:
            pass
        t.bind("<Return>", self._on_return)
        t.bind("<KP_Enter>", self._on_return)
        t.bind("<Alt-z>", lambda e: (self.toggle_wrap(), "break")[1])
        t.bind("<F5>", lambda e: (self.run_svg(), "break")[1] if self.run_btn is not None else None)
        t.bind("<Escape>", lambda e: self.app.find.hide())
        theme.bind_right(t, self._on_context)
        for seq in ("<<ViewChanged>>", "<<Selection>>", "<Configure>"):
            t.bind(seq, self.schedule_ui)
        t.bind("<<ContentChanged>>", self.schedule_highlight)
        t.bind("<<Modified>>", lambda e: self.set_dirty(t.edit_modified()) if self.alive else None)
        self.gutter.bind("<MouseWheel>", self._on_gutter_wheel)
        self.gutter.bind("<Button-1>", self._on_gutter_click)

    def _lang_menu(self, menu):
        menu.var = tk.StringVar(master=menu, value=self.lang)
        menu.add_command(label=T("Colour the code as:"), state="disabled")
        menu.add_separator()
        for key, (name, _rx, _ind, _cmt) in LANGS.items():
            menu.add_radiobutton(label=T(name), value=key, variable=menu.var,
                                 command=lambda k=key: self.set_language(k))

    def set_language(self, key):
        self.lang = key
        self.lang_btn.set_text(T(LANGS[key][0]))
        self.needs_highlight = True
        self.schedule_highlight(delay=1)
        self.app.update_status()

    def update_tabstops(self):
        self.text.configure(tabs=(theme.CODE_FONT.measure(" " * 4),), tabstyle="wordprocessor")
        self._keep_colors_in_selection()
        self._gutter_width = 0
        self.zoom_lbl.configure(text=f"{round(theme.CODE_FONT.cget('size') / theme.CODE_SIZE * 100)}%")
        self.schedule_ui()

    # ── content ──
    def load(self):
        if self._initial_content is not None:
            self.set_content(self._initial_content)
            self.text.edit_modified(False)
            return
        if self.path is None:
            return
        size = os.path.getsize(self.path)
        limit = MAX_EDITABLE if size > MAX_EDITABLE else None
        content, self.encoding, self.eol = formats.read_text_file(self.path, limit)
        self.truncated = limit is not None
        self.indent = detect_indent(content)
        self.set_content(content)
        if self.run_btn is None and self._is_svg(content):      # SVG saved under another name (.xml, .html...)
            self._add_run_button()
        if self.truncated:
            self.banner.configure(text=T("Large file — showing the first {0} of {1}. Saving is disabled.", formats.human_size(MAX_EDITABLE), formats.human_size(size)))
            self.banner.grid(row=0, column=0, columnspan=3, sticky="ew")
            self.savable = False

    def set_content(self, content):
        t = self.text
        t.delete("1.0", "end")
        t.insert("1.0", content)
        t.edit_reset()
        t.edit_modified(False)
        t.mark_set("insert", "1.0")
        t.see("1.0")
        self.needs_highlight = True

    def get_content(self):
        return self.text.get("1.0", "end-1c")

    def line_count(self):
        return int(self.text.index("end-1c").split(".")[0])

    def save_filetypes(self):
        ext = formats.ext_of(self.path or self.title) or ".lua"
        return [(formats.label_for("x" + ext) or T("Text"), "*" + ext), (T("Lua files"), "*.lua"),
                (T("Text files"), "*.txt"), (T("All files"), "*")]

    def default_extension(self):
        return formats.ext_of(self.path or self.title) or ".lua"

    def save_to(self, path):
        content = self.get_content()
        if self.eol == "\r\n":
            content = content.replace("\n", "\r\n")
        encoding, warning = self.encoding, None
        try:
            data = content.encode(encoding)
        except UnicodeEncodeError:
            encoding = "utf-8"
            data = content.encode(encoding)
            warning = T("Saved as UTF-8 \u2014 the original encoding couldn't store every character.")
        with open(path, "wb") as fh:
            fh.write(data)
        self.encoding = encoding
        self.text.edit_modified(False)
        if language_for(path) != self.lang and self.lang in ("lua", "plain"):
            self.set_language(language_for(path))
        return warning

    def pdf_bytes(self):
        """The text as a PDF (monospace, wrapped) for Convert → Export as PDF."""
        import html
        from .convert import story_to_pdf
        body = html.escape(self.get_content().replace("\t", "    "))
        css = "pre { font-family: monospace; font-size: 8.5pt; line-height: 1.35; white-space: pre-wrap; }"
        return story_to_pdf(f"<pre>{body}</pre>", css, margins=(42, 40, 42, 40))

    def selected_text(self):
        try:
            return self.text.get("sel.first", "sel.last")
        except tk.TclError:
            return ""

    def selection_length(self):
        ranges = self.text.tag_ranges("sel")
        if not ranges:
            return 0
        try:
            return int(self.text.tk.call(str(self.text), "count", "-chars", str(ranges[0]), str(ranges[-1])))
        except (tk.TclError, ValueError):
            return 0

    # ── actions ──
    def copy_all(self):
        content = self.get_content()
        if not content.strip():
            self.toast(T("Nothing to copy \u2014 the file is empty."), "warning")
            return
        self.app.set_clipboard(content)
        n = content.count("\n") + 1
        self.toast(T("Copied {0} — {1:,} line{2}", self.title, n, 's' if n != 1 else ''))

    def select_all(self):
        self.text.focus_set()
        self.text.tag_add("sel", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")

    def menu_title(self):
        return T("Text")

    def fill_menu(self, name, m):
        if name == "view":
            m.add_checkbutton(label=T("Word wrap"), command=self.toggle_wrap,
                              variable=theme.menu_var(m, "bool", self.wrap))
            m.add_command(label=T("Larger text"), accelerator=theme.keys("Ctrl++"),
                          command=lambda: self.app.zoom_code(1))
            m.add_command(label=T("Smaller text"), accelerator=theme.keys("Ctrl+-"),
                          command=lambda: self.app.zoom_code(-1))
            m.add_command(label=T("Default size"), accelerator=theme.keys("Ctrl+0"),
                          command=lambda: self.app.zoom_code(0))
        elif name == "tools":
            if self.run_btn is not None:
                m.add_command(label=T("Run SVG"), accelerator="F5", command=self.run_svg)
                m.add_separator()
            sub = theme.popup_menu(m)
            self._lang_menu(sub)
            m.add_cascade(label=T("Syntax colouring"), menu=sub)
            m.add_command(label=T("Copy all"), accelerator=theme.keys("Ctrl+Shift+C"), command=self.copy_all)

    def toggle_wrap(self):
        self.wrap = not self.wrap
        self.app.settings["wrap"] = self.wrap
        self.text.configure(wrap="word" if self.wrap else "none")
        self.wrap_btn.set_toggled(self.wrap)
        self.schedule_ui()

    def focus(self):
        self.text.focus_set()

    def on_show(self):
        if self.needs_highlight:
            self.schedule_highlight(delay=1)
        self.update_tabstops()

    def status(self):
        line, col = self.text.index("insert").split(".")
        pos = T("Ln {0}, Col {1}", line, int(col) + 1)
        n = self.selection_length()
        if n:
            pos += "  (" + T("{0:,} selected", n) + ")"
        return [pos, T("{0:,} lines", self.line_count()),
                formats.ENCODING_LABELS.get(self.encoding, self.encoding.upper()),
                "CRLF" if self.eol == "\r\n" else "LF", T(LANGS[self.lang][0])]

    # ── highlighting ──
    def schedule_highlight(self, _event=None, delay=None):
        if not self.alive:
            return
        if self.app.active is not self:
            self.needs_highlight = True
            return
        if self._hl_job:
            self.app.root.after_cancel(self._hl_job)
        if delay is None:
            delay = 120 + min(700, self.line_count() // 60)
        self._hl_job = self.app.root.after(delay, self.highlight)

    def highlight(self):
        """Syntax colours. Small files at once; big ones are tokenised in a worker thread and the colours
        are applied in slices - the visible part first - so the window keeps responding."""
        self._hl_job = None
        if not self.alive:
            return
        self._hl_gen = getattr(self, "_hl_gen", 0) + 1
        gen = self._hl_gen
        content = self.get_content()
        self.needs_highlight = False
        regex = LANGS[self.lang][1]
        if regex is None or len(content) > HIGHLIGHT_LIMIT:
            self._clear_syntax()
            self._after_highlight()
            return
        if len(content) <= HIGHLIGHT_SYNC:
            self._clear_syntax()
            for tag, idx in _tokenise(regex, content):
                self.text.tag_add(tag, *idx)
            self._after_highlight()
            return

        def done(ok, ranges):
            if not ok or not self.alive or gen != self._hl_gen:
                return
            self._clear_syntax()
            self._apply_slices(gen, self._visible_first(ranges))
        self.app.run_in_thread(lambda: _tokenise(regex, content), done)

    def _clear_syntax(self):
        for tag in SYNTAX_TAGS:
            self.text.tag_remove(tag, "1.0", "end")

    def _visible_first(self, ranges):
        """[(tag, [start, end, ...])] -> slices of at most SLICE ranges, those on screen first."""
        try:
            top = int(self.text.index("@0,0").split(".")[0]) - 40
            bottom = int(self.text.index(f"@0,{self.text.winfo_height()}").split(".")[0]) + 40
        except (tk.TclError, ValueError):
            top, bottom = 0, 0
        near, far = [], []
        for tag, idx in ranges:
            a, b = [], []
            for k in range(0, len(idx), 2):
                line = int(idx[k].split(".", 1)[0])
                (a if top <= line <= bottom else b).extend(idx[k:k + 2])
            for target, part in ((near, a), (far, b)):
                for i in range(0, len(part), SLICE * 2):
                    target.append((tag, part[i:i + SLICE * 2]))
        return near + far

    def _apply_slices(self, gen, slices, start=0):
        if not self.alive or gen != self._hl_gen:
            return
        t0 = time.perf_counter()
        i = start
        while i < len(slices) and time.perf_counter() - t0 < 0.03:      # ~30 ms of work, then let Tk breathe
            tag, idx = slices[i]
            if idx:
                self.text.tag_add(tag, *idx)
            i += 1
        if i < len(slices):
            self._hl_job = self.app.root.after(1, lambda: self._apply_slices(gen, slices, i))
        else:
            self._after_highlight()

    def _after_highlight(self):
        if self.app.find.visible and self.app.active is self:
            self.app.find.refresh()

    # ── view updates ──
    def schedule_ui(self, _event=None):
        if self._ui_job is None and self.alive:
            self._ui_job = self.app.root.after_idle(self._update_ui)

    def _update_ui(self):
        self._ui_job = None
        if not self.alive:
            return
        t = self.text
        t.tag_remove("curline", "1.0", "end")
        if not t.tag_ranges("sel"):
            t.tag_add("curline", "insert linestart", "insert lineend+1c")
        self._redraw_gutter()
        if self.app.active is self:
            self.app.update_status()

    def _redraw_gutter(self):
        t, g, font = self.text, self.gutter, theme.CODE_FONT
        last = self.line_count()
        width = font.measure("0" * max(3, len(str(last)))) + px(30)
        if width != self._gutter_width:
            self._gutter_width = width
            g.configure(width=width)
        g.delete("all")
        current = int(t.index("insert").split(".")[0])
        x = width - px(12)
        idx = t.index("@0,0")
        while True:
            line = int(idx.split(".")[0])
            if line > last:
                break
            info = t.dlineinfo(idx)
            if info is None:
                break
            g.create_text(x, info[1] + self.spacing, anchor="ne", text=str(line), font=font,
                          fill=C["gutter_active"] if line == current else C["gutter"])
            nxt = t.index(f"{idx}+1line")
            if nxt == idx:
                break
            idx = nxt

    def _on_yscroll(self, first, last):
        self.vsb.set(first, last)
        self.schedule_ui()

    def _on_xscroll(self, first, last):
        self.hsb.set(first, last)
        if float(first) <= 0.0 and float(last) >= 1.0:
            self.hsb.grid_remove()
        else:
            self.hsb.grid()

    def _on_gutter_wheel(self, event):
        step = theme.wheel_units(event, 4)
        self.text.yview_scroll(step, "units")
        return "break"

    def _on_gutter_click(self, event):
        t = self.text
        line = t.index(f"@0,{event.y}").split(".")[0]
        t.tag_remove("sel", "1.0", "end")
        t.tag_add("sel", f"{line}.0", f"{line}.0+1line")
        t.mark_set("insert", f"{line}.0+1line")
        t.focus_set()
        return "break"

    def _on_context(self, event):
        t = self.text
        t.focus_set()
        if not t.tag_ranges("sel"):
            t.mark_set("insert", f"@{event.x},{event.y}")
        m = theme.popup_menu(self.app.root)
        sel = "normal" if t.tag_ranges("sel") else "disabled"
        act = self.app.edit_action
        m.add_command(label=T("Undo"), accelerator="Ctrl+Z", command=lambda: act("undo", t))
        m.add_command(label=T("Redo"), accelerator="Ctrl+Y", command=lambda: act("redo", t))
        m.add_separator()
        m.add_command(label=T("Cut"), accelerator="Ctrl+X", state=sel, command=lambda: act("cut", t))
        m.add_command(label=T("Copy"), accelerator="Ctrl+C", state=sel, command=lambda: act("copy", t))
        m.add_command(label=T("Paste"), accelerator="Ctrl+V", command=lambda: act("paste", t))
        m.add_separator()
        m.add_command(label=T("Select All"), accelerator="Ctrl+A", command=self.select_all)
        m.add_command(label=T("Copy Entire File"), accelerator="Ctrl+Shift+C", command=self.copy_all)
        m.add_separator()
        m.add_command(label=T("Find\u2026"), accelerator="Ctrl+F", command=self.app.find_show)
        theme.show_menu(m, event.x_root, event.y_root)
        return "break"

    # ── smart editing ──
    def _selected_lines(self):
        t = self.text
        try:
            first, last = t.index("sel.first"), t.index("sel.last")
        except tk.TclError:
            return None
        l1, l2 = int(first.split(".")[0]), int(last.split(".")[0])
        if l2 > l1 and last.endswith(".0"):
            l2 -= 1
        return l1, l2

    def _on_tab(self, event):
        if event.state & CONTROL:
            return self.app.on_ctrl_key(event)
        t = self.text
        lines = self._selected_lines()
        if lines and lines[0] != lines[1]:
            l1, l2 = lines
            t.edit_separator()
            for ln in range(l1, l2 + 1):
                if t.get(f"{ln}.0", f"{ln}.end").strip():
                    t.insert(f"{ln}.0", self.indent)
            t.tag_remove("sel", "1.0", "end")
            t.tag_add("sel", f"{l1}.0", f"{l2}.end")
            t.edit_separator()
        else:
            if lines:
                t.delete("sel.first", "sel.last")
            t.insert("insert", self.indent)
            t.see("insert")
        return "break"

    def _on_shift_tab(self, event):
        if event.state & CONTROL:
            return self.app.on_ctrl_key(event)
        t = self.text
        lines = self._selected_lines()
        if lines:
            l1, l2 = lines
        else:
            l1 = l2 = int(t.index("insert").split(".")[0])
        width = 4 if self.indent == "\t" else len(self.indent)
        t.edit_separator()
        for ln in range(l1, l2 + 1):
            line = t.get(f"{ln}.0", f"{ln}.end")
            n = 1 if line.startswith("\t") else min(width, len(line) - len(line.lstrip(" ")))
            if n:
                t.delete(f"{ln}.0", f"{ln}.{n}")
        if lines:
            t.tag_remove("sel", "1.0", "end")
            t.tag_add("sel", f"{l1}.0", f"{l2}.end")
        t.edit_separator()
        return "break"

    def _on_return(self, _event):
        t = self.text
        if t.tag_ranges("sel"):
            t.delete("sel.first", "sel.last")
        line = t.get("insert linestart", "insert")
        indent = re.match(r"[ \t]*", line).group(0)
        _name, _rx, opener, comment = LANGS[self.lang]
        code = line
        if comment and comment in code:
            code = code.split(comment, 1)[0]
        if opener and re.search(opener, code.rstrip()):
            indent += self.indent
        t.insert("insert", "\n" + indent)
        t.see("insert")
        return "break"

    # ── find bar ──
    def find_initial(self):
        s = self.selected_text()
        return s if s and "\n" not in s and len(s) < 300 else ""

    def find_clear(self, commit=False):
        t = self.text
        t.tag_remove("find", "1.0", "end")
        t.tag_remove("find_cur", "1.0", "end")
        if commit and 0 <= self.current < len(self.matches):
            s, e = self.matches[self.current]
            t.tag_remove("sel", "1.0", "end")
            t.tag_add("sel", s, e)
            t.mark_set("insert", e)
        self.matches, self.keys, self.current = [], [], -1

    def find_update(self, needle, case, mode="jump"):
        t = self.text
        keep = self.current
        t.tag_remove("find", "1.0", "end")
        t.tag_remove("find_cur", "1.0", "end")
        self.matches, self.keys = [], []
        if not needle:
            self.current = -1
            return -1, 0
        content = self.get_content()
        mapper = OffsetMapper(content)
        for m in re.finditer(re.escape(needle), content, 0 if case else re.IGNORECASE):
            start, end = mapper.pos(m.start()), mapper.pos(m.end())
            self.keys.append(start)
            self.matches.append((f"{start[0]}.{start[1]}", f"{end[0]}.{end[1]}"))
            if len(self.matches) >= 20000:
                break
        flat = [i for pair in self.matches for i in pair]
        for i in range(0, len(flat), 4000):
            t.tag_add("find", *flat[i:i + 4000])
        if not self.matches:
            self.current = -1
        elif mode == "jump":
            origin = "sel.first" if t.tag_ranges("sel") else "insert"
            cursor = tuple(int(v) for v in t.index(origin).split("."))
            i = bisect.bisect_left(self.keys, cursor)
            self._goto(i if i < len(self.matches) else 0)
        elif mode == "keep" and keep >= 0:
            self.current = min(keep, len(self.matches) - 1)
            t.tag_add("find_cur", *self.matches[self.current])
        else:
            self.current = -1
        return self.current, len(self.matches)

    def find_step(self, direction):
        n = len(self.matches)
        if not n:
            return -1, 0
        cursor = tuple(int(v) for v in self.text.index("insert").split("."))
        if 0 <= self.current < n and self.keys[self.current] == cursor:
            i = (self.current + direction) % n
        elif direction > 0:
            i = bisect.bisect_left(self.keys, cursor)
            i = i if i < n else 0
        else:
            i = bisect.bisect_left(self.keys, cursor) - 1
            i = i if i >= 0 else n - 1
        self._goto(i)
        return self.current, n

    def _goto(self, i):
        t = self.text
        self.current = i
        s, e = self.matches[i]
        t.tag_remove("find_cur", "1.0", "end")
        t.tag_add("find_cur", s, e)
        t.mark_set("insert", s)
        t.see(e)
        t.see(s)

    def destroy(self):
        for job in (self._hl_job, self._ui_job):
            if job:
                try:
                    self.app.root.after_cancel(job)
                except tk.TclError:
                    pass
        name = str(self.text)
        super().destroy()
        try:
            self.app.root.tk.call("rename", name, "")
        except tk.TclError:
            pass
