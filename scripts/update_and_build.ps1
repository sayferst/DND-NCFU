# Owner workflow: always check GitHub before building the latest available sources.
param([ValidateSet('exe', 'tester')][string]$Target = 'tester')
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
    # Fetch changes references only: safe with local edits and a running host.
    # A failed network check must never silently produce an allegedly current build.
    Write-Host 'Checking GitHub for the latest game sources...'
    & git fetch origin 'refs/heads/setup/development-environment:refs/remotes/origin/setup/development-environment'
    if ($LASTEXITCODE -ne 0) { throw 'Cannot check GitHub. Build stopped; previous artifacts were not updated.' }
    $remote = (& git rev-parse refs/remotes/origin/setup/development-environment).Trim()
    if ($LASTEXITCODE -ne 0) { throw 'Cannot resolve the checked remote version.' }
    & git merge-base --is-ancestor $remote HEAD
    $containsLatest = $LASTEXITCODE -eq 0
    if ($LASTEXITCODE -gt 1) { throw 'Cannot compare local and remote versions.' }
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
    if (!$containsLatest) {
        if (!$clean) { throw 'GitHub has new changes. Save/commit local edits, update, then rebuild. No outdated build was made.' }
        if ($hosts) { throw 'GitHub has new changes. Stop START_HOST.bat with Ctrl+C, then rebuild. No outdated build was made.' }
        & git merge --ff-only $remote
        if ($LASTEXITCODE -ne 0) { throw 'Update failed or branches diverged. Build stopped; local changes were preserved.' }
    }
    Write-Host "Latest checked GitHub version: $remote"
    if (!$clean) {
        Write-Host 'Including your additional local edits in this build.'
    }
    if ($Target -eq 'exe') {
        & $python scripts\tester_host.py build-exe
        if ($LASTEXITCODE -ne 0) { throw 'Owner EXE build failed. Check the saved admin key.' }
        Start-Process explorer.exe -ArgumentList ('"' + (Join-Path (Get-Location) 'dist') + '"')
        exit 0
    }
    if ($Target -eq 'tester') {
        if (!(Test-Path (Join-Path $env:LOCALAPPDATA 'DND-NCFU-Host\account-mode.json'))) {
            throw 'First run SETUP_ACCOUNTS.bat from the launcher folder.'
        }
        if (!(Test-Path -LiteralPath $python)) { throw 'Python environment missing. Build a personal EXE first.' }
        & $python scripts\tester_host.py build tester1
        if ($LASTEXITCODE -ne 0) { throw 'Tester build failed. Start START_HOST.bat and wait for readiness.' }
        $output = Join-Path (Get-Location) 'dist\Release'
        Write-Host "Tester Setup: $output"
        Start-Process explorer.exe -ArgumentList ('"' + $output + '"')
        exit 0
    }
} catch {
    Write-Host $_.Exception.Message -ForegroundColor Red
    exit 1
}
