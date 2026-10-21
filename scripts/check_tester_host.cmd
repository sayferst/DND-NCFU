@echo off
setlocal
rem Read-only preflight; execution policy changes only for this child process.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0check_tester_host.ps1" %*
exit /b %ERRORLEVEL%
