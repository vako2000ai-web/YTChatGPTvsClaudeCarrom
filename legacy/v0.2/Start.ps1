$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (!(Test-Path -LiteralPath $taskPython)) { throw 'Run Setup.ps1 first.' }
& $taskPython (Join-Path $PSScriptRoot 'game.py') @args
exit $LASTEXITCODE
