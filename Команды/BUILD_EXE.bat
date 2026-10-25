@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Personal EXE
echo Закройте игру. Собирается личный admin EXE без входа, хоста и установщика.
echo Сборка привязывается к вашему ПК и пользователю Windows.
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\update_and_build.ps1" -Target exe
set "DND_BUILD_EXIT=%ERRORLEVEL%"
pause
exit /b %DND_BUILD_EXIT%
