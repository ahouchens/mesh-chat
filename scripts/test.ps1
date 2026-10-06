$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$bundledNode = Join-Path $env:USERPROFILE ".cache\codex-runtimes\codex-primary-runtime\dependencies\node\bin\node.exe"
$node = if (Test-Path -LiteralPath $bundledNode) { $bundledNode } else { (Get-Command node -ErrorAction Stop).Source }
$python = Join-Path $repoRoot ".venv\Scripts\python.exe"

Push-Location $repoRoot
try {
    $nodeVersion = (& $node --version).TrimStart("v").Split(".")[0]
    if ([int]$nodeVersion -lt 20) { throw "Node.js 20 or newer is required." }
    & $python -m pytest ".\service\tests" -q -p no:cacheprovider --basetemp ".\.test-tmp\pytest"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $node ".\scripts\run-frontend-tests.mjs"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $node --test ".\scripts\verify_packaged_emoji_artwork.test.mjs"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $node ".\node_modules\typescript\bin\tsc" -b
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
    & $node ".\scripts\run-frontend-build.mjs"
    exit $LASTEXITCODE
} finally {
    Pop-Location
}
