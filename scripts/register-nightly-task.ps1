<#
.SYNOPSIS
    Registers (or removes) the Windows Task Scheduler task "RemoteRadar Nightly".

.DESCRIPTION
    The task runs scripts\nightly.ps1 for the CURRENT user, daily at 03:30 by default.
      - Runs only while the user is logged on (no password is stored).
      - Does not wake the computer. If the PC was off or asleep at 03:30, the run starts as
        soon as possible afterwards (StartWhenAvailable).
      - Only one instance at a time; killed after 3 hours.

    The script prints exactly what it is going to do and then asks for confirmation
    (ConfirmImpact is High, so you get a prompt unless you pass -Confirm:$false).
    Use -WhatIf to see the plan without changing anything.

.PARAMETER Unregister
    Remove the task instead of creating it.

.PARAMETER At
    Daily start time as HH:mm (24 h). Default 03:30.

.PARAMETER Backend
    Optional. Passed to nightly.ps1 as -Backend (claude or ollama).

.PARAMETER Model
    Optional. Passed to nightly.ps1 as -Model.

.EXAMPLE
    .\scripts\register-nightly-task.ps1 -WhatIf

.EXAMPLE
    .\scripts\register-nightly-task.ps1

.EXAMPLE
    .\scripts\register-nightly-task.ps1 -Unregister
#>
[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'High')]
param(
    [switch]$Unregister,

    [ValidatePattern('^([01]?\d|2[0-3]):[0-5]\d$')]
    [string]$At = '03:30',

    [ValidateSet('claude', 'ollama')]
    [string]$Backend,

    [string]$Model
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$TaskName   = 'RemoteRadar Nightly'
$ScriptPath = Join-Path $PSScriptRoot 'nightly.ps1'
$RepoRoot   = Split-Path -Parent $PSScriptRoot
$UserId     = '{0}\{1}' -f $env:USERDOMAIN, $env:USERNAME

$existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

# ----------------------------------------------------------------------------- unregister

if ($Unregister) {
    Write-Host ''
    Write-Host "Plan: remove scheduled task '$TaskName' for $UserId"
    if (-not $existing) {
        Write-Host 'The task does not exist. Nothing to do.'
        exit 0
    }
    if ($PSCmdlet.ShouldProcess($TaskName, 'Unregister scheduled task')) {
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Host "Removed '$TaskName'."
    }
    exit 0
}

# ----------------------------------------------------------------------------- register

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    throw "Cannot find $ScriptPath"
}

$scriptArgs = @('-NoProfile', '-ExecutionPolicy', 'Bypass', '-WindowStyle', 'Hidden', '-File', ('"{0}"' -f $ScriptPath))
if ($Backend) { $scriptArgs += @('-Backend', $Backend) }
if ($Model)   { $scriptArgs += @('-Model', ('"{0}"' -f $Model)) }
$argumentString = $scriptArgs -join ' '

$when = [datetime]::ParseExact($At, @('H:mm', 'HH:mm'), [System.Globalization.CultureInfo]::InvariantCulture, [System.Globalization.DateTimeStyles]::None)

Write-Host ''
Write-Host 'Plan: register a scheduled task with these settings'
Write-Host "  Name        : $TaskName"
Write-Host "  User        : $UserId (runs only when logged on; no password stored)"
Write-Host ("  Schedule    : daily at {0}" -f $when.ToString('HH:mm'))
Write-Host "  Command     : powershell.exe $argumentString"
Write-Host "  Working dir : $RepoRoot"
Write-Host '  Wake PC     : no'
Write-Host '  If missed   : run as soon as possible after the PC is available'
Write-Host '  Limits      : one instance at a time, stop after 3 hours, allowed on battery'
if ($existing) {
    Write-Host "  Note        : a task with this name already exists and will be replaced"
}
Write-Host ''

if ($PSCmdlet.ShouldProcess($TaskName, 'Register scheduled task')) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument $argumentString -WorkingDirectory $RepoRoot
    $trigger = New-ScheduledTaskTrigger -Daily -At $when
    $settings = New-ScheduledTaskSettingsSet `
        -StartWhenAvailable `
        -AllowStartIfOnBatteries `
        -DontStopIfGoingOnBatteries `
        -MultipleInstances IgnoreNew `
        -ExecutionTimeLimit (New-TimeSpan -Hours 3)
    $principal = New-ScheduledTaskPrincipal -UserId $UserId -LogonType Interactive -RunLevel Limited

    Register-ScheduledTask `
        -TaskName $TaskName `
        -Description 'Remote Radar: fetch remote jobs, extract with an LLM, publish the dashboard snapshot.' `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Principal $principal `
        -Force | Out-Null

    Write-Host "Registered '$TaskName'. Logs: $(Join-Path $RepoRoot 'data\logs')"
    Write-Host "Test it now with:  Start-ScheduledTask -TaskName '$TaskName'"
    Write-Host "Remove it with:    .\scripts\register-nightly-task.ps1 -Unregister"
}
