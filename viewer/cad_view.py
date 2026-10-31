"""AutoCAD DXF and DWG (DWG through the bundled LibreDWG, or ODA File Converter) as zoomable vector pages."""

import os
import tkinter as tk
from tkinter import ttk

from . import theme, winutil
from .base import Notice
from .pdf_view import PdfView, open_pdf_bytes
from .theme import C, FONTS, px
from .i18n import T

INSUNITS = {0: "unitless", 1: "inches", 2: "feet", 4: "mm", 5: "cm", 6: "m", 7: "km", 14: "dm"}


def configure_oda():
    exe = winutil.find_oda_converter()
    if not exe:
        return None
    try:
        import ezdxf
        key = "win_exec_path" if winutil.IS_WIN else "unix_exec_path"
        ezdxf.options.set("odafc-addon", key, exe)
    except Exception:  # noqa: BLE001
        return None
    return exe


def can_read_dwg():
    return bool(configure_oda() or winutil.find_dwg2dxf())


def read_dwg(path):
    """DWG -> ezdxf document: ODA File Converter when installed (most faithful), else the bundled LibreDWG."""
    if configure_oda():
        from ezdxf.addons import odafc
        try:
            return odafc.readfile(path)
        except Exception as exc:  # noqa: BLE001 - fall back to LibreDWG
            winutil.log_error(f"ODA File Converter failed, trying LibreDWG: {exc!r}")
    exe = winutil.find_dwg2dxf()
    if not exe:
        raise RuntimeError(T("ODA File Converter is not installed"))
    import shutil
    from ezdxf import recover
    from . import safeio
    tmp = safeio.temp_dir("dwg")
    try:
        out = os.path.join(tmp, "drawing.dxf")
        winutil.run_hidden([exe, "-y", "-o", out, path], timeout=600)
        if not os.path.exists(out) or os.path.getsize(out) == 0:
            raise RuntimeError(T("This DWG file could not be converted (unsupported version or damaged file)."))
        doc, _auditor = recover.readfile(out)
        return doc
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def render_dxf(doc, layout_name="Model", hidden_layers=(), dark=True):
    """Render a layout of an ezdxf document to PDF bytes."""
    from ezdxf import bbox
    from ezdxf.addons.drawing import Frontend, RenderContext, config, layout
    from ezdxf.addons.drawing import pymupdf as pmb
    lay = doc.modelspace() if layout_name == "Model" else doc.paperspace(layout_name)
    hidden = {h.lower() for h in hidden_layers}

    def keep(entity):
        try:
            return entity.dxf.layer.lower() not in hidden
        except Exception:  # noqa: BLE001
            return True

    ext = bbox.extents(lay, fast=True)
    if ext.has_data and ext.size.x > 0 and ext.size.y > 0:
        aspect = ext.size.x / ext.size.y
    else:
        aspect = 1.414
    long_side = 841.0
    w, h = (long_side, max(120.0, long_side / aspect)) if aspect >= 1 else (max(120.0, long_side * aspect), long_side)
    cfg = config.Configuration(
        background_policy=config.BackgroundPolicy.BLACK if dark else config.BackgroundPolicy.WHITE,
        color_policy=config.ColorPolicy.COLOR,
        lineweight_scaling=1.0, min_lineweight=0.12)
    backend = pmb.PyMuPdfBackend()
    Frontend(RenderContext(doc), backend, config=cfg).draw_layout(lay, filter_func=keep)
    page = layout.Page(w, h, layout.Units.mm, margins=layout.Margins.all(6))
    try:
        return backend.get_pdf_bytes(page, settings=layout.Settings(fit_page=True))
    except ValueError as exc:
        if "empty" not in str(exc).lower():
            raise
        return _empty_layout_pdf(dark, bool(hidden))     # nothing visible: a page that says so, not an error


def _empty_layout_pdf(dark, layers_hidden):
    import fitz
    from .i18n import T
    doc = fitz.open()
    page = doc.new_page(width=842, height=595)
    bg, fg = ((0, 0, 0), (0.75, 0.78, 0.86)) if dark else ((1, 1, 1), (0.35, 0.38, 0.48))
    page.draw_rect(page.rect, color=None, fill=bg)
    text = T("Nothing to show in this layout - the layers that have drawings are hidden.") if layers_hidden \
        else T("This layout is empty. Choose Model or another layout.")
    page.insert_htmlbox(fitz.Rect(80, 260, 762, 340),
                        f"<p style='font-family:sans-serif;font-size:16pt;text-align:center;color:rgb("
                        f"{int(fg[0] * 255)},{int(fg[1] * 255)},{int(fg[2] * 255)})'>{text}</p>")
    data = doc.tobytes()
    doc.close()
    return data


class DxfTab(PdfView):
    kind = "dxf"

    def menu_title(self):
        return T("Drawing")

    def fill_menu(self, name, m):
        super().fill_menu(name, m)
        if name == "tools":
            m.add_separator()
            m.add_command(label=T("Layers"), command=self.toggle_layers)
            m.add_command(label=T("Light / dark background"), command=self.toggle_background)

    def __init__(self, app, path=None, title=None):
        self.dxf = None
        self.layout_name = "Model"
        self.hidden = set()
        self.dark = theme.IS_DARK            # drawing background follows the app theme
        self.info = {}
        self._rerender_job = None
        super().__init__(app, path, title)
        self.zoom_mode = "page"

    def build_tools(self):
        bar = self.bar
        self.layout_btn = bar.button(T("Model"), "page", tooltip=T("Model space / paper layouts"), menu=self._layout_menu)
        self.layers_btn = bar.button(T("Layers"), "layers", self.toggle_layers, T("Show / hide layers"))
        self.bg_btn = bar.button(T("Light") if self.dark else T("Dark"), "contrast", self.toggle_background, T("Dark / light background"))
        bar.divider()
        bar.button(T("Save as PDF"), "export", lambda: self.app.export_active_pdf(self), T("Save the drawing as PDF"))
        bar.button(T("Open in AutoCAD"), "external", lambda: self.app.open_external(self.path),
                   T("Open with the default CAD application"))

    def build_ui(self):
        super().build_ui()
        self.thumb_frame.pack_forget()
        self.thumb_sep.pack_forget()
        self.layer_panel = tk.Frame(self.body, bg=C["sidebar"], width=px(250))
        self.layer_panel.pack_propagate(False)
        head = tk.Frame(self.layer_panel, bg=C["sidebar"])
        head.pack(fill="x", padx=px(14), pady=(px(12), px(6)))
        tk.Label(head, text=T("LAYERS"), font=FONTS["caption"], bg=C["sidebar"], fg=C["fg_muted"]).pack(side="left")
        theme.ToolButton(head, T("All"), None, lambda: self._set_all(True), bg=C["sidebar"], pad=(6, 2)).pack(side="right")
        theme.ToolButton(head, T("None"), None, lambda: self._set_all(False), bg=C["sidebar"], pad=(6, 2)).pack(side="right")
        self.layer_tree = ttk.Treeview(self.layer_panel, style="Side.Treeview", show="tree", selectmode="none")
        self.layer_tree.pack(fill="both", expand=True)
        self.layer_tree.bind("<Button-1>", self._on_layer_click)
        self.canvas.configure(bg=C["canvas"])
        self.dark_pages = False

    def load(self):
        path = self.path

        def work():
            import ezdxf
            from ezdxf import recover
            if self.kind == "dwg":
                doc = read_dwg(path)
            else:
                try:
                    doc = ezdxf.readfile(path)
                except Exception:  # noqa: BLE001
                    doc, _auditor = recover.readfile(path)
            info = {"layers": sorted((l.dxf.name, l.color, l.is_off() or l.is_frozen()) for l in doc.layers),
                    "layouts": ["Model"] + [n for n in doc.layout_names_in_taborder() if n != "Model"],
                    "units": INSUNITS.get(doc.header.get("$INSUNITS", 0), "units"),
                    "version": doc.acad_release, "entities": len(doc.modelspace())}
            hidden = {name for name, _c, off in info["layers"] if off}
            return doc, info, hidden, render_dxf(doc, "Model", hidden, self.dark)

        self.run_async(work, self._loaded, error=self._failed, text=T("Rendering drawing…"))

    def _failed(self, exc):
        self.app.replace_with(self, "info", error=str(exc))

    def _loaded(self, result):
        self.dxf, self.info, self.hidden, data = result
        self._fill_layers()
        self.set_document(open_pdf_bytes(data))
        if self.app.active is self:
            self.on_show()
            self.app.update_status()

    def _fill_layers(self):
        t = self.layer_tree
        t.delete(*t.get_children())
        try:
            from ezdxf.colors import aci2rgb
        except Exception:  # noqa: BLE001
            aci2rgb = None
        for name, color, _off in self.info.get("layers", []):
            hexcol = C["fg_dim"]
            if aci2rgb and 0 < abs(color) < 256:
                rgb = aci2rgb(abs(color))
                hexcol = "#%02x%02x%02x" % tuple(rgb)
                if hexcol.lower() in ("#000000", "#ffffff"):
                    hexcol = C["fg_dim"]
            img = theme.swatch_image(hexcol, 12)
            mark = "☐" if name in self.hidden else "☑"
            t.insert("", "end", iid=name, text=f"  {mark}  {name}", image=img)

    def _on_layer_click(self, event):
        name = self.layer_tree.identify_row(event.y)
        if not name:
            return "break"
        self.hidden ^= {name}
        self._fill_layers()
        self._schedule_rerender()
        return "break"

    def _set_all(self, visible):
        self.hidden = set() if visible else {n for n, _c, _o in self.info.get("layers", [])}
        self._fill_layers()
        self._schedule_rerender()

    def toggle_layers(self):
        if self.layer_panel.winfo_ismapped():
            self.layer_panel.pack_forget()
            self.layers_btn.set_toggled(False)
        else:
            self.layer_panel.pack(side="right", fill="y", before=self.main)
            self.layers_btn.set_toggled(True)

    def toggle_background(self):
        self.dark = not self.dark
        self.bg_btn.set_text(T("Light") if self.dark else T("Dark"))
        self._schedule_rerender(1)

    def _layout_menu(self, m):
        for name in self.info.get("layouts", ["Model"]):
            m.add_command(label=T(name) if name == "Model" else name, command=lambda n=name: self._set_layout(n))

    def _set_layout(self, name):
        self.layout_name = name
        self.layout_btn.set_text(T(name) if name == "Model" else name)
        self._schedule_rerender(1)

    def _schedule_rerender(self, delay=500):
        if self._rerender_job:
            self.app.root.after_cancel(self._rerender_job)
        self._rerender_job = self.app.root.after(delay, self._rerender)

    def _rerender(self):
        self._rerender_job = None
        if self.dxf is None:
            return
        doc, name, hidden, dark = self.dxf, self.layout_name, set(self.hidden), self.dark

        def done(data):
            self.zoom_mode = self.zoom_mode or "page"
            self.set_document(open_pdf_bytes(data))

        self.run_async(lambda: render_dxf(doc, name, hidden, dark), done, text=T("Rendering drawing…"))

    def on_show(self):
        if self.doc is not None and not self.boxes:
            self.zoom_mode = "page"
        super().on_show()

    def type_label(self):
        return T("AutoCAD DWG drawing") if self.kind == "dwg" else T("AutoCAD DXF drawing")

    def status(self):
        segs = []
        if self.info:
            segs += [T("{0:,} entities", self.info['entities']), T("{0} layers", len(self.info['layers'])),
                     T("Units: {0}", self.info['units'])]
        return segs + [f"{round(self.ppp / self.base_ppp * 100)}%", self.type_label()]

    def destroy(self):
        if self._rerender_job:
            try:
                self.app.root.after_cancel(self._rerender_job)
            except tk.TclError:
                pass
        super().destroy()


class DwgTab(DxfTab):
    kind = "dwg"

    def load(self):
        if not can_read_dwg():
            raise Notice(T("Full DWG viewing needs the free ODA File Converter — showing the preview stored "
                         "in the drawing."))
        super().load()

    def type_label(self):
        return T("AutoCAD DWG drawing")

