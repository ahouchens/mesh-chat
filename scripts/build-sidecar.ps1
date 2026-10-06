param(
    [string]$TargetTriple = "x86_64-pc-windows-msvc"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Create the repository virtual environment and install service/requirements-dev.lock first."
}

& $python (Join-Path $PSScriptRoot "build_sidecar.py") --target-triple $TargetTriple
exit $LASTEXITCODE
