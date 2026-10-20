# Optional developer packaging; no model calls and no credentials in the bundle.
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Собирайте Windows EXE на Windows x64.' }
Set-Location (Split-Path $PSScriptRoot -Parent)
& '.\.venv\Scripts\python.exe' -m PyInstaller --version
if ($LASTEXITCODE -ne 0) {
    throw 'Установите бесплатные инструменты: .\.venv\Scripts\python.exe -m pip install --require-hashes -r requirements-build.lock'
}
& '.\.venv\Scripts\python.exe' scripts\check.py
if ($LASTEXITCODE -ne 0) { throw 'Проверки не прошли, сборка остановлена.' }
& '.\.venv\Scripts\python.exe' -m PyInstaller --noconfirm DND-NCFU.spec
if ($LASTEXITCODE -ne 0) { throw 'Сборка не завершена.' }
Write-Host 'Готова папка dist\DND-NCFU. Переносить нужно всю папку, не один EXE.'
