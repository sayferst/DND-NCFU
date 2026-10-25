@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Update and build
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\update_and_build.ps1"
set "DND_BUILD_EXIT=%ERRORLEVEL%"
pause
exit /b %DND_BUILD_EXIT%
