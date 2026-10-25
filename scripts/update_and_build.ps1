# Owner workflow: update a clean checkout and build a personal-API Windows installer.
$ErrorActionPreference = 'Stop'
try {
    Set-Location (Split-Path $PSScriptRoot -Parent)
    # Never replace scripts underneath an active owner host, including before ready exists.
    $hosts = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match 'tester_host\.py["\s]+start(?:\s|$)' }
    if ($hosts) { throw 'Stop START_HOST.bat with Ctrl+C before updating.' }
    $branch = & git branch --show-current
    if ($LASTEXITCODE -ne 0 -or $branch.Trim() -ne 'setup/development-environment') {
        throw 'Expected branch: setup/development-environment. No branch was changed.'
    }
    # Repair only the known, hash-verified LF -> CRLF fixture conversion before
    # checking cleanliness. The builder otherwise repairs it too late for this check.
    $python = Join-Path (Get-Location) '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $python) {
        & $python scripts\repair_fixture_checkout.py
        if ($LASTEXITCODE -ne 0) { throw 'Fixture repair refused changes. Update stopped.' }
    }
    if (Test-Path -LiteralPath $python) {
        & $python -m scripts.check_update_tree
        if ($LASTEXITCODE -ne 0) { throw 'Local changes found. Save them before updating; nothing was discarded.' }
    } else {
        $changes = & git status --porcelain
        if ($LASTEXITCODE -ne 0 -or $changes) { throw 'Working tree is not clean. Update stopped.' }
    }
    & git pull --ff-only
    if ($LASTEXITCODE -ne 0) { throw 'Git update failed. Build stopped.' }
    & (Join-Path $PSScriptRoot 'build_windows.ps1') -Installer -Profile developer
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    $dist = Join-Path (Get-Location) 'dist'
    # Preserve the personal build before a later tester build replaces dist outputs.
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $personal = Join-Path $dist ('Personal-' + $stamp)
    New-Item -ItemType Directory -Path $personal | Out-Null
    Copy-Item -LiteralPath (Join-Path $dist 'DND-NCFU-Setup.exe') -Destination $personal
    Copy-Item -LiteralPath (Join-Path $dist 'DND-NCFU') -Destination $personal -Recurse
    Write-Host "Setup and portable EXE: $personal"
    Write-Host 'Enter personal API keys in the developer console. No API key is embedded.'
    Write-Host 'Next: START_HOST.bat, then BUILD_TESTER_SETUP.bat for tester1.'
    Start-Process explorer.exe -ArgumentList ('"' + $personal + '"')
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
