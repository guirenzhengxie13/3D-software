param([int]$Port = 8877)
$ErrorActionPreference = 'Stop'
$workspacePath = Split-Path -Parent $PSScriptRoot
$pythonPath = Join-Path $workspacePath '.venv\Scripts\python.exe'
Write-Host "Web studio: http://127.0.0.1:$Port"
Write-Host 'Keep this terminal open. Press Ctrl+C to stop.'
Push-Location -LiteralPath $workspacePath
try { & $pythonPath (Join-Path $PSScriptRoot 'serve_web_studio.py') --port $Port }
finally { Pop-Location }
