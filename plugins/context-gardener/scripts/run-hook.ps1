param(
    [Parameter(Position = 0)]
    [string]$Action
)

$ErrorActionPreference = 'Stop'
$scriptPath = Join-Path $env:PLUGIN_ROOT 'skills\manage-context\scripts\context_gardener.py'
$extraArgs = @()
if ($Action) { $extraArgs += $Action }

$python = Get-Command python -ErrorAction SilentlyContinue
if ($python) {
    & $python.Source $scriptPath @extraArgs
    exit $LASTEXITCODE
}
$py = Get-Command py -ErrorAction SilentlyContinue
if ($py) {
    & $py.Source -3 $scriptPath @extraArgs
    exit $LASTEXITCODE
}
$python3 = Get-Command python3 -ErrorAction SilentlyContinue
if ($python3) {
    & $python3.Source $scriptPath @extraArgs
    exit $LASTEXITCODE
}

[Console]::Error.WriteLine('Context Gardener requires Python 3.9 or newer; hook skipped.')
exit 0
