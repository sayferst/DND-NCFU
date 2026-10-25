@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Tester Setup
echo Закройте игру. Запустите START_HOST.bat и дождитесь готовности хоста.
echo Собирается персональный Setup для tester1 с доступом через хост.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\update_and_build.ps1" -Target tester
set "DND_BUILD_EXIT=%ERRORLEVEL%"
pause
exit /b %DND_BUILD_EXIT%
