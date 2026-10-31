"""Single source of truth for the product identity (used by the app, the build scripts and the installers).

Change PUBLISHER / COPYRIGHT here once; build.ps1, the MSI, Info.plist and the About box all read it.
"""

NAME = "Monkey Viewer"
APP_ID = "MonkeyViewer"                    # folder / registry / settings names
VERSION = "1.0.0"
PUBLISHER = "easy"
COPYRIGHT = "© 2026 easy. All rights reserved."
DESCRIPTION = "Viewer for specialist files: PDF & DjVu, CAD, GIS, signed & encrypted files, Lua code"
LICENSE = "Proprietary — internal use only (see LICENSE.txt)"
BUNDLE_ID = "ge.easy.monkeyviewer"         # macOS bundle identifier
UPGRADE_CODE = "{C769098C-3FD1-4A9C-84D7-A097E03D8ABB}"   # MSI upgrade code: never change once released
POLICY_KEY = r"SOFTWARE\Policies\MonkeyViewer"               # Group Policy settings (HKLM / HKCU)

try:                                    # written by the build (commit, date); absent when running from source
    from ._build_info import BUILD_COMMIT, BUILD_DATE   # type: ignore
except ImportError:
    BUILD_COMMIT, BUILD_DATE = "source", ""


def version_tuple():
    parts = [int(p) for p in VERSION.split(".")[:3]]
    return tuple(parts + [0] * (4 - len(parts)))
