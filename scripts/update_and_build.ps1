# Owner workflow: build local edits, or update a clean checkout before building.
param([ValidateSet('personal', 'exe', 'tester')][string]$Target = 'personal')
$ErrorActionPreference = 'Stop'
try {
    Set-Location (Split-Path $PSScriptRoot -Parent)
    # Never replace scripts underneath an active owner host, including before ready exists.
    $hosts = Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
        Where-Object { $_.CommandLine -match 'tester_host\.py["\s]+start(?:\s|$)' }
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
    $clean = $false
    if (Test-Path -LiteralPath $python) {
        & $python -m scripts.check_update_tree | Out-Null
        $clean = $LASTEXITCODE -eq 0
    } else {
        $changes = & git status --porcelain
        if ($LASTEXITCODE -ne 0) { throw 'Cannot check working tree.' }
        $clean = !$changes
    }
    if ($clean -and !$hosts) {
        & git pull --ff-only
        if ($LASTEXITCODE -ne 0) { throw 'Git update failed. Build stopped.' }
    } else {
        Write-Host 'Building current local files. Git pull skipped: local edits or a running host.'
        Write-Host 'To download remote updates: stop the host and save/commit local edits first.'
    }
    if ($Target -eq 'tester') {
        if (!(Test-Path -LiteralPath $python)) { throw 'Python environment missing. Build a personal EXE first.' }
        & $python scripts\tester_host.py build tester1
        if ($LASTEXITCODE -ne 0) { throw 'Tester build failed. Start START_HOST.bat and wait for readiness.' }
        $output = Join-Path (Get-Location) 'dist\Tester-tester1'
        Write-Host "Tester Setup: $output"
        Start-Process explorer.exe -ArgumentList ('"' + $output + '"')
        exit 0
    }
    $installer = $Target -eq 'personal'
    & (Join-Path $PSScriptRoot 'build_windows.ps1') -Installer:$installer -Profile developer
    if ($LASTEXITCODE -ne 0) { throw 'Windows build failed.' }
    $dist = Join-Path (Get-Location) 'dist'
    # Preserve the personal build before a later tester build replaces dist outputs.
    $stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
    $personal = Join-Path $dist ('Personal-' + $stamp)
    New-Item -ItemType Directory -Path $personal | Out-Null
    if ($installer) {
        Copy-Item -LiteralPath (Join-Path $dist 'DND-NCFU-Setup.exe') -Destination $personal
    }
    Copy-Item -LiteralPath (Join-Path $dist 'DND-NCFU') -Destination $personal -Recurse
    Write-Host "Personal build: $personal"
    Write-Host "Launch: $(Join-Path $personal 'DND-NCFU\DND-NCFU.exe')"
    Write-Host 'Enter personal API keys in the developer console. No API key is embedded.'
    Write-Host 'Next: START_HOST.bat, then BUILD_TESTER_SETUP.bat for tester1.'
    Start-Process explorer.exe -ArgumentList ('"' + $personal + '"')
    exit 0
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
