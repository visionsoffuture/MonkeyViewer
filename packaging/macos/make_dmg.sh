#!/bin/bash
# Build the macOS disk image: Monkey Viewer.app, an arrow to Applications on a branded background,
# the app logo as the volume icon and installation notes.
#   packaging/macos/make_dmg.sh "dist/Monkey Viewer.app" release/MonkeyViewer-<ver>-macos.dmg "Monkey Viewer <ver>"
set -euo pipefail
APP="$1"; OUT="$2"; VOL="$3"
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
STAGE="$(mktemp -d)"
RW="$(mktemp -u -t monkeyviewer).dmg"
README="README - ინსტალაცია.txt"

ditto "$APP" "$STAGE/Monkey Viewer.app"
ln -s /Applications "$STAGE/Applications"
cp "$HERE/DMG_README.txt" "$STAGE/$README"
mkdir "$STAGE/.background"
BG="background.tiff"
if ! tiffutil -cathidpicheck "$HERE/dmg-background.png" "$HERE/dmg-background@2x.png" \
        -out "$STAGE/.background/$BG" >/dev/null 2>&1; then
    BG="background.png"
    cp "$HERE/dmg-background.png" "$STAGE/.background/$BG"
fi
cp "$ROOT/monkeyviewer.icns" "$STAGE/.VolumeIcon.icns"

[ -d "/Volumes/$VOL" ] && hdiutil detach "/Volumes/$VOL" -force >/dev/null 2>&1 || true
hdiutil create -volname "$VOL" -srcfolder "$STAGE" -fs HFS+ -format UDRW -ov "$RW" >/dev/null
DEV="$(hdiutil attach -readwrite -noverify -noautoopen "$RW" | awk '/Apple_HFS/ {print $1; exit}')"
MNT="/Volumes/$VOL"
mdutil -i off "$MNT" >/dev/null 2>&1 || true        # no Spotlight indexing: it keeps the volume busy
SetFile -a C "$MNT" 2>/dev/null || xattr -wx com.apple.FinderInfo \
    "0000000000000000040000000000000000000000000000000000000000000000" "$MNT" 2>/dev/null || true

# Finder window layout (icon positions, background). Skipped - not fatal - if Finder can't be scripted.
perl -e 'alarm 180; exec @ARGV' osascript <<EOF || echo "note: Finder layout skipped"
tell application "Finder"
    tell disk "$VOL"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set the bounds of container window to {200, 120, 840, 548}
        set opts to the icon view options of container window
        set arrangement of opts to not arranged
        set icon size of opts to 96
        set text size of opts to 12
        set background picture of opts to file ".background:$BG"
        set position of item "Monkey Viewer.app" of container window to {160, 190}
        set position of item "Applications" of container window to {480, 190}
        set position of item "$README" of container window to {580, 360}
        close
        open
        update without registering applications
        delay 2
        close
    end tell
end tell
EOF

sync
# Finder / Spotlight can hold the fresh volume for a few seconds ("Resource busy"): retry, then force
detached=0
for i in 1 2 3 4 5 6 7 8 9 10; do
    if [ "$i" -le 4 ]; then flag=""; else flag="-force"; fi
    # shellcheck disable=SC2086 # empty or a single option
    if hdiutil detach "$DEV" $flag >/dev/null 2>&1; then detached=1; break; fi
    echo "note: $DEV still busy (try $i), waiting"
    osascript -e "tell application \"Finder\" to close every window" >/dev/null 2>&1 || true
    sleep 3
done
if [ "$detached" != 1 ]; then
    lsof +f -- "$MNT" 2>/dev/null | head -20 || true
    hdiutil detach "$DEV" -force
fi
mkdir -p "$(dirname "$OUT")"
hdiutil convert "$RW" -format UDZO -imagekey zlib-level=9 -ov -o "$OUT" >/dev/null
rm -f "$RW"
rm -rf "$STAGE"
echo "$OUT"
