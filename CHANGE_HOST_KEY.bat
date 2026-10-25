@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Change host API
echo Сначала остановите старый хост через Ctrl+C в его окне.
echo Новый ключ вводится только здесь, на вашем ПК.
call "%~dp0scripts\tester_host.cmd" key
if errorlevel 1 goto failed
call "%~dp0START_HOST.bat"
exit /b %ERRORLEVEL%
:failed
echo Ключ не изменён. Проверьте сообщение выше.
pause
exit /b 1
