<#
.SYNOPSIS
  Authenticode-sign Monkey Viewer binaries (EXE / MSI) with SHA-256 and an RFC 3161 timestamp.

.DESCRIPTION
  Use ONE of:
    -Thumbprint  a code-signing certificate already in the Windows certificate store
                 (for example issued by your Active Directory Certificate Services "Code Signing" template)
    -PfxPath / -PfxPassword  a .pfx file (CI: decoded from a GitHub secret, deleted afterwards)

.EXAMPLE
  .\packaging\windows\sign.ps1 -Thumbprint 0123ABCD... -Files dist\MonkeyViewer\MonkeyViewer.exe
#>
param(
    [Parameter(Mandatory = $true)][string[]]$Files,
    [string]$Thumbprint,
    [string]$PfxPath,
    [string]$PfxPassword,
    [string]$TimestampUrl = "http://timestamp.digicert.com"
)
$ErrorActionPreference = "Stop"

function Find-SignTool {
    $cmd = Get-Command signtool.exe -ErrorAction SilentlyContinue
    if ($cmd) { return $cmd.Source }
    $kits = Join-Path ${env:ProgramFiles(x86)} "Windows Kits\10\bin"
    $hit = Get-ChildItem -Path $kits -Recurse -Filter signtool.exe -ErrorAction SilentlyContinue |
        Where-Object { $_.FullName -match "\\x64\\" } | Sort-Object FullName -Descending | Select-Object -First 1
    if (-not $hit) { throw "signtool.exe not found - install the Windows SDK (Signing Tools)" }
    return $hit.FullName
}

$signtool = Find-SignTool
$signArgs = @("sign", "/fd", "SHA256", "/td", "SHA256", "/tr", $TimestampUrl, "/d", "Monkey Viewer")
if ($Thumbprint) {
    $signArgs += @("/sha1", $Thumbprint.Replace(" ", ""))
} elseif ($PfxPath) {
    $signArgs += @("/f", $PfxPath)
    if ($PfxPassword) { $signArgs += @("/p", $PfxPassword) }
} else {
    throw "Give -Thumbprint or -PfxPath"
}

foreach ($f in $Files) {
    & $signtool @signArgs $f
    if ($LASTEXITCODE -ne 0) { throw "signing failed: $f" }
    # /pa = default Authenticode policy; fails on machines that don't trust the issuing CA (e.g. a CI runner
    # signing with an internal AD CS certificate) - that is reported, not fatal.
    & $signtool verify /pa $f | Out-Null
    if ($LASTEXITCODE -ne 0) { Write-Warning "signature applied, but this machine does not trust the issuer: $f" }
    Write-Host "signed: $f"
}
