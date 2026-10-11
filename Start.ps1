$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Run Setup.ps1 first.' }
if ($args.Count -eq 0) {
    & $taskPython (Join-Path $PSScriptRoot 'game.py') --official-match
} else {
    & $taskPython (Join-Path $PSScriptRoot 'game.py') @args
}
exit $LASTEXITCODE
