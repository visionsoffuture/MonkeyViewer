"""Calculator: a small window next to the documents (Window > Calculator, Ctrl+Shift+K).

Exact decimal arithmetic (0.1 + 0.2 = 0.3), a safe parser (no eval), typing and buttons, % like a desk
calculator (200 + 10% = 220), history of results, copy and paste.
"""

import decimal
import re
import tkinter as tk
from decimal import Decimal

from . import theme
from .i18n import T
from .theme import C, FONTS, ToolButton, px

CTX = decimal.Context(prec=34, Emax=999_999, Emin=-999_999, traps=[decimal.DivisionByZero, decimal.Overflow,
                                                                     decimal.InvalidOperation])
NUMBER = re.compile(r"\d+(?:[.,]\d*)?(?:[eE][-+]?\d+)?|[.,]\d+(?:[eE][-+]?\d+)?")
KEYSYMS = {".": "period", ",": "comma", "+": "plus", "-": "minus", "*": "asterisk", "/": "slash",
           "(": "parenleft", ")": "parenright", "%": "percent", "^": "asciicircum"}


class CalcError(ValueError):
    pass


def tokenize(text):
    text = (text or "").replace("−", "-").replace("×", "*").replace("÷", "/").replace(":", "/")
    text = text.replace(" ", "").replace(" ", "").replace(" ", "")
    out, i = [], 0
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        m = NUMBER.match(text, i)
        if m:
            out.append(("num", Decimal(m.group(0).replace(",", "."))))
            i = m.end()
            continue
        if text[i] in "+-*/^()%²√":
            out.append(("op", text[i]))
            i += 1
            continue
        if text.startswith("sqrt", i):
            out.append(("op", "√"))
            i += 4
            continue
        raise CalcError(T("Not a calculation"))
    return out


class _Parser:
    def __init__(self, tokens):
        self.t, self.i = tokens, 0

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, op=None):
        tok = self.peek()
        if op is not None and tok != ("op", op):
            raise CalcError(T("Not a calculation"))
        self.i += 1
        return tok

    def expr(self):
        value, _pct = self.term()
        while self.peek() in (("op", "+"), ("op", "-")):
            op = self.take()[1]
            right, pct = self.term()
            if pct:                                   # 200 + 10% = 220, 200 - 10% = 180
                right = CTX.multiply(value, right)
            value = CTX.add(value, right) if op == "+" else CTX.subtract(value, right)
        return value, False

    def term(self):
        value, pct = self.factor()
        while self.peek() in (("op", "*"), ("op", "/")) or self.peek()[0] == "num" or self.peek() == ("op", "("):
            if self.peek()[0] == "num" or self.peek() == ("op", "("):
                op = "*"                              # 2(3+4) = 14
            else:
                op = self.take()[1]
            right, _p = self.factor()
            if op == "*":
                value = CTX.multiply(value, right)
            else:
                if right == 0:
                    raise CalcError(T("Cannot divide by zero"))
                value = CTX.divide(value, right)
            pct = False
        return value, pct

    def factor(self):
        base, pct = self.unary()
        if self.peek() == ("op", "^"):
            self.take()
            exp, _p = self.factor()
            if abs(exp) > 100_000:
                raise CalcError(T("The number is too large"))
            if base < 0 and exp != exp.to_integral_value():
                raise CalcError(T("Invalid input"))
            if base == 0 and exp < 0:
                raise CalcError(T("Cannot divide by zero"))
            base, pct = CTX.power(base, exp), False
        return base, pct

    def unary(self):
        if self.peek() == ("op", "-"):
            self.take()
            value, pct = self.unary()
            return CTX.minus(value), pct
        if self.peek() == ("op", "+"):
            self.take()
            return self.unary()
        if self.peek() == ("op", "√"):
            self.take()
            value, _p = self.unary()
            if value < 0:
                raise CalcError(T("Invalid input"))
            return CTX.sqrt(value), False
        return self.postfix()

    def postfix(self):
        value, pct = self.primary(), False
        while self.peek() in (("op", "%"), ("op", "²")):
            if self.take()[1] == "%":
                value, pct = CTX.divide(value, Decimal(100)), True
            else:
                value, pct = CTX.multiply(value, value), False
        return value, pct

    def primary(self):
        kind, val = self.peek()
        if kind == "num":
            self.take()
            return val
        if (kind, val) == ("op", "("):
            self.take()
            value, _p = self.expr()
            if self.peek() == ("op", ")"):
                self.take()
            return value                              # a missing ")" at the end is forgiven
        raise CalcError(T("Not a calculation"))


def evaluate(text):
    """Decimal value of a calculation; CalcError with a readable message when it is not one."""
    tokens = tokenize(text)
    if not tokens:
        raise CalcError(T("Not a calculation"))
    p = _Parser(tokens)
    try:
        value, _pct = p.expr()
    except decimal.DivisionByZero as exc:
        raise CalcError(T("Cannot divide by zero")) from exc
    except decimal.Overflow as exc:
        raise CalcError(T("The number is too large")) from exc
    except decimal.InvalidOperation as exc:
        raise CalcError(T("Invalid input")) from exc
    if p.i != len(tokens):
        raise CalcError(T("Not a calculation"))
    return value


def format_number(value, group=True):
    """Up to 16 significant digits, no trailing zeros, thin-space thousands; scientific when very big/small."""
    if value == 0:
        return "0"
    q = CTX.create_decimal(value)
    exp = q.adjusted()
    if exp >= 16 or exp < -9:
        mant = f"{q:.15e}"
        m, e = mant.split("e")
        m = m.rstrip("0").rstrip(".")
        return f"{m}e{int(e):+d}"
    rounded = q.quantize(Decimal(1).scaleb(max(-15, exp - 15)), rounding=decimal.ROUND_HALF_EVEN, context=CTX)
    text = f"{rounded:f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    if not group:
        return text
    sign = "-" if text.startswith("-") else ""
    whole, _dot, frac = text.lstrip("-").partition(".")
    whole = f"{int(whole):,}".replace(",", " ")
    return sign + whole + ("." + frac if frac else "")


# ─────────────────────────────── window ───────────────────────────────
KEYS = [
    [("%", "op"), ("CE", "fn"), ("C", "fn"), ("⌫", "fn")],
    [("1/x", "fn"), ("x²", "fn"), ("√x", "fn"), ("÷", "op")],
    [("7", "num"), ("8", "num"), ("9", "num"), ("×", "op")],
    [("4", "num"), ("5", "num"), ("6", "num"), ("−", "op")],
    [("1", "num"), ("2", "num"), ("3", "num"), ("+", "op")],
    [("±", "fn"), ("0", "num"), (".", "num"), ("=", "eq")],
]


class _Key(tk.Label):
    def __init__(self, master, text, kind, command):
        self.kind = kind
        colors = {"num": (C["input"], C["hover"], C["fg_bright"]), "op": (C["panel_hi"], C["hover_strong"], C["fg"]),
                  "fn": (C["panel_hi"], C["hover_strong"], C["fg_dim"]),
                  "eq": (C["accent"], C["accent_hover"], C["on_accent"])}[kind]
        self.bg, self.hover, fg = colors
        font = FONTS["h3"] if kind in ("num", "eq") else FONTS["ui"]
        super().__init__(master, text=text, bg=self.bg, fg=fg, font=font, cursor="hand2", padx=px(4),
                         pady=px(10))
        self.command = command
        self.bind("<Enter>", lambda e: self.configure(bg=self.hover))
        self.bind("<Leave>", lambda e: self.configure(bg=self.bg))
        self.bind("<ButtonRelease-1>", lambda e: self.command() if theme.pointer_inside(self, e) else None)


class Calculator(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app.root)
        self.withdraw()
        self.app = app
        self.title(T("Calculator"))
        self.configure(bg=C["panel"])
        self.resizable(True, True)
        self.minsize(px(280), px(420))
        self.expr = ""
        self.just_evaluated = False
        self.history = []
        self.on_top = bool(app.settings.get("calc_on_top", False))
        self._build()
        self._bind_keys()
        self._refresh()
        top = app.root
        w, h = px(320), px(500)
        x = top.winfo_rootx() + top.winfo_width() - w - px(40)
        y = top.winfo_rooty() + px(90)
        self.geometry(f"{w}x{h}+{max(0, x)}+{max(0, y)}")
        self.attributes("-topmost", self.on_top)
        self.deiconify()
        from . import winutil
        winutil.apply_dark_titlebar(self, C["panel"], C["border"])
        self.protocol("WM_DELETE_WINDOW", self.close)
        self.focus_set()

    def _build(self):
        head = tk.Frame(self, bg=C["panel"])
        head.pack(fill="x", padx=px(10), pady=(px(8), 0))
        self.pin_btn = ToolButton(head, "", "pin", self.toggle_on_top, T("Keep on top of other windows"),
                                  bg=C["panel"], hover=C["hover_strong"], pad=(8, 4))
        self.pin_btn.pack(side="right")
        self.pin_btn.set_toggled(self.on_top)
        self.hist_btn = ToolButton(head, "", "history", self.toggle_history, T("History"), bg=C["panel"],
                                   hover=C["hover_strong"], pad=(8, 4))
        self.hist_btn.pack(side="right")
        ToolButton(head, "", "copy", self.copy_result, T("Copy the result  (Ctrl+C)"), bg=C["panel"],
                   hover=C["hover_strong"], pad=(8, 4)).pack(side="right")

        disp = tk.Frame(self, bg=C["panel"])
        disp.pack(fill="x", padx=px(16), pady=(px(6), px(10)))
        self.expr_lbl = tk.Label(disp, text="", bg=C["panel"], fg=C["fg_muted"], font=FONTS["ui"], anchor="e")
        self.expr_lbl.pack(fill="x")
        self.main_lbl = tk.Label(disp, text="0", bg=C["panel"], fg=C["fg_bright"],
                                 font=(FONTS["h1"][0], FONTS["h1"][1], "bold"), anchor="e")
        self.main_lbl.pack(fill="x")
        self.main_lbl.bind("<Configure>", lambda e: self._fit_font())
        theme.bind_right(self.main_lbl, self._context_menu)

        self.stack = tk.Frame(self, bg=C["panel"])
        self.stack.pack(fill="both", expand=True, padx=px(6), pady=(0, px(6)))
        self.pad = tk.Frame(self.stack, bg=C["panel"])
        self.pad.pack(fill="both", expand=True)
        for r, row in enumerate(KEYS):
            self.pad.grid_rowconfigure(r, weight=1, uniform="k")
            for c, (text, kind) in enumerate(row):
                key = _Key(self.pad, text, kind, lambda t=text: self.press(t))
                key.grid(row=r, column=c, sticky="nsew", padx=px(2), pady=px(2))
        for c in range(4):
            self.pad.grid_columnconfigure(c, weight=1, uniform="k")
        self.hist = tk.Frame(self.stack, bg=C["panel"])
        self.hist_list = tk.Listbox(self.hist, bg=C["input"], fg=C["fg"], selectbackground=C["selection"],
                                    selectforeground=C["fg_bright"], relief="flat", highlightthickness=0, bd=0,
                                    font=FONTS["ui"], activestyle="none")
        self.hist_list.pack(fill="both", expand=True, padx=px(2), pady=px(2))
        self.hist_list.bind("<Double-Button-1>", self._use_history)
        self.hist_list.bind("<Return>", self._use_history)
        self.hist_empty = tk.Label(self.hist, text=T("No calculations yet"), bg=C["input"], fg=C["fg_muted"],
                                   font=FONTS["small"])

    def _bind_keys(self):
        for ch in "0123456789.,+-*/()%^":
            self.bind(f"<KeyPress-{KEYSYMS.get(ch, ch)}>", lambda e, c=ch: self.press(c))
        for name, ch in (("KP_Add", "+"), ("KP_Subtract", "-"), ("KP_Multiply", "*"), ("KP_Divide", "/"),
                         ("KP_Decimal", "."), ("KP_Separator", ".")):
            self.bind(f"<{name}>", lambda e, c=ch: self.press(c))
        for d in range(10):
            self.bind(f"<KP_{d}>", lambda e, c=str(d): self.press(c))
        self.bind("<Return>", lambda e: self.press("="))
        self.bind("<KP_Enter>", lambda e: self.press("="))
        self.bind("<equal>", lambda e: self.press("="))
        self.bind("<BackSpace>", lambda e: self.press("⌫"))
        self.bind("<Delete>", lambda e: self.press("CE"))
        self.bind("<Escape>", lambda e: self.press("C"))
        self.bind(f"<{theme.PRIMARY}-c>", lambda e: self.copy_result())
        self.bind(f"<{theme.PRIMARY}-v>", lambda e: self.paste())
        self.bind(f"<{theme.PRIMARY}-C>", lambda e: self.copy_result())
        self.bind(f"<{theme.PRIMARY}-V>", lambda e: self.paste())

    # ── input ──
    def press(self, key):
        key = {"×": "*", "÷": "/", "−": "-", ",": "."}.get(key, key)
        if key == "C":
            self.expr, self.just_evaluated = "", False
        elif key == "CE":
            self.expr = re.sub(r"(\d+(?:\.\d*)?|\.\d+)$", "", self.expr)
            self.just_evaluated = False
        elif key == "⌫":
            self.expr = "" if self.just_evaluated else self.expr[:-1]
            self.just_evaluated = False
        elif key == "=":
            self.evaluate()
            return
        elif key == "±":
            self._toggle_sign()
        elif key in ("1/x", "x²", "√x"):
            self._apply(key)
            return
        else:
            if self.just_evaluated and (key.isdigit() or key in ".("):
                self.expr = ""                         # a new number after = starts a new calculation
            self.just_evaluated = False
            if key == "." and re.search(r"\d*\.\d*$", self.expr):
                return                                 # one decimal point per number
            if key in "+-*/^" and self.expr[-1:] in "+-*/^" and not (key == "-" and self.expr[-1:] in "*/^"):
                self.expr = self.expr[:-1]             # replace the operator just typed
            if key in "+*/^%" and not self.expr:
                self.expr = "0"
            self.expr += key
        self._refresh()

    def _toggle_sign(self):
        """± on the number being typed: 5 -> -5, 3+5 -> 3+(-5), and back."""
        m = re.search(r"(\(-)?(\d+(?:\.\d*)?(?:e[-+]?\d+)?|\.\d+)$", self.expr)
        if not m:
            if not self.expr:
                self.expr = "-"
            return
        prefix, num = self.expr[:m.start()], m.group(2)
        if m.group(1):
            self.expr = prefix + num
        elif prefix == "":
            self.expr = "-" + num
        elif prefix == "-":
            self.expr = num
        elif prefix.endswith("("):
            self.expr = prefix + "-" + num
        else:
            self.expr = prefix + "(-" + num
        self.just_evaluated = False

    def _apply(self, fn):
        try:
            value = evaluate(self.expr or "0")
        except CalcError as exc:
            self._show_error(str(exc))
            return
        shown = format_number(value, group=False)
        expr = {"1/x": f"1/({shown})", "x²": f"({shown})²", "√x": f"√({shown})"}[fn]
        self.expr = expr
        self.evaluate()

    def evaluate(self):
        if not self.expr:
            return
        try:
            value = evaluate(self.expr)
        except CalcError as exc:
            self._show_error(str(exc))
            return
        text = format_number(value)
        self.history.insert(0, (self.expr, value))
        del self.history[50:]
        self._fill_history()
        self.expr_lbl.configure(text=self._pretty(self.expr) + " =")
        self.expr = format_number(value, group=False)
        self.just_evaluated = True
        self._set_main(text)

    def paste(self):
        try:
            text = self.clipboard_get()
        except tk.TclError:
            return
        text = text.strip().replace(" ", "").replace(" ", "").replace(" ", "")
        if text and re.fullmatch(r"[\d.,+\-*/×÷()%^²√e]+", text):
            if self.just_evaluated:
                self.expr = ""
            self.expr += text.replace(",", ".")
            self.just_evaluated = False
            self._refresh()

    def copy_result(self):
        try:
            text = format_number(evaluate(self.expr), group=False) if self.expr else "0"
        except CalcError:
            return
        self.app.set_clipboard(text)
        self.app.toast.show(T("Copied {0}", text), "info", 1400)

    # ── display ──
    @staticmethod
    def _pretty(expr):
        return expr.replace("*", " × ").replace("/", " ÷ ").replace("+", " + ").replace("^", " ^ ") \
            .replace("-", " − ").replace("(  − ", "(−").replace("( − ", "(−").strip()

    def _refresh(self):
        if not self.expr:
            self.expr_lbl.configure(text="")
            self._set_main("0")
            return
        self.expr_lbl.configure(text="")
        shown = self._pretty(self.expr)
        try:
            preview = format_number(evaluate(self.expr))
            if preview != shown and not re.fullmatch(r"-?[\d.]+", self.expr):
                self.expr_lbl.configure(text=shown)
                self._set_main(preview, muted=True)
                return
        except CalcError:
            pass
        self._set_main(shown)

    def _set_main(self, text, muted=False):
        self.main_lbl.configure(text=text, fg=C["fg_dim"] if muted else C["fg_bright"])
        self._fit_font()

    def _fit_font(self):
        width = max(50, self.main_lbl.winfo_width())
        family, size = FONTS["h1"][0], FONTS["h1"][1]
        import tkinter.font as tkfont
        text = self.main_lbl.cget("text")
        while size > 10 and tkfont.Font(family=family, size=size, weight="bold").measure(text) > width - px(8):
            size -= 2
        self.main_lbl.configure(font=(family, size, "bold"))

    def _show_error(self, message):
        self.expr_lbl.configure(text=self._pretty(self.expr))
        self.main_lbl.configure(text=message, fg=C["danger"], font=(FONTS["h3"][0], FONTS["h3"][1], "bold"))
        self.just_evaluated = False

    def _context_menu(self, event):
        m = theme.popup_menu(self)
        m.add_command(label=T("Copy"), accelerator=theme.keys("Ctrl+C"), command=self.copy_result)
        m.add_command(label=T("Paste"), accelerator=theme.keys("Ctrl+V"), command=self.paste)
        theme.show_menu(m, event.x_root, event.y_root)

    # ── history / on top ──
    def toggle_history(self):
        if self.hist.winfo_manager():
            self.hist.pack_forget()
            self.pad.pack(fill="both", expand=True)
            self.hist_btn.set_toggled(False)
        else:
            self.pad.pack_forget()
            self.hist.pack(fill="both", expand=True)
            self.hist_btn.set_toggled(True)
            self._fill_history()

    def _fill_history(self):
        self.hist_list.delete(0, "end")
        for expr, value in self.history:
            self.hist_list.insert("end", f"{self._pretty(expr)} = {format_number(value)}")
        if self.history:
            self.hist_empty.place_forget()
        else:
            self.hist_empty.place(relx=0.5, rely=0.3, anchor="center")

    def _use_history(self, _event=None):
        sel = self.hist_list.curselection()
        if not sel:
            return
        _expr, value = self.history[sel[0]]
        self.expr = format_number(value, group=False)
        self.just_evaluated = True
        self.toggle_history()
        self._refresh()

    def toggle_on_top(self):
        self.on_top = not self.on_top
        self.attributes("-topmost", self.on_top)
        self.pin_btn.set_toggled(self.on_top)
        self.app.settings["calc_on_top"] = self.on_top

    def close(self):
        if getattr(self.app, "calculator", None) is self:
            self.app.calculator = None
        self.destroy()


def show(app):
    calc = getattr(app, "calculator", None)
    if calc is not None and calc.winfo_exists():
        calc.deiconify()
        calc.lift()
        calc.focus_force()
        return calc
    app.calculator = Calculator(app)
    return app.calculator
