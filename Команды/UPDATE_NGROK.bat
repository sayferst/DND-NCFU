@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Update ngrok
echo Перед обновлением остановите хост через Ctrl+C в его окне.
echo Обновляется отдельная копия ngrok. Ключи и допуски сохраняются.
call "%~dp0..\scripts\tester_host.cmd" update-ngrok
set "DND_NGROK_EXIT=%ERRORLEVEL%"
echo.
if not "%DND_NGROK_EXIT%"=="0" goto failed
echo Обновление завершено. Для запуска хоста откройте START_HOST.bat.
goto done
:failed
echo Обновление не завершено. Проверьте сообщение выше.
:done
pause
exit /b %DND_NGROK_EXIT%
