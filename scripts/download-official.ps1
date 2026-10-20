param([string]$Python)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$downloadRoot = Join-Path $projectRoot 'downloads'
New-Item -ItemType Directory -Path $downloadRoot -Force | Out-Null
$env:PYTHONUTF8 = '1'
if (-not $Python) { $Python = Join-Path $projectRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $Python)) { throw 'Run setup.ps1 first or provide -Python with a Python executable path.' }
& $Python (Join-Path $PSScriptRoot 'download_official.py')
if ($LASTEXITCODE -ne 0) { throw 'Official software download failed.' }
$manifest = Get-Content -LiteralPath (Join-Path $downloadRoot 'manifest.json') -Raw | ConvertFrom-Json
foreach ($item in $manifest) {
    $item.checked_utc = (Get-Date).ToUniversalTime().ToString('o')
    $destination = Join-Path $downloadRoot $item.name
    if ($destination.EndsWith('.exe')) {
        $signature = Get-AuthenticodeSignature -LiteralPath $destination
        $item | Add-Member -NotePropertyName signature_status -NotePropertyValue ([string]$signature.Status) -Force
        $signer = if ($signature.SignerCertificate) { $signature.SignerCertificate.Subject } else { $null }
        $item | Add-Member -NotePropertyName signer -NotePropertyValue $signer -Force
    }
}
$manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $downloadRoot 'manifest.json') -Encoding utf8
$manifest | Format-Table name,bytes,signature_status -AutoSize
