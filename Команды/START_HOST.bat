@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Host
echo Запуск хоста DND-NCFU...
echo Оставьте это окно открытым, пока тестировщик играет.
echo Для остановки нажмите Ctrl+C.
echo.
call "%~dp0..\scripts\tester_host.cmd" start
set "DND_HOST_EXIT_CODE=%ERRORLEVEL%"
echo.
if not "%DND_HOST_EXIT_CODE%"=="0" echo Хост завершился с ошибкой. Сохраните сообщения выше.
echo Хост остановлен. Нажмите любую клавишу, чтобы закрыть окно.
pause >nul
exit /b %DND_HOST_EXIT_CODE%
