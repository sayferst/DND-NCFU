# Run only against the freshly built developer Setup, using isolated temporary data.
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
    & $python scripts\probe_saved_campaign.py --directory $campaignData --phase create
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
        if ((Get-FileHash -LiteralPath $sentinel -Algorithm SHA256).Hash -ne $before) { throw 'Update changed isolated user data.' }
    }
    @{ native_windows=$true; install=$true; repeat_update=$true; isolated_data_preserved=$true; manual_gui=$false } |
        ConvertTo-Json | Set-Content -LiteralPath (Join-Path $reports 'setup-result.json') -Encoding UTF8
} finally {
    $env:RPG_VKR_DATA_DIR = $previousData
    # Keep the isolated directory for diagnosing a failed run; never delete user campaigns.
}
