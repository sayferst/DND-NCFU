@echo off
setlocal
pushd "%~dp0.."
if not exist ".venv\Scripts\python.exe" (
  echo Project Python .venv is missing. Read docs/intelligent_gm/WINDOWS_FAUN_SETUP.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m training.setup_faun --interactive
set "DND_SETUP_EXIT=%ERRORLEVEL%"
popd
pause
exit /b %DND_SETUP_EXIT%
