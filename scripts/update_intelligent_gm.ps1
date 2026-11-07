$ErrorActionPreference = "Stop"
$ProjectRoot = Split-Path -Parent $PSScriptRoot
$Branch = "codex/intelligent-gm-20261103"
Push-Location $ProjectRoot
try {
    & git fetch origin
    if ($LASTEXITCODE -ne 0) { throw "Fetch failed; no checkout was changed." }
    & git show-ref --verify --quiet "refs/heads/$Branch"
    if ($LASTEXITCODE -eq 0) { & git switch $Branch } else { & git switch --track "origin/$Branch" }
    if ($LASTEXITCODE -ne 0) { throw "Switch failed. Preserve local changes and resolve them before continuing." }
    & git merge --ff-only "origin/$Branch"
    if ($LASTEXITCODE -ne 0) { throw "Fast-forward failed. No reset, stash or deletion was attempted." }
    Write-Host "Source checkout updated. Existing EXE installations require a separate rebuild."
} finally { Pop-Location }
