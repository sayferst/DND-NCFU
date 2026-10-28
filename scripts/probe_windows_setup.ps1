# Use isolated data; the optional first installer is the pinned previous release.
param([string]$PreviousInstaller = '', [string]$PreviousSource = '')
$ErrorActionPreference = 'Stop'
if ($env:OS -ne 'Windows_NT') { throw 'Native Windows is required.' }
Set-Location (Split-Path $PSScriptRoot -Parent)
$setup = (Resolve-Path 'dist\DND-NCFU-Setup.exe').Path
$root = Join-Path $env:TEMP ('DND-setup-probe-' + [Guid]::NewGuid().ToString('N'))
$install = Join-Path $root 'application'
$data = Join-Path $root 'user-data'
$reports = Join-Path (Get-Location) 'build\setup-probe'
New-Item -ItemType Directory -Force -Path $data,$reports | Out-Null
$sentinel = Join-Path $data 'preserve-on-update.txt'
'Isolated probe data' | Set-Content -LiteralPath $sentinel -Encoding UTF8
$before = (Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash
$previousData = $env:RPG_VKR_DATA_DIR
try {
    $env:RPG_VKR_DATA_DIR = $data
    $python = (Resolve-Path '.venv\Scripts\python.exe').Path
    $campaignData = Join-Path $data 'campaign-probe'
    $writer = 'scripts\probe_saved_campaign.py'
    if ($PreviousInstaller) {
        if (!$PreviousSource) { throw 'Historical source is required for the old writer.' }
        $oldSetup = (Resolve-Path $PreviousInstaller).Path
        $writer = Join-Path (Resolve-Path $PreviousSource).Path 'scripts\probe_saved_campaign.py'
        $old = Start-Process -FilePath $oldSetup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="' + $install + '"')) -PassThru
        if (!$old.WaitForExit(180000)) { $old.Kill(); throw 'Historical Setup timeout.' }
        if ($old.ExitCode -ne 0) { throw 'Historical Setup failed.' }
        $oldExe = Join-Path $install 'DND-NCFU.exe'
        $oldReport = Join-Path $reports 'historical-self-check.json'
        $oldApp = Start-Process -FilePath $oldExe -WorkingDirectory $root -ArgumentList @('--self-check','--report',('"' + $oldReport + '"')) -PassThru
        if (!$oldApp.WaitForExit(180000)) { $oldApp.Kill(); throw 'Historical application timeout.' }
        if ($oldApp.ExitCode -ne 0) { throw 'Historical application failed.' }
        $oldResult = Get-Content -LiteralPath $oldReport -Raw -Encoding UTF8 | ConvertFrom-Json
        if (!$oldResult.ok -or $oldResult.version -ne '0.3.1') { throw 'Unexpected historical binary.' }
    }
    & $python $writer --directory $campaignData --phase create
    if ($LASTEXITCODE -ne 0) { throw 'Could not create isolated saved campaign.' }
    foreach ($pass in @('first','repeat-update')) {
        $process = Start-Process -FilePath $setup -ArgumentList @('/VERYSILENT','/SUPPRESSMSGBOXES','/NORESTART','/SP-',('/DIR="' + $install + '"')) -PassThru
        if (!$process.WaitForExit(180000)) { $process.Kill(); throw 'Setup timeout.' }
        if ($process.ExitCode -ne 0) { throw "Setup failed: $pass" }
        $exe = Join-Path $install 'DND-NCFU.exe'
        if (!(Test-Path -LiteralPath $exe)) { throw 'Installed EXE not found.' }
        foreach ($mode in @('self-check','smoke-test')) {
            $report = Join-Path $reports ($pass + '-' + $mode + '.json')
            $app = Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList @("--$mode",'--report',('"' + $report + '"')) -PassThru
            if (!$app.WaitForExit(180000)) { $app.Kill(); throw 'Installed application timeout.' }
            if ($app.ExitCode -ne 0) { throw 'Installed application failed.' }
            $result = Get-Content -LiteralPath $report -Raw -Encoding UTF8 | ConvertFrom-Json
            if (!$result.ok) { throw 'Installed smoke report is not successful.' }
        }
        & $python scripts\probe_saved_campaign.py --directory $campaignData --phase verify |
            Set-Content -LiteralPath (Join-Path $reports ($pass + '-saved-campaign.json')) -Encoding UTF8
        if ($LASTEXITCODE -ne 0) { throw 'Update did not preserve saved campaign.' }
        $loadReport = Join-Path $reports ($pass + '-installed-save-load.json')
        $loaded = Start-Process -FilePath $exe -WorkingDirectory $root -ArgumentList @('--verify-saved-campaign',('"' + $campaignData + '"'),'--report',('"' + $loadReport + '"')) -PassThru
        if (!$loaded.WaitForExit(180000)) { $loaded.Kill(); throw 'Installed save reader timeout.' }
        if ($loaded.ExitCode -ne 0) { throw 'Installed EXE could not load the historical campaign.' }
        if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $before) { throw 'Update changed isolated user data.' }
    }
    @{ native_windows=$true; install=$true; historical_031_upgrade=[bool]$PreviousInstaller; historical_writer=[bool]$PreviousSource; installed_exe_save_reader=$true; repeat_update=$true; isolated_data_preserved=$true; manual_gui=$false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reports 'setup-result.json') -Encoding UTF8
} finally {
    $env:RPG_VKR_DATA_DIR = $previousData
    # Keep the isolated directory for diagnosing a failed run; never delete user campaigns.
}
