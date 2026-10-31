<#
.SYNOPSIS
  Fetch the helper programs Monkey Viewer ships with, verified against pinned SHA-256 checksums:
    DjVuLibre 3.5.29 (ddjvu - DjVu pages)   GPL-2.0   https://djvu.sourceforge.net
    LibreDWG 0.13.3  (dwg2dxf - DWG files)  GPL-3.0   https://www.gnu.org/software/libredwg
    GnuPG 2.5.21     (gpg - .gpg / .pgp)    GPL-3.0   https://gnupg.org
  They are separate programs started by Monkey Viewer (not linked into it); their licences are bundled.
  Result: build\vendor\djvulibre, \libredwg and \gnupg (picked up by MonkeyViewer.spec).
#>
$ErrorActionPreference = "Stop"
Set-Location -LiteralPath (Split-Path -Parent (Split-Path -Parent $PSScriptRoot))
$v = "build\vendor"; New-Item -ItemType Directory -Force $v | Out-Null
function Get-Verified($url, $file, $sha) {
  Invoke-WebRequest -Uri $url -OutFile $file -UseBasicParsing -UserAgent "Wget"
  $h = (Get-FileHash $file -Algorithm SHA256).Hash
  if ($h -ne $sha) { throw "checksum mismatch for $url : $h" }
}
Get-Verified "https://github.com/LibreDWG/libredwg/releases/download/0.13.3/libredwg-0.13.3-win64.zip" `
  "$v\libredwg.zip" "B5133F8B6BD71B7E682A06EF5F99C93B40D628A791C30A31924A80D258C87173"
Expand-Archive "$v\libredwg.zip" "$v\libredwg-full" -Force
New-Item -ItemType Directory -Force "$v\libredwg" | Out-Null
Copy-Item "$v\libredwg-full\dwg2dxf.exe", "$v\libredwg-full\libredwg-0.dll", "$v\libredwg-full\libiconv-2.dll" "$v\libredwg\"
Copy-Item "$v\libredwg-full\README.txt" "$v\libredwg\README-LibreDWG.txt"
Get-Verified "https://downloads.sourceforge.net/project/djvu/DjVuLibre_Windows/3.5.29%2B4.12/DjVuLibre-3.5.29_DjView-4.12_Setup.exe" `
  "$v\djvulibre-setup.exe" "92233FBF891C63F3FB7A0B5E1CE108BAA4C29A40C89A442D1313F883AAE84670"
$tmp = Join-Path $env:TEMP "DjVuLibreTmp"
function Expand-Installer($exe, $dest) {
    if (Test-Path $dest) { Remove-Item $dest -Recurse -Force }
    $7z = Get-Command 7z -ErrorAction SilentlyContinue
    if (-not $7z -and (Test-Path "$env:ProgramFiles\7-Zip\7z.exe")) { $7z = Get-Command "$env:ProgramFiles\7-Zip\7z.exe" }
    if ($7z) {   # unpack the installer without installing anything
        & $7z.Source x -y "-o$dest" $exe | Out-Null
    } else {     # silent install into a temporary folder
        Start-Process $exe -ArgumentList "/S", "/D=$dest" -Wait
    }
}
Expand-Installer "$v\djvulibre-setup.exe" $tmp
$dd = Get-ChildItem $tmp -Recurse -Filter ddjvu.exe | Select-Object -First 1
if (-not $dd) { throw "ddjvu.exe not found after installing DjVuLibre" }
New-Item -ItemType Directory -Force "$v\djvulibre" | Out-Null
Copy-Item $dd.FullName "$v\djvulibre\"
Get-ChildItem $dd.DirectoryName -Filter *.dll | Where-Object { $_.Name -notlike "Qt*" } | Copy-Item -Destination "$v\djvulibre\"
Get-ChildItem $tmp -Recurse -Filter "COPYING*" | Select-Object -First 1 | Copy-Item -Destination "$v\djvulibre\COPYING-DjVuLibre.txt"
Get-ChildItem "$v\djvulibre", "$v\libredwg" | Format-Table Name, Length
& "$v\libredwg\dwg2dxf.exe" --version

Get-Verified "https://gnupg.org/ftp/gcrypt/binary/gnupg-w32-2.5.21_20260702.exe" `
  "$v\gnupg-setup.exe" "6246C925A73167253444AFC24A0DEB83A3F43B7D636AF84D6AAF48A98A62F024"
$gtmp = Join-Path $env:TEMP "GnuPGTmp"
Expand-Installer "$v\gnupg-setup.exe" $gtmp
$gpg = Get-ChildItem $gtmp -Recurse -Filter gpg.exe | Select-Object -First 1
if (-not $gpg) { throw "gpg.exe not found in the GnuPG installer" }
$groot = Split-Path -Parent $gpg.DirectoryName           # keep the bin\ share\ layout GnuPG expects
if (Test-Path "$v\gnupg") { Remove-Item "$v\gnupg" -Recurse -Force }
New-Item -ItemType Directory -Force "$v\gnupg" | Out-Null
Get-ChildItem $groot | Where-Object { $_.Name -notlike '$*' -and $_.Name -notlike "*uninst*" } |
    Copy-Item -Destination "$v\gnupg\" -Recurse
& "$v\gnupg\bin\gpg.exe" --version
$global:LASTEXITCODE = 0
