@echo off
cd /d "%~dp0"
if "%~1"=="" (
  echo Drag a .replay.jsonl.gz file onto this shortcut.
  pause
  exit /b 1
)
set "CARROM_EXE=%~dp0CarromAIShowdown.exe"
if not exist "%CARROM_EXE%" set "CARROM_EXE=%~dp0dist\CarromAIShowdown\CarromAIShowdown.exe"
start "" "%CARROM_EXE%" --replay "%~1"
