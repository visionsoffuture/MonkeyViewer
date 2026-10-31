#!/bin/bash
# Removes Monkey Viewer from this Mac and gives its file types back to the apps they used before.
APP="$HOME/Applications/Monkey Viewer.app"
[ -d "$APP" ] || APP="/Applications/Monkey Viewer.app"
LSREGISTER="/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister"
if [ ! -d "$APP" ]; then
    echo "Monkey Viewer is not installed."
    exit 0
fi
osascript -e 'tell application id "ge.easy.monkeyviewer" to quit' >/dev/null 2>&1
sleep 1
"$APP/Contents/MacOS/MonkeyViewer" --unregister --quiet
[ -x "$LSREGISTER" ] && "$LSREGISTER" -u "$APP" >/dev/null 2>&1
rm -rf "$APP"
echo "Monkey Viewer was removed. (Settings stay in ~/Library/Application Support/MonkeyViewer)"
rm -f "$0"
