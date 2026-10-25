@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Tester setup
echo Оставьте START_HOST.bat открытым. Дождитесь готовности хоста.
echo Сборка tester1 сохраняет существующие расходы и срок допуска.
call "%~dp0scripts\tester_host.cmd" build tester1
set "DND_BUILD_EXIT=%ERRORLEVEL%"
if not "%DND_BUILD_EXIT%"=="0" goto failed
explorer.exe "%~dp0dist\Tester-tester1"
goto done
:failed
echo Сборка не завершена. Старый Setup не является новой сборкой.
:done
pause
exit /b %DND_BUILD_EXIT%
