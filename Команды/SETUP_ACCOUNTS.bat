@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Accounts
echo Остановите хост через Ctrl+C перед настройкой.
echo Сначала сохраните ключи через CHANGE_ADMIN_API.bat и CHANGE_TESTER_API.bat.
echo Здесь задаются только пароли admin и tester.
call "%~dp0..\scripts\tester_host.cmd" accounts
set "DND_ACCOUNT_EXIT=%ERRORLEVEL%"
pause
exit /b %DND_ACCOUNT_EXIT%
