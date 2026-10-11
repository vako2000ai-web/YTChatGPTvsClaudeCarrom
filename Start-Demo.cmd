@echo off
cd /d "%~dp0"
set "CARROM_EXE=%~dp0CarromAIShowdown.exe"
if not exist "%CARROM_EXE%" set "CARROM_EXE=%~dp0dist\CarromAIShowdown\CarromAIShowdown.exe"
start "" "%CARROM_EXE%" --config "%~dp0.env" --mode demo --official-match
