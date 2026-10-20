param(
    [string]$Python = 'python',
    [switch]$CoreOnly
)
$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$env:PYTHONUTF8 = '1'
$env:PIP_CACHE_DIR = Join-Path $projectRoot '.cache\pip'
$venvPython = Join-Path $projectRoot '.venv\Scripts\python.exe'
Push-Location $projectRoot
try {
    if (-not (Test-Path -LiteralPath $venvPython)) {
        & $Python -c "import sys; assert sys.version_info >= (3, 10), 'Python 3.10+ required'; assert sys.maxsize > 2**32, '64-bit Python required'"
        if ($LASTEXITCODE -ne 0) { throw 'Python version check failed.' }
        & $Python -m venv .venv
        if ($LASTEXITCODE -ne 0) { throw 'Virtual environment creation failed.' }
    }
    $installTarget = if ($CoreOnly) { '.' } else { '.[viewer]' }
    & $venvPython -m pip install --disable-pip-version-check -e $installTarget
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $venvPython -m pip check
    if ($LASTEXITCODE -ne 0) { throw 'Dependency check failed.' }
    Write-Host 'Environment ready. See README.md for demo and replay commands.'
} finally {
    Pop-Location
}
