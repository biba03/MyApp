param(
    [Parameter(Mandatory=$true)][string]$PythonExe,
    [string]$ProjectDir = 'C:\Jupyter_project\shoryuken_project\shoryuken',
    [string]$NotebookPath = '',
    [switch]$Replace
)
$ErrorActionPreference = 'Stop'
$ProjectDir = (Resolve-Path -LiteralPath $ProjectDir).Path
$PythonExe = (Resolve-Path -LiteralPath $PythonExe).Path
if (!$NotebookPath) { $NotebookPath = Join-Path $ProjectDir 'shoryuken_scanner.ipynb' }
$NotebookPath = (Resolve-Path -LiteralPath $NotebookPath).Path
$Runner = Join-Path $ProjectDir 'run_daily_scan.py'
if (!(Test-Path -LiteralPath $Runner)) { throw "Copy run_daily_scan.py into $ProjectDir first." }
foreach ($p in @($PythonExe,$ProjectDir,$NotebookPath)) {
    if ($p.Contains('"')) { throw 'Paths may not contain double quotes.' }
}
$TaskName = 'Shoryuken Daily Scan 0100 UAE'
if ((Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue) -and !$Replace) {
    throw 'Task already exists. Inspect it first, then add -Replace if you intend to replace it.'
}
# The caller supplies the actual notebook interpreter; no guessing Python versions.
& $PythonExe -m pip install nbclient nbformat ipykernel
if ($LASTEXITCODE -ne 0) { throw 'Could not install execution dependencies.' }
$hash = [System.Security.Cryptography.SHA256]::Create()
$digest = [BitConverter]::ToString($hash.ComputeHash([Text.Encoding]::UTF8.GetBytes($ProjectDir))).Replace('-','').Substring(0,8).ToLowerInvariant()
$Kernel = 'shoryuken-daily-' + $digest
& $PythonExe -m ipykernel install --user --name $Kernel --display-name 'Shoryuken daily scan'
if ($LASTEXITCODE -ne 0) { throw 'Could not register the notebook kernel.' }
$ConfigPath = Join-Path $ProjectDir 'daily_scan_config.json'
@{ project=$ProjectDir; notebook=$NotebookPath; kernel=$Kernel } | ConvertTo-Json | Set-Content -LiteralPath $ConfigPath -Encoding UTF8
& $PythonExe $Runner --config $ConfigPath --dry-run
if ($LASTEXITCODE -ne 0) { throw 'Notebook selection validation failed; task was not registered.' }
$Dubai = [TimeZoneInfo]::FindSystemTimeZoneById('Arabian Standard Time')
$NowDubai = [TimeZoneInfo]::ConvertTimeFromUtc([DateTime]::UtcNow, $Dubai)
$NextDubai = $NowDubai.Date.AddHours(1)
if ($NextDubai -le $NowDubai) { $NextDubai = $NextDubai.AddDays(1) }
$Trigger = New-ScheduledTaskTrigger -Daily -At '01:00'
# Explicit UAE offset, independent of the PC's display time zone.
$Trigger.StartBoundary = $NextDubai.ToString("yyyy-MM-dd'T'HH:mm:ss") + '+04:00'
$Action = New-ScheduledTaskAction -Execute $PythonExe -Argument ('-u "' + $Runner + '" --config "' + $ConfigPath + '"') -WorkingDirectory $ProjectDir
$Settings = New-ScheduledTaskSettingsSet -WakeToRun -StartWhenAvailable -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Hours 12)
$Identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$Principal = New-ScheduledTaskPrincipal -UserId $Identity -LogonType Interactive -RunLevel Limited
$Task = New-ScheduledTask -Action $Action -Trigger $Trigger -Settings $Settings -Principal $Principal -Description 'Shoryuken notebook sections 1 through 6b daily at 01:00 UAE. Account must remain signed in; locked screen is fine.'
Register-ScheduledTask -TaskName $TaskName -InputObject $Task -Force | Out-Null
Write-Host "Installed: $TaskName"
Write-Host 'Schedule: daily 01:00 UAE (UTC+04:00). Keep Windows signed in; you may lock the screen.'
Write-Host 'Wake requested; power hardware/settings must permit wake timers. Shut down PCs cannot run.'
Write-Host "Logs/executed copies: $ProjectDir\logs\scheduled"
Get-ScheduledTaskInfo -TaskName $TaskName | Format-List NextRunTime, LastRunTime, LastTaskResult
