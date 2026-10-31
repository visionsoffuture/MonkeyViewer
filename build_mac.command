#!/bin/bash
# Monkey Viewer - build the macOS app (Apple Silicon or Intel) and a .dmg into ./release.
# Python is needed only on this build Mac; users get a normal app.
#   bash build_mac.command                 build, test, package
#   bash build_mac.command --install       also copy the app to ~/Applications
# Optional signing: export MAC_SIGN_IDENTITY="Developer ID Application: Name (TEAMID)" before running.
set -u
cd "$(dirname "$0")" || exit 1
fail() { echo; echo "Build failed: $1"; exit 1; }

echo "[1/6] Python 3.12 with Tk 8.6..."
PY=""
for cand in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3 /opt/homebrew/bin/python3.12 \
            /usr/local/bin/python3.12 python3.12; do
    if command -v "$cand" >/dev/null 2>&1 && "$cand" -c "import tkinter, sys; sys.exit(0 if tkinter.TkVersion >= 8.6 else 1)" 2>/dev/null; then
        PY="$cand"; break
    fi
done
[ -n "$PY" ] || fail "install Python 3.12 from https://www.python.org/downloads/macos/ (includes Tk 8.6)"

echo "[2/6] Locked components..."
[ -x .build-venv-mac/bin/python ] || "$PY" -m venv .build-venv-mac || fail "venv"
VPY=.build-venv-mac/bin/python
"$VPY" -m pip install --quiet --upgrade pip
"$VPY" -m pip install --quiet --require-hashes -r requirements-lock.txt || fail "components"
"$VPY" -m pip install --quiet --require-hashes -r requirements-dev-lock.txt || fail "test tools"

echo "[3/6] Tests..."
"$VPY" -m pytest -q || fail "tests"

echo "[4/6] Building the app..."
"$VPY" tools/write_build_info.py
"$VPY" -m PyInstaller MonkeyViewer.spec --noconfirm --clean || fail "PyInstaller"
APP="dist/Monkey Viewer.app"
[ -d "$APP" ] || fail "app bundle missing"
VERSION=$("$VPY" -c "from viewer import app_info; print(app_info.VERSION)")
mkdir -p release
"$APP/Contents/MacOS/MonkeyViewer" --self-test=release/selftest-macos.json || { cat release/selftest-macos.json; fail "self test"; }

echo "[5/6] Signing..."
if [ -n "${MAC_SIGN_IDENTITY:-}" ]; then
    codesign --force --deep --options runtime --timestamp --entitlements packaging/macos/entitlements.plist \
        --sign "$MAC_SIGN_IDENTITY" "$APP" || fail "codesign"
else
    codesign --force --deep --sign - "$APP" >/dev/null 2>&1   # ad-hoc (no Apple Developer ID)
fi

echo "[6/6] Disk image..."
DMG="release/MonkeyViewer-$VERSION-macos.dmg"
rm -f "$DMG"
bash packaging/macos/make_dmg.sh "$APP" "$DMG" "Monkey Viewer $VERSION" >/dev/null || fail "dmg"
(cd release && shasum -a 256 "$(basename "$DMG")" > "$(basename "$DMG").sha256")

if [ "${1:-}" = "--install" ]; then
    mkdir -p "$HOME/Applications"
    rm -rf "$HOME/Applications/Monkey Viewer.app"
    ditto "$APP" "$HOME/Applications/Monkey Viewer.app"
    /System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister \
        -f "$HOME/Applications/Monkey Viewer.app" >/dev/null 2>&1
    open "$HOME/Applications/Monkey Viewer.app" --args --associations
fi
echo "Done: $DMG"
