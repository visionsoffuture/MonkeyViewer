import os
import sys

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


@pytest.fixture(autouse=True)
def isolated_home(tmp_path, monkeypatch):
    """Every test gets its own settings / audit folder and no system policies."""
    home = tmp_path / "home"
    home.mkdir()
    for var in ("HOME", "USERPROFILE"):
        monkeypatch.setenv(var, str(home))
    monkeypatch.setenv("APPDATA", str(home / "AppData" / "Roaming"))
    monkeypatch.setenv("MONKEYVIEWER_OFFLINE", "1")          # tests never go to the internet (weather)
    from viewer import i18n, policy
    policy.override({})
    monkeypatch.setattr(i18n, "system_language", lambda: "en")   # English unless a test asks
    i18n.setup("en")
    yield home
    i18n.setup("en")
    if "viewer.theme" in sys.modules:           # palette back to the default for the next test
        sys.modules["viewer.theme"].set_mode("dark")
    policy.override(None)


@pytest.fixture
def tk_root():
    tk = pytest.importorskip("tkinter")
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    root.geometry("1100x700+20+20")       # keyboard events need a mapped, focusable window
    yield root
    root.destroy()
    from viewer import theme
    theme._IMAGES.clear()            # images belong to the destroyed interpreter
