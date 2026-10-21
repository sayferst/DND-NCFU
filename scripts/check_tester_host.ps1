# Read-only Windows preflight. No API calls, credentials or system changes.
$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
if ([Environment]::OSVersion.Platform -ne 'Win32NT') {
    throw 'Эта проверка предназначена для Windows.'
}
$python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
$pythonVersion = ''
$pythonReady = $false
if (Test-Path -LiteralPath $python) {
    $pythonVersion = (& $python -c "import sys; print('.'.join(map(str,sys.version_info[:3])))" | Out-String).Trim()
    if ($LASTEXITCODE -eq 0) { $pythonReady = $pythonVersion.StartsWith('3.12.') }
}
$gitCommand = Get-Command git.exe -ErrorAction SilentlyContinue
$tunnelCommand = Get-Command cloudflared.exe -ErrorAction SilentlyContinue
$wingetCommand = Get-Command winget.exe -ErrorAction SilentlyContinue
$gitVersion = ''
$tunnelVersion = ''
if ($gitCommand) { $gitVersion = (& $gitCommand.Source --version | Out-String).Trim() }
if ($tunnelCommand) { $tunnelVersion = (& $tunnelCommand.Source --version | Out-String).Trim() }
$report = [ordered]@{
    check = 'DND-NCFU tester host prerequisites'
    python_312_ready = $pythonReady
    python_version = $pythonVersion
    git_available = [bool]$gitCommand
    git_version = $gitVersion
    cloudflared_available = [bool]$tunnelCommand
    cloudflared_version = $tunnelVersion
    winget_available = [bool]$wingetCommand
    gateway_source_present = Test-Path -LiteralPath 'server\gateway.py'
    tools_ready = ($pythonReady -and [bool]$gitCommand -and [bool]$tunnelCommand)
    network_started = $false
    paid_requests = 0
    secrets_read = $false
}
Write-Output ($report | ConvertTo-Json)
Write-Output ''
Write-Output 'Это только проверка инструментов. Сервер и туннель не запускались.'
Write-Output 'Имена пользователя/ПК, IP-адреса, API-ключи и коды допуска не выводятся.'
if (!$tunnelCommand) {
    Write-Output 'cloudflared пока не найден. При наличии winget установите:'
    Write-Output 'winget install --id Cloudflare.cloudflared --exact --source winget'
    Write-Output 'После установки откройте PowerShell заново и повторите проверку.'
}
if (!$pythonReady) {
    Write-Output 'Не найден Python 3.12 в .venv проекта. Сообщите этот результат владельцу разработки.'
}
if (!$report.tools_ready) { exit 2 }
exit 0
