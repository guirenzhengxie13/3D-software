param([string]$DllPath = '')
$ErrorActionPreference = 'Stop'
$executable = Join-Path $PSScriptRoot 'build/public_sdk_probe.exe'
if (-not (Test-Path -LiteralPath $executable -PathType Leaf)) {
    throw 'Build the probe first: .\native_probe\build.cmd'
}
if (-not $DllPath) {
    $DllPath = Join-Path $PSScriptRoot '../vendor/public-3dviewer-reference/thirdparty/3DCamera/windows/x64/3DCamera.dll'
}
$resolvedDll = (Resolve-Path -LiteralPath $DllPath).Path
& $executable $resolvedDll
exit $LASTEXITCODE
