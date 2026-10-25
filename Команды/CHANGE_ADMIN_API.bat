@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Admin API
echo Остановите хост через Ctrl+C перед сменой ключа.
echo Ключ admin: бюджет учётной записи 500 рублей. Расходы не сбрасываются.
call "%~dp0..\scripts\tester_host.cmd" key --account admin
set "DND_KEY_EXIT=%ERRORLEVEL%"
echo После успешного сохранения запустите START_HOST.bat.
pause
exit /b %DND_KEY_EXIT%
