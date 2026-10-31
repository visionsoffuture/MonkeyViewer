"""End-to-end checks with the real window (skipped when no display is available)."""

import time
import tkinter as tk
import types

import fitz

import pytest

import samples

pytestmark = pytest.mark.gui


def _pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


def _app(root):
    from viewer import app as appmod
    a = appmod.App(root)
    _pump(root)
    return a


def test_opens_specialist_files(tk_root, tmp_path):
    a = _app(tk_root)
    files = [samples.pdf(tmp_path / "a.pdf"), samples.dxf(tmp_path / "b.dxf"),
             samples.pol(tmp_path / "Registry.pol")]
    a.open_paths([str(f) for f in files])
    for _ in range(100):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    kinds = sorted(t.kind for t in a.tabs)
    assert kinds == ["dxf", "pdf", "table"]


def test_ctrl_v_pastes_exactly_once(tk_root, tmp_path):
    a = _app(tk_root)
    f = tmp_path / "x.lua"
    f.write_text("-- code\n")
    a.open_paths([str(f)])
    _pump(tk_root)
    text = a.active.text
    tk_root.lift()
    tk_root.focus_force()
    _pump(tk_root, 0.3)
    text.focus_force()
    _pump(tk_root, 0.2)
    text.mark_set("insert", "1.0")
    tk_root.clipboard_clear()
    tk_root.clipboard_append("Q")
    from viewer import theme
    state = 0x8 if theme.IS_MAC else 0x4
    text.event_generate("<KeyPress>", keysym="v", state=state)
    _pump(tk_root, 0.3)
    assert text.get("1.0", "1.end") == "Q-- code"
    # Georgian layout: the character for "v" is ვ
    a.on_ctrl_key(types.SimpleNamespace(state=state, keysym="Georgian_vin", keycode=0, char="ვ", widget=text))
    _pump(tk_root, 0.3)
    assert text.get("1.0", "1.end") == "QQ-- code"


def test_read_only_policy_blocks_saving(tk_root, tmp_path):
    from tkinter import filedialog
    from viewer import policy
    a = _app(tk_root)
    policy.override({"ReadOnly": 1})
    assert filedialog.asksaveasfilename(parent=tk_root) == ""
    f = tmp_path / "x.lua"
    f.write_text("x")
    a.open_paths([str(f)])
    _pump(tk_root)
    assert a.save_tab(a.active) is False


def _texts(widget):
    out = []
    for child in widget.winfo_children():
        try:
            out.append(str(child.cget("text")))
        except Exception:  # noqa: BLE001 - widgets without a text option
            pass
        out += _texts(child)
    return out


def test_georgian_interface(tk_root, tmp_path, monkeypatch):
    from viewer import i18n, winutil
    settings = winutil.Settings()
    settings["language"] = "ka"
    settings.save()
    a = _app(tk_root)
    assert i18n.current() == "ka"
    texts = _texts(tk_root)
    assert "ფაილების გახსნა" in texts
    assert any("Office ვერ ხსნის" in t for t in texts)
    a.open_paths([str(samples.pdf(tmp_path / "a.pdf"))])
    for _ in range(50):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    assert any(seg.startswith("გვერდი 1 / ") for seg in a.active.status())
    from viewer import app as appmod
    asked = []
    monkeypatch.setattr(appmod.messagebox, "askyesno", lambda title, question, **kw: asked.append((title, question)) or False)
    a.set_language("en")
    assert winutil.Settings()["language"] == "en"
    assert asked and asked[0][0] == "Language" and "Restart" in asked[0][1]    # asked in the new language


def test_toolbar_overflow_keeps_every_command_reachable(tk_root, tmp_path):
    a = _app(tk_root)
    a.open_paths([str(samples.pdf(tmp_path / "a.pdf"))])
    for _ in range(50):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    tk_root.geometry("700x600")
    _pump(tk_root, 0.6)
    bar = a.active.bar
    assert bar.overflow.winfo_ismapped()
    hidden = bar._hidden_buttons()
    assert hidden
    from viewer import theme
    menu = theme.popup_menu(tk_root)
    bar._overflow_menu(menu)
    assert menu.index("end") is not None and menu.index("end") + 1 >= len(hidden)
    tk_root.geometry(f"{tk_root.winfo_screenwidth()}x700+0+0")     # as wide as this screen allows
    _pump(tk_root, 0.6)
    assert bool(bar.overflow.winfo_ismapped()) == bar._clipped()      # » only while something is cut off


def test_user_guide_opens(tk_root):
    a = _app(tk_root)
    a.open_user_guide()
    for _ in range(30):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    tab = a.active
    assert tab is not None and tab.kind == "document" and getattr(tab, "is_guide", False)
    assert tab.page_count >= 3 and "Monkey Viewer" in tab.doc[0].get_text()      # laid out, not Markdown
    a.open_user_guide()
    assert sum(1 for t in a.tabs if getattr(t, "is_guide", False)) == 1         # opened once


def test_theme_choice_and_light_palette(tk_root, monkeypatch):
    from viewer import app as appmod, theme, winutil
    settings = winutil.Settings()
    settings["theme"] = "light"
    settings.save()
    a = _app(tk_root)
    assert not theme.IS_DARK and theme.C["bg"] == theme.LIGHT["bg"]
    asked = []
    monkeypatch.setattr(appmod.messagebox, "askyesno", lambda title, question, **kw: asked.append(title) or False)
    a.set_theme("dark")
    assert winutil.Settings()["theme"] == "dark" and asked


def test_pdf_save_as_images_and_crop_frame(tk_root, tmp_path):
    a = _app(tk_root)
    pdf = samples.pdf(tmp_path / "doc.pdf")
    a.open_paths([str(pdf)])
    for _ in range(50):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    t = a.active
    t.save_to(str(tmp_path / "pages.png"))
    assert t.exported and all(p.endswith(".png") for p in t.exported)
    t.exported = None
    t.set_tool("crop")
    x, y, w, h = t.boxes[0]
    ev = types.SimpleNamespace(x=0, y=0)
    t.on_tool_press(ev, x + w * 0.2, y + h * 0.2, 0)
    t.on_tool_drag(ev, x + w * 0.8, y + h * 0.6)
    t.on_tool_release(ev, x + w * 0.8, y + h * 0.6)
    assert t.crop is not None and t.crop_bar is not None          # nothing cut yet: frame + Apply bar
    full = t.doc[0].cropbox
    t.apply_crop()
    assert t.crop is None and t.doc[0].cropbox.width < full.width * 0.7
    # "Selected pages" on page 2 while only page 1 was (by default) selected crops page 2 alone
    if t.page_count > 1:
        t.selected = {0}
        before0 = fitz.Rect(t.doc[0].cropbox)
        x, y, w, h = t.boxes[1]
        t.on_tool_press(ev, x + w * 0.1, y + h * 0.1, 1)
        t.on_tool_drag(ev, x + w * 0.9, y + h * 0.9)
        t.on_tool_release(ev, x + w * 0.9, y + h * 0.9)
        t.crop["target"] = "selected"
        assert t._crop_targets() == [1]
        t._margin_vars["left"].set("20")                    # exact margin typed in millimetres
        assert abs(t.crop["rect"].x0 - 20 * 72 / 25.4) < 0.01
        x0 = t.crop["rect"].x0
        t.crop_nudge(10, 0)
        assert abs(t.crop["rect"].x0 - x0 - 10) < 0.01
        t.apply_crop()
        assert t.doc[0].cropbox == before0
        assert abs(t.doc[1].cropbox.x0 - (x0 + 10)) < 0.5


def test_signed_pdf_banner_and_eyedropper(tk_root, tmp_path):
    a = _app(tk_root)
    key, cert = samples.self_signed("Banner Signer")
    path = samples.signed_pdf(str(tmp_path / "signed.pdf"), key, cert)
    a.open_paths([path])
    for _ in range(60):
        _pump(tk_root, 0.1)
        if getattr(a.active, "signatures", None):
            break
    t = a.active
    assert t.signatures and t.signatures[0]["intact"] and t.sig_banner is not None
    panel = t.signature_details()                           # designed panel, not a text tab
    assert panel.winfo_exists() and t.signature_details() is panel
    panel._toggle(1)                                        # certificate details
    panel.set_trust({1: (False, "Not trusted")})
    texts = [w.cget("text") for w in panel._all(panel.inner) if isinstance(w, tk.Label)]
    assert "Banner Signer" in texts and "Not trusted" in texts
    panel.close()
    t.set_tool("pen")
    t.start_eyedropper()
    x, y, _w, _h = t.boxes[0]
    t.on_tool_press(types.SimpleNamespace(x=0, y=0), x + 3, y + 3, 0)
    assert t.colors["pen"] == "#ffffff"                     # the page background is white


def test_menu_bar_and_print_for_every_type(tk_root, tmp_path):
    from PIL import Image
    from viewer import theme
    a = _app(tk_root)
    (tmp_path / "c.lua").write_text("print('ქართული')\n", encoding="utf-8")
    geojson = ('{"type":"FeatureCollection","features":[{"type":"Feature","properties":{"n":1},'
               '"geometry":{"type":"Point","coordinates":[44.8,41.7]}}]}')
    (tmp_path / "m.geojson").write_text(geojson, encoding="utf-8")
    Image.new("RGB", (64, 40), "blue").save(tmp_path / "i.png")
    files = [samples.pdf(tmp_path / "a.pdf"), samples.dxf(tmp_path / "b.dxf"), samples.pol(tmp_path / "R.pol"),
             tmp_path / "c.lua", tmp_path / "m.geojson", tmp_path / "i.png"]
    a.open_paths([str(f) for f in files])
    for _ in range(150):
        _pump(tk_root, 0.1)
        if not a._pending and all(getattr(t, "spinner", None) is None for t in a.tabs):
            break
    assert len(a.tabs) == 6
    model = a.menu_model
    for tab in list(a.tabs):
        a.select_tab(tab)
        _pump(tk_root, 0.2)
        titles = model.titles()
        assert [k for k, _ in titles][:3] == ["file", "edit", "view"] and titles[-1][0] == "help"
        assert tab.menu_title(), tab.kind                        # every type has its own menu
        if a.menubar is not None:
            assert tab.menu_title() in [w.cget("text") for w in a.menubar.labels.values()]
        for key, _label in titles:
            m = theme.popup_menu(tk_root)
            model.fill(key, m)
            assert m.index("end") is not None
            m.destroy()
        doc = tab.print_document()
        assert doc is not None and len(doc) >= 1, tab.kind
    m = theme.popup_menu(tk_root)
    model.fill_app_menu(m)
    assert m.index("end") > 10


def test_print_flows_without_a_printer(tk_root, tmp_path, monkeypatch):
    from viewer import printing
    a = _app(tk_root)
    a.open_paths([str(samples.pdf(tmp_path / "p.pdf", pages=3))])
    for _ in range(50):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    sent = {}
    # macOS / Linux: our dialog, then lp
    monkeypatch.setattr(printing, "cups_printers", lambda: (["Office"], "Office"))
    monkeypatch.setattr(printing.CupsDialog, "run", lambda self: {"printer": "Office", "pages": [0, 2],
                                                                   "copies": 2, "sides": None})
    monkeypatch.setattr(printing, "cups_print", lambda data, title, printer, copies, pages, sides: sent.update(
        cups=(data[:5], printer, copies, pages)))
    monkeypatch.setattr(printing.sys, "platform", "linux")
    a.print_active()
    for _ in range(30):
        _pump(tk_root, 0.1)
        if sent:
            break
    assert sent["cups"] == (b"%PDF-", "Office", 2, "1,3")
    # Windows: system dialog, then GDI in a worker with a private copy of the document
    monkeypatch.setattr(printing.sys, "platform", "win32")
    monkeypatch.setattr(printing, "_win_print_dialog", lambda hwnd, count, current, selected: (1234, [1]))
    monkeypatch.setattr(printing, "_win_print", lambda hdc, doc, pages, title: sent.update(
        win=(hdc, len(doc), pages, doc is a.active.doc)) or len(pages))
    a.print_active()
    for _ in range(30):
        _pump(tk_root, 0.1)
        if "win" in sent:
            break
    assert sent["win"] == (1234, 3, [1], False)


def test_narrow_window_keeps_everything_reachable(tk_root, tmp_path):
    """Works on any screen size (CI runners have small screens): checks follow the real window width."""
    from viewer.theme import px
    a = _app(tk_root)
    if not a.sidebar_visible:
        a.toggle_sidebar()
    a.show_home()

    def resize(w, h):
        tk_root.geometry(f"{w}x{h}")
        _pump(tk_root, 0.8)
        return tk_root.winfo_width()

    def expected_cols():
        width = max(px(280), min(px(1000), a._welcome_canvas.winfo_width() - px(48)))
        return 4 if width >= px(860) else 2 if width >= px(470) else 1

    narrow = resize(px(640), px(420))
    assert narrow < px(820) and not a.sidebar_visible             # the file list gives way...
    assert a._tile_cols == expected_cols() in (1, 2)               # ...the tiles reflow...
    box_h = a._welcome_box.winfo_reqheight()
    assert bool(a._welcome_sb.winfo_ismapped()) == (box_h + 2 * px(18) > a._welcome_canvas.winfo_height())
    wide = resize(min(tk_root.winfo_screenwidth(), px(1280)), min(tk_root.winfo_screenheight(), px(800)))
    if wide >= px(900):
        assert a.sidebar_visible                                   # ...and comes back when there is room
    assert a._tile_cols == expected_cols()


def test_menu_closes_when_the_pointer_leaves(tk_root):
    from viewer import theme
    if theme.IS_WIN or theme.IS_MAC:
        pytest.skip("Windows / macOS menus are native; the X11 watcher is what can be driven here")
    a = _app(tk_root)
    tk_root.geometry("900x600+0+0")
    _pump(tk_root, 0.3)
    lab = a.menubar.labels["file"]
    m = theme.popup_menu(tk_root)
    a.menu_model.fill("file", m)
    tk_root.event_generate("<Motion>", warp=True, x=lab.winfo_rootx() - tk_root.winfo_rootx() + 5,
                           y=lab.winfo_rooty() - tk_root.winfo_rooty() + 5)
    _pump(tk_root, 0.2)
    theme.show_menu(m, lab.winfo_rootx(), lab.winfo_rooty() + lab.winfo_height(), anchor=lab)
    _pump(tk_root, 0.8)
    assert m.winfo_ismapped()                                      # pointer on its button: stays open
    tk_root.event_generate("<Motion>", warp=True, x=850, y=550)
    _pump(tk_root, 1.2)
    assert not m.winfo_ismapped()                                  # pointer gone: it closes by itself


def test_run_svg_from_the_code_view(tk_root, tmp_path):
    import test_svg
    a = _app(tk_root)
    f = tmp_path / "spinner.svg"
    f.write_text(test_svg.SPINNER, encoding="utf-8")
    a.open_paths([str(f)])
    _pump(tk_root, 0.5)
    code = a.active
    assert code.kind == "text" and code.run_btn is not None
    code.run_svg()
    _pump(tk_root, 0.6)
    view = a.active
    assert view.kind == "svg" and view.source is code and view.anim is not None and view.playing
    t1 = view.current_time()
    _pump(tk_root, 0.4)
    assert view.current_time() > t1 and view.photo is not None
    view.toggle_play()
    assert not view.playing
    code.text.insert("end", "\n")                 # edit the code, run again: the same preview is refreshed
    code.run_svg()
    _pump(tk_root, 0.3)
    assert a.active is view and sum(1 for t in a.tabs if t.kind == "svg") == 1 and view.playing
    doc = view.print_document()
    assert len(doc) == 1


def test_big_file_is_coloured_without_freezing_the_window(tk_root, tmp_path):
    import time as _t
    a = _app(tk_root)
    f = tmp_path / "big.lua"
    f.write_text("".join(f'local v{i} = "text {i}" -- note\n' for i in range(20000)), encoding="utf-8")
    a.open_paths([str(f)])
    longest, last = 0.0, _t.perf_counter()
    end = _t.time() + 6
    tab = None
    while _t.time() < end:
        tk_root.update()
        now = _t.perf_counter()
        longest, last = max(longest, now - last), now
        tab = a.active
        if tab is not None and tab.kind == "text" and len(tab.text.tag_ranges("syn_comment")) >= 40000:
            break
        _t.sleep(0.005)
    assert len(tab.text.tag_ranges("syn_comment")) == 40000            # every line's comment, in slices
    assert longest < 3.0


def test_highlight_on_empty_area_does_not_fail(tk_root, tmp_path):
    import fitz
    a = _app(tk_root)
    a.open_paths([str(samples.pdf(tmp_path / "h.pdf"))])
    for _ in range(50):
        _pump(tk_root, 0.1)
        if not a._pending:
            break
    t = a.active
    before = len(list(t.doc[0].annots()))
    t._add_highlight(0, fitz.Rect(500, 800, 500.2, 800.2))            # no words, a dot-sized area
    assert len(list(t.doc[0].annots())) == before and not t.undo_stack
    t._add_highlight(0, fitz.Rect(40, 60, 300, 90))                   # over the sample's text
    assert len(list(t.doc[0].annots())) == before + 1


def test_calculator_window_and_weather_corner(tk_root, monkeypatch):
    import time as _t
    from viewer import weather
    monkeypatch.setattr(weather, "get", lambda city, force=False: (
        weather.summarise(samples.met_forecast(_t.strftime("%Y-%m-%dT%H:00:00Z", _t.gmtime()))), _t.time()))
    a = _app(tk_root)
    calc = a.show_calculator() or a.calculator
    assert a.show_calculator() is calc                       # one window, brought to the front
    for k in "12+30%":
        calc.press(k)
    calc.press("=")
    assert calc.main_lbl.cget("text") == "15.6" and calc.history
    calc.press("C")
    calc.press("5")
    calc.press("±")
    assert calc.expr == "-5"
    calc.press("√x")
    assert "Invalid" in calc.main_lbl.cget("text")
    calc.close()
    assert a.calculator is None
    a.weather.refresh()
    for _ in range(30):
        _pump(tk_root, 0.1)
        if a.weather.summary:
            break
    assert a.weather.summary and "°" in a.weather.label.cget("text")
    a.weather.toggle_popup()
    _pump(tk_root, 0.3)
    assert a.weather.popup is not None
    a.weather.set_enabled(False)
    assert a.weather.popup is None and not a.weather.label.winfo_manager()
    a.weather.set_enabled(True)
    assert a.weather.label.winfo_manager()
