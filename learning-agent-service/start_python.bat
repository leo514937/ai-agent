@echo off
setlocal EnableExtensions

set "SCRIPT_DIR=%~dp0"
%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start_python.ps1"
exit /b %ERRORLEVEL%
