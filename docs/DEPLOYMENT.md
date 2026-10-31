# Monkey Viewer — დანერგვა ორგანიზაციაში

## 1. ფაილები, რომლებიც რელიზს მოყვება

| ფაილი | დანიშნულება |
|---|---|
| `MonkeyViewer-1.0.0-x64.msi` | Windows 10/11 (x64) ინსტალატორი — ყველა მომხმარებლისთვის, Program Files-ში |
| `MonkeyViewer-1.0.0-win64-portable.zip` | ინსტალაციის გარეშე (ადმინის უფლება არ სჭირდება) |
| `MonkeyViewer-1.0.0-macos.dmg` | macOS 11+ (Apple Silicon / Intel აწყობის მიხედვით) |
| `MonkeyViewer-1.0.0-sbom.cdx.json` | კომპონენტების სია (SBOM, CycloneDX 1.6) |
| `SHA256SUMS.txt` | ყველა ფაილის SHA-256 — გავრცელებამდე შეამოწმეთ |
| `MonkeyViewer-v1.0.0-source.zip` | წყაროს კოდი |

ჰეშის შემოწმება: `Get-FileHash .\MonkeyViewer-1.0.0-x64.msi -Algorithm SHA256` და შეადარეთ `SHA256SUMS.txt`-ს.
ხელმოწერის შემოწმება (თუ ხელმოწერილია): ფაილზე მარჯვენა ღილაკი → Properties → Digital Signatures.

## 2. Windows — ინსტალაცია

**ხელით:** ორჯერ დააწკაპეთ MSI-ზე → Next → ლიცენზიის დათანხმება → საქაღალდე (ნაგულისხმევად
`C:\Program Files\Monkey Viewer`) → Install. საჭიროა ადმინისტრატორის უფლება. იქმნება მალსახმობი Desktop-ზე და Start-ში.
ბოლოს Windows გთავაზობთ კომპიუტერის გადატვირთვას (Yes — ახლავე, No — მოგვიანებით); იგივე ხდება ხელით წაშლისას.

**ჩუმად (სკრიპტი / Intune / SCCM):**
```
msiexec /i MonkeyViewer-1.0.0-x64.msi /qn /l*v C:\Windows\Temp\MonkeyViewer-install.log
```
წაშლა: `msiexec /x MonkeyViewer-1.0.0-x64.msi /qn` ან Settings → Apps.
ჩუმი ინსტალაცია / წაშლა (`/qn`, GPO, Intune, SCCM) კომპიუტერს **არასოდეს** გადატვირთავს. ხელით გაშვებისასაც თუ არ
გინდათ შეთავაზება: `msiexec /i MonkeyViewer-1.0.0-x64.msi REBOOT=ReallySuppress`.

**Group Policy (Software Installation):**
1. MSI დადეთ ქსელურ საქაღალდეში, რომელზეც `Domain Computers`-ს აქვს Read, მაგ. `\\water.local\NETLOGON\Software\MonkeyViewer\`.
2. GPMC → ახალი GPO → Computer Configuration → Policies → Software Settings → Software installation →
   New → Package → აირჩიეთ MSI **UNC გზით** → Assigned.
3. GPO მიაბით სასურველ OU-ს. დაყენდება კომპიუტერის შემდეგ გადატვირთვაზე.
4. ახალი ვერსია: დაამატეთ ახალი MSI იმავე GPO-ში და Upgrades ჩანართზე მიუთითეთ ძველი — ან უბრალოდ
   ჩაანაცვლეთ (MSI-ს MajorUpgrade ძველ ვერსიას თავისით წაშლის; UpgradeCode უცვლელია).

**Lua Viewer-თან ერთად:** Monkey Viewer ცალკე პროდუქტია — საკუთარი MSI იდენტიფიკატორით (UpgradeCode), პარამეტრების
საქაღალდით (`%APPDATA%\MonkeyViewer`), Group Policy გასაღებით (`SOFTWARE\Policies\MonkeyViewer`) და ფაილის ტიპების
რეგისტრაციით (`MonkeyViewer.*`). ერთ კომპიუტერზე ორივე პროგრამა შეიძლება იყოს დაყენებული; Monkey Viewer-ის დაყენება ან
წაშლა Lua Viewer-ს არ ეხება და პირიქით.

## 3. Group Policy პარამეტრები (ADMX)

1. `Admin\admx\MonkeyViewer.admx` (ინსტალაციის საქაღალდეში ან რელიზში) დააკოპირეთ
   `\\water.local\SYSVOL\water.local\Policies\PolicyDefinitions\`-ში.
2. `en-US\MonkeyViewer.adml` და `ka-GE\MonkeyViewer.adml` — შესაბამის ენის საქაღალდეებში.
3. GPMC: Computer ან User Configuration → Administrative Templates → **Monkey Viewer**.

| პოლიტიკა | რას აკეთებს |
|---|---|
| Don't ask users to choose file types | პირველ გაშვებაზე ფაილის ტიპების ფანჯარა არ ჩნდება |
| Prevent users from changing file associations | მომხმარებელი ვერ ცვლის მიბმებს |
| Don't start helper programs | GnuPG / DjVuLibre / ODA არ ეშვება |
| Don't decrypt files | დაშიფრული ფაილი მხოლოდ აღიწერება, არ იშიფრება |
| View-only mode | შენახვა და ექსპორტი დაბლოკილია |
| Turn off printing | ბეჭდვა (ფაილი → ბეჭდვა, Ctrl+P) დაბლოკილია |
| Turn off the weather forecast | ამინდი არ ჩანს და პროგრამა ინტერნეტს საერთოდ არ უკავშირდება |
| Turn off the local audit log | ლოკალური `audit.log` არ იწერება |
| Write audit events to the Windows event log | აუდიტი Application log-შიც (წყარო `MonkeyViewer`) |
| Additional audit log file | აუდიტის ასლი ცენტრალურ ფაილში, მაგ. `\\server\audit$\MonkeyViewer\%USERNAME%.jsonl` |
| Record file hashes in the audit log | გახსნილი ფაილების SHA-256 |
| Interface language | ინტერფეისის ენა ყველასთვის: ქართული ან English (მომხმარებელი ვეღარ ცვლის) |

კომპიუტერის პოლიტიკა (HKLM) უპირატესია მომხმარებლის პოლიტიკაზე (HKCU). რეესტრი:
`HKLM\SOFTWARE\Policies\MonkeyViewer` (DWORD 1 = ჩართული; `AuditLogPath` — REG_EXPAND_SZ; `Language` — REG_SZ
`ka` ან `en`).

ცენტრალური ჟურნალის საქაღალდისთვის მომხმარებლებს მიეცით მხოლოდ **ჩაწერის/დამატების** უფლება, წაკითხვის გარეშე.

## 4. ინტერფეისის ენა

Monkey Viewer-ს აქვს ქართული და ინგლისური ინტერფეისი. ნაგულისხმევად ენა Windows-ის / macOS-ის ენას მიჰყვება;
მომხმარებელს შეუძლია შეცვალოს: **⋯ (მეტი) → ენა** (ცვლილება მოქმედებს შემდეგ გახსნაზე). ორგანიზაციისთვის
ერთიანი ენა: პოლიტიკა „Interface language“ (Windows) ან `Language` გასაღები mobileconfig-ში (macOS).

## 5. ფაილის ტიპები ცენტრალურად

Monkey Viewer თავისით არაფერს უკავშირებს. ცენტრალური მიბმისთვის გამოიყენეთ Windows-ის სტანდარტული
DISM მეთოდი (Default App Associations XML) და პოლიტიკა „Don't ask users to choose file types“.
ProgID-ები (თითოეულს საკუთარი ხატულა აქვს): `MonkeyViewer.pdf`, `MonkeyViewer.djvu`, `MonkeyViewer.cad`, `MonkeyViewer.gis`, `MonkeyViewer.model`, `MonkeyViewer.secure`,
`MonkeyViewer.code`, `MonkeyViewer.lua`, `MonkeyViewer.data`, `MonkeyViewer.image`.

## 6. macOS

DMG-დან `Monkey Viewer.app` გადაიტანეთ Applications-ში. ხელმოუწერელ ვერსიაზე პირველად: მარჯვენა ღილაკი → Open
(ან System Settings → Privacy & Security → Open Anyway). პოლიტიკები: `deploy/macos/MonkeyViewer-policies.mobileconfig`
MDM-ით (Jamf, Intune...) — bundle id `ge.easy.monkeyviewer`.

## 7. შემოწმება დანერგვის შემდეგ

```
"C:\Program Files\Monkey Viewer\MonkeyViewer.exe" --self-test=%TEMP%\monkeyviewer-selftest.json
```
გამოსვლის კოდი 0 = ყველა ძრავი მუშაობს; ანგარიში JSON ფაილშია. პროგრამიდან: ⋯ → კომპონენტები და დიაგნოსტიკა (Components & diagnostics).
