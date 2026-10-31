# Monkey Viewer — აწყობა

მომხმარებლის კომპიუტერზე Python **არ არის საჭირო**: MSI/DMG შეიცავს ყველაფერს. Python 3.12 საჭიროა მხოლოდ
აწყობისთვის — GitHub-ზე (ავტომატურად) ან ერთ ადმინის კომპიუტერზე.

## A. GitHub Actions (რეკომენდებული)

1. GitHub-ზე შექმენით **private** repository (მაგ. `MonkeyViewer`) და ატვირთეთ ეს საქაღალდე:
   ```
   git init
   git add .
   git commit -m "Monkey Viewer 1.0.0"
   git branch -M main
   git remote add origin https://github.com/<თქვენი-ანგარიში>/MonkeyViewer.git
   git push -u origin main
   ```
2. Actions ჩანართზე გაეშვება **Build**: შემოწმებები → Windows MSI → macOS DMG. შედეგი — თითოეული აწყობის
   გვერდზე „Artifacts“ (windows, macos, audit-reports).
3. ოფიციალური რელიზი: `git tag v1.0.0 && git push origin v1.0.0` → Releases-ში გამოჩნდება MSI, ZIP, DMG,
   SBOM, SHA256SUMS და წყაროს კოდი. ტეგი უნდა ემთხვეოდეს `viewer/app_info.py`-ის `VERSION`-ს.

### ხელმოწერა (არასავალდებულო, მაგრამ რეკომენდებული)

Settings → Secrets and variables → Actions:

| Secret | რა არის |
|---|---|
| `WINDOWS_CERT_PFX_BASE64` | Code Signing სერტიფიკატი .pfx, base64-ით: `[Convert]::ToBase64String([IO.File]::ReadAllBytes("cert.pfx"))` |
| `WINDOWS_CERT_PASSWORD` | .pfx-ის პაროლი |
| `MACOS_CERT_P12_BASE64`, `MACOS_CERT_PASSWORD`, `MACOS_SIGN_IDENTITY` | Apple „Developer ID Application“ სერტიფიკატი |
| `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD` | Apple notarization |

**შიდა გამოყენებისთვის საუკეთესო ვარიანტი:** Active Directory Certificate Services-ის „Code Signing“ შაბლონით
გაცემული სერტიფიკატი, ხოლო GPO-ით (Computer → Policies → Windows Settings → Security Settings → Public Key
Policies → Trusted Publishers) — გამომცემლის ნდობა. მაშინ SmartScreen/AppLocker ხელმოწერას იცნობს.

## B. ადგილობრივად Windows-ზე

საჭიროა: Python 3.12 (python.org, „tcl/tk“ მონიშნული), .NET SDK 8+ (MSI-სთვის; WiX ავტომატურად დაყენდება).

```
build.bat
```
ან ხელმოწერით (სერტიფიკატი Windows-ის საცავში):
```
powershell -ExecutionPolicy Bypass -File build.ps1 -Thumbprint <სერტიფიკატის thumbprint>
```
შედეგი `release\`-ში: MSI, portable ZIP, SBOM, SHA256SUMS, selftest-windows.json.

## C. ადგილობრივად Mac-ზე

```
bash build_mac.command            # release/MonkeyViewer-<ver>-macos.dmg
bash build_mac.command --install  # + ~/Applications-ში დაყენება
```

## აწყობის ეტაპები (ყველა გზაზე ერთნაირი)

1. კომპონენტები `requirements-lock.txt`-დან, `pip --require-hashes` (ზუსტი ვერსია + SHA-256).
2. ტესტები (`pytest`), bandit, pip-audit.
3. PyInstaller (`MonkeyViewer.spec`) — ერთი აღწერა Windows-ისთვის და macOS-ისთვის; UPX გამორთულია.
4. აწყობილი პროგრამის `--self-test`.
5. ხელმოწერა (თუ სერტიფიკატი არის) → MSI (WiX 5.0.2) / DMG → ხელმოწერა → SBOM → SHA256SUMS.

## ვერსიის ან გამომცემლის შეცვლა

ყველაფერი ერთ ფაილშია: `viewer/app_info.py` (`VERSION`, `PUBLISHER`, `COPYRIGHT`, `BUNDLE_ID`).
`UPGRADE_CODE` არასდროს შეცვალოთ — მისით აახლებს MSI ძველ ვერსიას. Group Policy შაბლონების განახლება:
`python tools/gen_admx.py`. კომპონენტების განახლება: `requirements.in` → `uv pip compile requirements.in
--universal --python-version 3.12 --generate-hashes -o requirements-lock.txt`.
