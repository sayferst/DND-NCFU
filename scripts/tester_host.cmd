@echo off
setlocal
cd /d "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Python environment missing. Run check_tester_host.cmd first.
  exit /b 2
)
".venv\Scripts\python.exe" "scripts\tester_host.py" %*
exit /b %errorlevel%
