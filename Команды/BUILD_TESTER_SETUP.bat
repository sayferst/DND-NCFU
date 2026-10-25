@echo off
setlocal
chcp 65001 >nul
title DND-NCFU - Tester setup
rem Compatibility alias: one common installer for admin and tester.
call "%~dp0BUILD_SETUP.bat"
exit /b %ERRORLEVEL%
