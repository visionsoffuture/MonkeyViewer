# Monkey Viewer 1.0

**სპეციფიური ფაილების მნახველი** — ის ფაილები, რომლებსაც ოფისში მომუშავე პერსონალი ჩვეულებრივ ვერ ხსნის.
მუშაობს Windows-სა და macOS-ზე, Python-ის გარეშე; ფაილებისთვის ინტერნეტი არ სჭირდება და მონაცემს არსად აგზავნის (ერთადერთი გამონაკლისი — ამინდის პროგნოზი, რომელიც GPO-ით ითიშება).

| კატეგორია | ფორმატები |
|---|---|
| PDF & DjVu | PDF ნახვა და რედაქტირება (ტექსტი, მარკერი, ზუსტი ამოჭრა, გვერდები, შერწყმა, დაყოფა), ციფრული ხელმოწერების შემოწმება, DjVu, XPS, EPUB |
| CAD | AutoCAD DWG / DXF (შრეებით), IFC/STEP, ArchiCAD / Revit-ის preview |
| GIS | Shapefile, KML/KMZ, GPX, GeoJSON, GeoPackage, OpenStreetMap, DEM (.hgt, .asc), dBASE |
| ხელმოწერილი და დაშიფრული | .p7m (ხელმოწერის და ხელმომწერის ნდობის შემოწმება, გაშიფვრა .pfx-ით), .pfx/.p12, .cer/.pem, .gpg/.pgp, .enc/.crypto (OpenSSL), Base64/JWT |
| Lua & კოდი | Lua, Python, PowerShell, JSON, XML, SQL... — ფერადი სინტაქსი, ქართული განლაგებით მომუშავე Ctrl/⌘ ღილაკები; SVG — „SVG-ის გაშვება“ ნახატს და ანიმაციას აჩვენებს |
| მონაცემები | SQLite (მხოლოდ წაკითხვით), dBASE, Group Policy Registry.pol |
| სპეციალური სურათები | PSD, Camera RAW, HEIC, TIFF/GeoTIFF, JPEG 2000, EMF/WMF |

ყველა დოკუმენტის ბეჭდვა, ჩაშენებული კალკულატორი და საქართველოს ქალაქების ამინდის პროგნოზი (სტატუსის ზოლის კუთხეში).

Word / Excel / PowerPoint, ZIP / RAR, ელფოსტა და აუდიო/ვიდეო იხსნება თავისი პროგრამებით — Monkey Viewer მათ არ ეხება.

## დაყენება

- **Windows:** `MonkeyViewer-1.0.0-x64.msi` (ხელით ან Group Policy / Intune / SCCM — იხ. [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)).
  ინსტალაციის გარეშე: `MonkeyViewer-1.0.0-win64-portable.zip`.
- **macOS:** `MonkeyViewer-1.0.0-macos.dmg` → Applications.
- პირველ გაშვებაზე Monkey Viewer გკითხავთ, რომელი ფაილის ტიპები გაიხსნას მასში; ავტომატურად არაფერი იცვლება.

## დოკუმენტაცია

- [docs/USER_GUIDE.md](docs/USER_GUIDE.md) — მომხმარებლის მოკლე სახელმძღვანელო (თანამშრომლებისთვის)
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) — დანერგვა, Group Policy, ჩუმი ინსტალაცია
- [docs/AUDIT.md](docs/AUDIT.md) — კონტროლები და მტკიცებულებები აუდიტისთვის
- [SECURITY.md](SECURITY.md) · [PRIVACY.md](PRIVACY.md) · [CHANGELOG.md](CHANGELOG.md)
- [docs/BUILD.md](docs/BUILD.md) — აწყობა (GitHub Actions ან ადგილობრივად)
- [LICENSE.txt](LICENSE.txt) · [THIRD_PARTY_NOTICES.txt](THIRD_PARTY_NOTICES.txt)

© 2026 easy
