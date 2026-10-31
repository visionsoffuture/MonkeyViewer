# Changelog

## 1.0.0 — 2026-10-31

First release of Monkey Viewer: the same program as Lua Viewer 1.0.0 under its own name, logo, loading
animation (a small monkey with a magnifier) and file icons. It is a separate product with its own installer
identity, settings folder, Group Policy key and file-type registrations, so it can be installed next to
Lua Viewer on the same computer without either one touching the other.

### What Monkey Viewer does
- **PDF:** view, edit text, highlight, draw, white-out, insert images / signatures, precise crop (millimetre
  margins, arrow keys, selected pages), page operations (rotate, copy, move, extract, split, merge), save pages
  as images; verify digital signatures (PAdES, CMS, document timestamps, legacy adbe.x509.rsa_sha1) with a
  signature panel and an operating-system trust check.
- **DjVu, XPS, EPUB, MOBI, FB2, CBZ, DWFx** as read-only documents (DjVuLibre bundled).
- **CAD:** DWG (LibreDWG bundled) and DXF with layers, layouts and light / dark background; IFC / STEP as text.
- **GIS:** Shapefile, GeoJSON, KML / KMZ, GPX, GeoPackage, OpenStreetMap, SRTM / ASCII grids, dBASE; layers with
  colours, attribute table, PNG export.
- **Signed & encrypted files:** .p7m / .p7s, certificates and keys, PGP / GnuPG (bundled), OpenSSL .enc,
  age, Ansible Vault, KeePass, Base64 / JWT - analysed, verified and, where allowed, decrypted.
- **Code:** Lua and 120+ text and code formats with syntax colours that work on any keyboard layout;
  **Run SVG** draws an SVG and plays its SMIL / CSS animation.
- **Data and images:** SQLite (read-only), Group Policy Registry.pol, PSD, Camera RAW, HEIC / AVIF, TIFF /
  GeoTIFF, JPEG 2000, EMF / WMF.
- **Everywhere:** menu bar with each file type's own menu, the ☰ app menu, printing for every document,
  a built-in calculator (Ctrl+Shift+K), the weather of Georgian cities in the status bar corner (MET Norway),
  Georgian and English interface, light / dark theme, works in small windows.

### For administrators
- MSI for Windows 10 / 11 (per-machine, Group Policy / Intune / SCCM, silent installs never restart; an
  interactive install or removal offers a restart at the end), DMG for macOS.
- Group Policy (ADMX): view-only, no printing, no decryption, no helper programs, file associations,
  interface language, audit log options, and "Turn off the weather forecast" - the only internet connection.
- Audit log (local, central file or Windows event log), error and freeze logs for support, self-test
  (`--self-test`), SBOM and checksums with every release.
