# Monkey Viewer 1.0 — აუდიტის მასალა

ეს დოკუმენტი აუდიტორისთვისაა: რა მოთხოვნას რა კონტროლი პასუხობს და სად არის მისი მტკიცებულება.
ცხრილი გამოსადეგია ISO/IEC 27001:2022 Annex A-ს და მსგავსი ჩარჩოების შეფასებისას. Monkey Viewer
სერტიფიცირებული არ არის — ის აწვდის კონტროლებს და მტკიცებულებებს, რომლებიც ასეთ შეფასებას სჭირდება.

## 1. პროდუქტის იდენტიფიკაცია

| | |
|---|---|
| პროდუქტი | Monkey Viewer 1.0.0 |
| გამომცემელი | easy |
| დანიშნულება | სპეციფიური ფაილების ნახვა: PDF (რედაქტირებით) და DjVu, CAD, GIS, SVG, ხელმოწერილი / დაშიფრული ფაილები, Lua კოდი, SQLite / dBASE / Registry.pol, სპეციალური გამოსახულებები |
| პლატფორმა | Windows 10/11 x64 (MSI, per-machine), macOS 11+ (DMG) |
| ლიცენზია | შიდა გამოყენება (LICENSE.txt); მესამე მხარის კომპონენტები — THIRD_PARTY_NOTICES.txt |
| ქსელი | ფაილებისთვის არ საჭიროებს; ტელემეტრია არ აქვს. ერთადერთი კავშირი — ამინდი: HTTPS `api.met.no`, იგზავნება მხოლოდ არჩეული ქალაქის კოორდინატები, არაუმეტეს 30 წუთში ერთხელ; GPO „Turn off the weather forecast“ სრულად თიშავს |
| ადმინის უფლება | მხოლოდ ინსტალაციისას (MSI); მუშაობისას — არა |

## 2. კონტროლები და მტკიცებულებები

| # | მოთხოვნა (ISO/IEC 27001:2022) | კონტროლი Monkey Viewer-ში | მტკიცებულება |
|---|---|---|---|
| 1 | უსაფრთხო განვითარება (A.8.25, A.8.28) | შეყვანილი ფაილი არასანდოა: defusedxml, read-only SQLite, sidecar გზების შეზღუდვა, უსაფრთხო ფაილის სახელები | `viewer/safeio.py`; ტესტები `tests/test_security.py` |
| 2 | კოდის შესრულების აკრძალვა (A.8.7) | პროგრამები/სკრიპტები არ ეშვება; მხოლოდ http/https/mailto | `safeio.is_dangerous`, `winutil.open_external/open_url`; ტესტები `test_programs_are_never_launched`, `test_only_web_links_open` |
| 3 | სტატიკური ანალიზი (A.8.28) | bandit ყოველ აწყობაზე, 0 მიგნება; გამონაკლისები დასაბუთებულია კოდში (`# nosec` + კომენტარი) და `pyproject.toml`-ში | CI ნაბიჯი „Bandit“, არტეფაქტი `bandit-report.txt` |
| 4 | ტესტირება (A.8.29) | 90+ ავტომატური ტესტი; აწყობილი პროგრამის თვითშემოწმება (`--self-test`) Windows-სა და macOS-ზე | `tests/`; CI ნაბიჯები „Tests“, „Self test of the frozen program“; `selftest-*.json` რელიზში |
| 5 | ტექნიკური მოწყვლადობები (A.8.8) | ფიქსირებული ვერსიები SHA-256 ჰეშებით; pip-audit ყოველ აწყობაზე | `requirements-lock.txt`; CI ნაბიჯი „pip-audit“ |
| 6 | მიწოდების ჯაჭვი (A.5.19–A.5.23) | SBOM (CycloneDX 1.6); GitHub Actions მიბმული commit SHA-ზე; წყაროს კოდის არქივი | `MonkeyViewer-*-sbom.cdx.json`; `.github/workflows/build.yml` |
| 7 | მთლიანობა (A.8.24, A.8.32) | SHA256SUMS ყოველ რელიზზე; Authenticode / Developer ID ხელმოწერა (სერტიფიკატის არსებობისას) | `SHA256SUMS.txt`; `packaging/windows/sign.ps1` |
| 8 | ჟურნალირება (A.8.15) | აუდიტის JSON Lines: გახსნა, შენახვა, ექსპორტი, გაშიფვრა, ხელმოწერის/ნდობის შემოწმება, ასოციაციები, აპლიკაციის ჩართვა/გამორთვა; Event Log და ცენტრალური ფაილი პოლიტიკით | `viewer/audit.py`; ტესტები `test_audit_*` |
| 9 | საიდუმლოების დაცვა (A.8.24) | პაროლი არ იწერება დისკზე/ჟურნალში/ბრძანების ხაზზე; ჟურნალი ფილტრავს password/passphrase/secret ველებს | `audit._SECRET_KEYS`; `crypto.decrypt_gpg` (`--passphrase-fd 0`); ტესტი `test_audit_log_records_and_hides_secrets` |
| 10 | მონაცემის წაშლა (A.8.10) | გაშიფრული შედეგები მხოლოდ სესიის პირად დროებით საქაღალდეში, დახურვისას იშლება; დარჩენილი იწმინდება | `safeio.session_dir/cleanup_*`; ტესტი `test_session_temp_is_private_and_removed` |
| 11 | ცენტრალური მართვა (A.8.9) | Group Policy (ADMX/ADML ka-GE/en-US), macOS კონფიგურაციის პროფილი | `deploy/admx`, `deploy/macos`; ტესტი `test_admx_matches_policy_definitions` |
| 12 | პროგრამების ინსტალაცია (A.8.19) | per-machine MSI Program Files-ში, MajorUpgrade, GPO/Intune/SCCM; ჩუმი ინსტალაცია | `packaging/windows/make_wxs.py`; docs/DEPLOYMENT.md |
| 13 | მინიმალური ცვლილება სისტემაში | ფაილის ტიპებს თავისით არ იკავებს; მომხმარებლის არჩევანი HKCU-ში, ძველის აღდგენით; 3.x-ის დანატოვარის გაწმენდა | `winutil.apply_associations`, `_cleanup_legacy` |
| 14 | ინტელექტუალური საკუთრება (A.5.32) | ყველა კომპონენტის ლიცენზია ჩამოთვლილი და ტექსტები დაყენებული `licenses/`-ში; AGPL-ის ვალდებულებები აღწერილი | `THIRD_PARTY_NOTICES.txt`, `LICENSE.txt`, `MonkeyViewer.spec` |
| 15 | კონფიდენციალურობა (A.5.34) | ლოკალური მუშაობა, ტელემეტრიის გარეშე; შენახული მონაცემების სია და ვადები | `PRIVACY.md` |
| 16 | წვდომის შეზღუდვა (A.8.3) | მხოლოდ-ნახვის რეჟიმი, გაშიფვრის აკრძალვა, დამხმარე პროგრამების აკრძალვა — პოლიტიკით | `viewer/policy.py`; ტესტი `test_read_only_policy_blocks_saving` |

## 3. როგორ გადაამოწმოს აუდიტორმა

1. **ფაილის მთლიანობა:** `Get-FileHash <file> -Algorithm SHA256` = `SHA256SUMS.txt`-ის მნიშვნელობა.
2. **აწყობის ჟურნალი:** GitHub → Actions → Build — ყველა ნაბიჯი (ტესტები, bandit, pip-audit, self-test) ჩანს
   ცალ-ცალკე; არტეფაქტები შეიცავს `bandit-report.txt`-ს და `selftest-*.json`-ს.
3. **კომპონენტები:** SBOM (`*.sbom.cdx.json`) — ნებისმიერ SCA ინსტრუმენტში (Dependency-Track და სხვ.).
4. **დაყენებული პროგრამის შემოწმება:**
   `"C:\Program Files\Monkey Viewer\MonkeyViewer.exe" --self-test=C:\Temp\lv.json` (გამოსვლის კოდი 0).
5. **ჟურნალი** (მომხმარებლის მენიუში არ ჩანს — მხოლოდ ადმინისტრატორისთვის): `%APPDATA%\MonkeyViewer\audit.log`, შეცდომები `error.log`, გაყინვები `hang.log`; ან Event Viewer → Windows Logs → Application → წყარო `MonkeyViewer`.
6. **ქსელის შემოწმება:** Monkey Viewer-ის მუშაობისას `Get-NetTCPConnection -OwningProcess (Get-Process MonkeyViewer).Id`
   აჩვენებს 127.0.0.1-ზე მოსმენას (ერთი ფანჯრის რეჟიმი) და, ამინდის ჩართვისას, დროებით HTTPS კავშირს
   `api.met.no`-სთან. სხვა მისამართი არ უნდა ჩანდეს.

## 4. აუდიტის მოვლენები

| action | როდის | ველები |
|---|---|---|
| `app_start` / `app_exit` | ჩართვა / დახურვა | `frozen`, `build`, `policies` |
| `file_open` | ფაილის გახსნა | `path`, `viewer`, `size`, `sha256` (პოლიტიკით) |
| `file_save` | შენახვა | `path`, `source`, `viewer` |
| `export` | ექსპორტი / შენახვის დიალოგი | `path`, `dialog` / `what` |
| `decrypt` | გაშიფვრა (წარმატება / წარუმატებლობა) | `path`, `method`, `result`, `output` / `reason` |
| `signature` | ხელმოწერის / ნდობის შემოწმება | `path`, `result`, `signer`, `signed`, `check` |
| `open_external` | სისტემის პროგრამაში გახსნა | `path` |
| `settings` | ინტერფეისის ენის შეცვლა | `language` |

ყოველ ჩანაწერს აქვს `time` (UTC, ISO 8601), `user` (DOMAIN\user), `computer`, `app` (ვერსია), `pid`.
Event Log-ის ID-ები: 1000 start, 1001 open, 1002 save, 1003 export, 1004 decrypt, 1005 signature,
1006 associations, 1007 open external, 1009 exit, 1010 blocked, 1011 settings (ენის შეცვლა), 1012 hang (გაყინვა), 1013 print (ბეჭდვა) (გაფრთხილება — წარუმატებელი გაშიფვრა / გაფუჭებული ხელმოწერა).

## 5. ცნობილი შეზღუდვები

- ხელმოწერის „Intact“ ამოწმებს მხოლოდ მთლიანობას; ხელმომწერის ნდობას ამოწმებს „Check trust“ (Windows CryptoAPI /
  macOS Security), რომელიც სერტიფიკატში მითითებულ CRL/OCSP-ს შეიძლება მიმართოს.
- ხელმოწერის (Authenticode / Developer ID) გარეშე Windows SmartScreen და macOS Gatekeeper გააფრთხილებენ.
  ორგანიზაციის შიგნით გამოსავალია AD CS-ის Code Signing სერტიფიკატი + GPO-ით ნდობა.
- DjVu, GnuPG და DWG საჭიროებს ცალკე დაყენებულ უფასო პროგრამებს (DjVuLibre, Gpg4win, ODA File Converter).
