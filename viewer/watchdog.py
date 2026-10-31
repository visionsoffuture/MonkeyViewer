"""Freeze detector: when the window stops responding for a few seconds, write what the program was doing
(the stack of every thread) to hang.log, so a "Not responding" can be traced to its cause.

The time a native dialog (file chooser, message box) is open on purpose is not counted as a freeze, but the
dialog that was open last is recorded, so a freeze right after closing one is attributed to it.
"""

import faulthandler
import io
import os
import sys
import threading
import time
import traceback

HANG_SECONDS = 4.0

_state = {"beat": time.monotonic(), "dialog": None, "dialog_closed": None, "reported": False, "path": None}


def log_path():
    from . import winutil
    return os.path.join(winutil.config_dir(), "hang.log")


def _stacks():
    out = io.StringIO()
    frames = sys._current_frames()
    names = {t.ident: t.name for t in threading.enumerate()}
    for ident, frame in frames.items():
        if ident == threading.get_ident():          # the watchdog itself
            continue
        out.write(f"\n--- thread {names.get(ident, ident)} ---\n")
        out.write("".join(traceback.format_stack(frame)))
    return out.getvalue()


def _report(stalled):
    from . import app_info
    dialog = _state["dialog"]
    closed = _state["dialog_closed"]
    lines = [f"===== {time.strftime('%Y-%m-%d %H:%M:%S')}  {app_info.NAME} {app_info.VERSION}",
             f"The window did not respond for {stalled:.1f} s."]
    if closed:
        name, at = closed
        lines.append(f"The last native dialog ({name}) was closed {time.monotonic() - at:.1f} s ago.")
    if dialog:
        lines.append(f"A native dialog is open: {dialog}.")
    text = "\n".join(lines) + "\n" + _stacks() + "\n"
    try:
        path = log_path()
        if os.path.exists(path) and os.path.getsize(path) > 2_000_000:
            os.replace(path, path + ".1")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(text)
    except OSError:
        pass
    try:
        from . import audit
        audit.event("hang", warning=True, seconds=round(stalled, 1),
                    dialog=(dialog or (closed[0] if closed else "")))
    except Exception:  # noqa: BLE001
        pass


def _main_thread_idle():
    """True when the main thread is not running any Python code of ours - it waits inside Tk's own loop.
    That is a native modal loop (moving / resizing the window, an open menu, a system dialog) or the
    computer sleeping, not a freeze caused by the program."""
    frame = sys._current_frames().get(threading.main_thread().ident)
    if frame is None:
        return False
    names = [f.name for f in traceback.extract_stack(frame)]
    return bool(names) and names[-1] == "mainloop"


def _watch():
    last = time.monotonic()
    while True:
        time.sleep(0.5)
        now = time.monotonic()
        if now - last > 3.0:                     # this thread itself was not running: sleep / hibernation
            _state["beat"] = now
        last = now
        if _state["dialog"]:
            continue
        stalled = now - _state["beat"]
        if stalled >= HANG_SECONDS and not _state["reported"]:
            if _main_thread_idle():
                continue
            _state["reported"] = True
            _report(stalled)


def start(root):
    """Heartbeat from the Tk main loop plus a watcher thread. Call once."""
    def beat():
        now = time.monotonic()
        if _state["reported"]:
            _state["reported"] = False
            try:
                with open(log_path(), "a", encoding="utf-8") as fh:
                    fh.write(f"(responding again after {now - _state['beat']:.1f} s)\n")
            except OSError:
                pass
        _state["beat"] = now
        root.after(250, beat)
    beat()
    threading.Thread(target=_watch, name="freeze-watchdog", daemon=True).start()
    try:
        faulthandler.enable()            # hard crashes also leave a trace on stderr
    except (RuntimeError, ValueError, io.UnsupportedOperation):
        pass


def native_dialog(name, func):
    """Wrap a blocking dialog function so its open time is not reported as a freeze."""
    def wrapper(*args, **kw):
        _state["dialog"] = name
        try:
            return func(*args, **kw)
        finally:
            _state["dialog"] = None
            _state["dialog_closed"] = (name, time.monotonic())
            _state["beat"] = time.monotonic()
    wrapper._lv_watch = True
    return wrapper


def wrap_dialogs():
    from tkinter import colorchooser, filedialog, messagebox
    for module, names in ((filedialog, ("askopenfilename", "askopenfilenames", "asksaveasfilename",
                                        "askdirectory")),
                          (messagebox, ("showinfo", "showwarning", "showerror", "askyesno", "askokcancel",
                                        "askyesnocancel", "askquestion", "askretrycancel")),
                          (colorchooser, ("askcolor",))):
        for n in names:
            func = getattr(module, n)
            if not getattr(func, "_lv_watch", False):
                setattr(module, n, native_dialog(f"{module.__name__.split('.')[-1]}.{n}", func))
