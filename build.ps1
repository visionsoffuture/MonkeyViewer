<#
.SYNOPSIS
  Build Monkey Viewer for Windows: tests, standalone program, self test, MSI installer, portable ZIP, SBOM,
  SHA-256 checksums. Python is needed only on this build machine - never on the users' computers.

.PARAMETER Thumbprint
  Optional: thumbprint of a code-signing certificate in your certificate store (e.g. from AD CS).

.PARAMETER SkipTests
  Skip the automated tests (not recommended).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File build.ps1
  powershell -ExecutionPolicy Bypass -File build.ps1 -Thumbprint 0123456789ABCDEF...
#>
param([string]$Thumbprint, [switch]$SkipTests)
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath $PSScriptRoot
$WixVersion = "5.0.2"

function Step($n, $text) { Write-Host ""; Write-Host "[$n] $text" -ForegroundColor Cyan }
function Run($exe, [string[]]$argv) {
    & $exe @argv
    if ($LASTEXITCODE -ne 0) { throw "$exe $($argv -join ' ') failed ($LASTEXITCODE)" }
}

Step 1 "Python 3.12 build environment"
$pyExe = $null; $pyPre = @()
foreach ($cand in @(@("py", "-3.12"), @("python"))) {
    $exe = $cand[0]; $pre = @($cand | Select-Object -Skip 1)
    if (-not (Get-Command $exe -ErrorAction SilentlyContinue)) { continue }
    $v = & $exe @pre -c "import sys, tkinter; print('%d.%d' % sys.version_info[:2])" 2>$null
    if ($LASTEXITCODE -eq 0 -and "$v".Trim() -eq "3.12") { $pyExe = $exe; $pyPre = $pre; break }
}
if (-not $pyExe) { throw "Python 3.12 (python.org, with tcl/tk) is required on the build machine." }
if (-not (Test-Path ".build-venv\Scripts\python.exe")) { Run $pyExe ($pyPre + @("-m", "venv", ".build-venv")) }
$vpy = (Resolve-Path ".build-venv\Scripts\python.exe").Path
Run $vpy @("-m", "pip", "install", "--quiet", "--upgrade", "pip")
Run $vpy @("-m", "pip", "install", "--quiet", "--require-hashes", "-r", "requirements-lock.txt")
Run $vpy @("-m", "pip", "install", "--quiet", "--require-hashes", "-r", "requirements-dev-lock.txt")

if (-not $SkipTests) {
    Step 2 "Tests, static analysis, dependency audit"
    Run $vpy @("-m", "pytest", "-q")
    Run $vpy @("-m", "bandit", "-q", "-c", "pyproject.toml", "-r", "viewer", "monkey_viewer.py", "tools", "packaging")
    Run $vpy @("-m", "pip_audit", "--strict", "--require-hashes", "--disable-pip", "-r", "requirements-lock.txt")
}

Step 3 "Helper programs (DjVuLibre, LibreDWG) and standalone program (PyInstaller)"
try { & "$PSScriptRoot\packaging\windows\fetch_helpers.ps1" }
catch { Write-Warning "Helper programs not bundled ($_) - DjVu and DWG will need them installed separately." }
Run $vpy @("tools\write_build_info.py")
Run $vpy @("-m", "PyInstaller", "MonkeyViewer.spec", "--noconfirm", "--clean")
$version = & $vpy -c "from viewer import app_info; print(app_info.VERSION)"
New-Item -ItemType Directory -Force -Path release | Out-Null

Step 4 "Self test of the built program"
$report = Join-Path $PWD "release\selftest-windows.json"
$p = Start-Process -FilePath "dist\MonkeyViewer\MonkeyViewer.exe" -ArgumentList "--self-test=`"$report`"" -Wait -PassThru
Get-Content $report | Write-Host
if ($p.ExitCode -ne 0) { throw "self test failed" }

if ($Thumbprint) {
    Step 5 "Signing the program"
    & "$PSScriptRoot\packaging\windows\sign.ps1" -Thumbprint $Thumbprint -Files "dist\MonkeyViewer\MonkeyViewer.exe"
}

Step 6 "MSI installer (WiX $WixVersion)"
$wix = Get-Command wix -ErrorAction SilentlyContinue
if (-not $wix -and (Get-Command dotnet -ErrorAction SilentlyContinue)) {
    Run "dotnet" @("tool", "install", "--global", "wix", "--version", $WixVersion)
    $env:PATH += ";$env:USERPROFILE\.dotnet\tools"
    $wix = Get-Command wix -ErrorAction SilentlyContinue
}
$msi = "release\MonkeyViewer-$version-x64.msi"
if ($wix) {
    & wix extension add -g "WixToolset.UI.wixext/$WixVersion" | Out-Null
    Run $vpy @("packaging\windows\make_wxs.py", "--src", "dist\MonkeyViewer", "--out", "build\msi")
    Run "wix" @("build", "build\msi\MonkeyViewer.wxs", "-arch", "x64", "-ext", "WixToolset.UI.wixext", "-o", $msi)
    if ($Thumbprint) { & "$PSScriptRoot\packaging\windows\sign.ps1" -Thumbprint $Thumbprint -Files $msi }
} else {
    Write-Warning "WiX needs the .NET SDK (https://dotnet.microsoft.com) - MSI skipped, portable ZIP only."
}

Step 7 "Portable ZIP, SBOM, checksums"
$zip = "release\MonkeyViewer-$version-win64-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path "dist\MonkeyViewer\*" -DestinationPath $zip
Run $vpy @("-m", "cyclonedx_py", "requirements", "requirements-lock.txt", "--output-format", "JSON",
           "--output-file", "release\MonkeyViewer-$version-sbom.cdx.json")
Get-ChildItem release -File | Where-Object { $_.Name -ne "SHA256SUMS.txt" } | ForEach-Object {
    "{0}  {1}" -f (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLower(), $_.Name
} | Set-Content -Encoding ascii release\SHA256SUMS.txt

Write-Host ""
Write-Host "Done. Files in .\release:" -ForegroundColor Green
Get-ChildItem release | Format-Table Name, Length -AutoSize
