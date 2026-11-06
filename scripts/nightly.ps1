<#
.SYNOPSIS
    Nightly Remote Radar run: fetch -> ingest -> extract -> publish, then commit and push the snapshot.

.DESCRIPTION
    Steps:
      1. Prepare the environment (OLLAMA_MODELS, UTF-8 for Python, ANTHROPIC_API_KEY for the claude backend).
      2. For the ollama backend, make sure the Ollama server answers on http://127.0.0.1:11434
         (starts "ollama app.exe" if it does not, waits up to 60 s) and that the model is installed.
      3. Run "uv run radar run-all" from pipeline/.
      4. If web/public/data changed, commit it with a dated message. Push only when a remote exists
         and -NoPush is not given.

    Everything is logged to data\logs\nightly-YYYY-MM-DD.log (transcript, 30 days kept).
    The data\ folder (SQLite database, logs) is never committed; only web/public/data is.
    Exit code is 0 on success and non-zero on any failure.

.PARAMETER Backend
    claude or ollama. Default: $env:RADAR_BACKEND, otherwise the pipeline default (config.py).

.PARAMETER Model
    Model tag for the chosen backend. Default: the pipeline default for that backend
    ($env:RADAR_OLLAMA_MODEL / $env:RADAR_CLAUDE_MODEL or config.py).

.PARAMETER NoPush
    Commit locally but do not push.

.PARAMETER DryRun
    Print the plan and read-only checks, then stop. Does not fetch, extract, write a log file,
    start Ollama, commit or push.

.EXAMPLE
    .\scripts\nightly.ps1 -DryRun -NoPush

.EXAMPLE
    .\scripts\nightly.ps1 -Backend claude -Model claude-sonnet-5-5
#>
[CmdletBinding()]
param(
    [ValidateSet('claude', 'ollama')]
    [string]$Backend,

    [string]$Model,

    [switch]$NoPush,

    [switch]$DryRun
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

$RepoRoot    = Split-Path -Parent $PSScriptRoot
$PipelineDir = Join-Path $RepoRoot 'pipeline'
$WebDataRel  = 'web/public/data'
$LogDir      = Join-Path $RepoRoot 'data\logs'
$LogKeepDays = 30
$OllamaUrl   = 'http://127.0.0.1:11434'
$OllamaWaitSeconds = 60
$Today       = Get-Date -Format 'yyyy-MM-dd'
$LogFile     = Join-Path $LogDir ("nightly-{0}.log" -f $Today)

# ----------------------------------------------------------------------------- helpers

function Write-Log {
    param([string]$Message, [string]$Level = 'INFO')
    Write-Host ("[{0}] [{1}] {2}" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Level, $Message)
}

function Write-Plan {
    param([string]$Message)
    Write-Host ("  DRY-RUN  {0}" -f $Message)
}

# Run a native program, stream stdout+stderr line by line to the host (and so into the
# transcript) and return its exit code. Windows PowerShell 5.1 turns native stderr into
# error records, so the error preference is relaxed for the duration of the call.
function Invoke-Native {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $RepoRoot
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkingDirectory
    try {
        & $FilePath @Arguments 2>&1 | ForEach-Object { Write-Host ($_.ToString()) }
        return $LASTEXITCODE
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
}

# Run a native program and return its stdout lines (stderr discarded). Never throws.
function Get-NativeOutput {
    param(
        [Parameter(Mandatory)] [string]$FilePath,
        [string[]]$Arguments = @(),
        [string]$WorkingDirectory = $RepoRoot
    )
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    Push-Location $WorkingDirectory
    try {
        $lines = & $FilePath @Arguments 2>$null
        if ($LASTEXITCODE -ne 0) { return @() }
        return @($lines | ForEach-Object { $_.ToString() })
    }
    catch {
        return @()
    }
    finally {
        Pop-Location
        $ErrorActionPreference = $previous
    }
}

function Test-OllamaUp {
    try {
        $null = Invoke-WebRequest -Uri $OllamaUrl -UseBasicParsing -TimeoutSec 3
        return $true
    }
    catch {
        return $false
    }
}

function Get-OllamaModelNames {
    try {
        $tags = Invoke-RestMethod -Uri ($OllamaUrl + '/api/tags') -TimeoutSec 10
        return @($tags.models | ForEach-Object { $_.name })
    }
    catch {
        return @()
    }
}

function Start-OllamaServer {
    $app = Join-Path $env:LOCALAPPDATA 'Programs\Ollama\ollama app.exe'
    if (Test-Path -LiteralPath $app) {
        Write-Log "Starting Ollama: $app"
        Start-Process -FilePath $app -WindowStyle Hidden
        return
    }
    $cli = Get-Command ollama -ErrorAction SilentlyContinue
    if ($cli) {
        Write-Log "ollama app.exe not found; starting 'ollama serve' instead"
        Start-Process -FilePath $cli.Source -ArgumentList 'serve' -WindowStyle Hidden
        return
    }
    throw "Ollama is not running and no installation was found (looked for '$app' and 'ollama' on PATH)."
}

function Wait-OllamaUp {
    $deadline = (Get-Date).AddSeconds($OllamaWaitSeconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-OllamaUp) { return $true }
        Start-Sleep -Seconds 2
    }
    return (Test-OllamaUp)
}

function Get-ModelTagForCompare {
    param([string]$Name)
    if ($Name -match ':') { return $Name }
    return ($Name + ':latest')
}

# Defaults live in pipeline/src/radar/config.py; ask it instead of duplicating them here.
function Get-PipelineDefaults {
    $result = @{ Backend = 'ollama'; OllamaModel = 'gemma4:12b'; ClaudeModel = 'claude-sonnet-5-5' }
    $code = 'from radar import config; print(config.DEFAULT_BACKEND); print(config.OLLAMA_MODEL); print(config.CLAUDE_MODEL)'
    $lines = @(Get-NativeOutput -FilePath 'uv' -Arguments @('run', 'python', '-c', $code) -WorkingDirectory $PipelineDir)
    if ($lines.Count -ge 3) {
        $result.Backend     = $lines[0].Trim()
        $result.OllamaModel = $lines[1].Trim()
        $result.ClaudeModel = $lines[2].Trim()
    }
    return $result
}

function Remove-OldLogs {
    param([switch]$WhatIfOnly)
    if (-not (Test-Path -LiteralPath $LogDir)) { return }
    $cutoff = (Get-Date).AddDays(-$LogKeepDays)
    $old = @(Get-ChildItem -LiteralPath $LogDir -Filter 'nightly-*.log' -File |
        Where-Object { $_.LastWriteTime -lt $cutoff })
    if ($WhatIfOnly) {
        Write-Plan ("would delete {0} log file(s) older than {1} days" -f $old.Count, $LogKeepDays)
        return
    }
    foreach ($f in $old) {
        Remove-Item -LiteralPath $f.FullName -Force
        Write-Log ("Deleted old log {0}" -f $f.Name)
    }
}

# ----------------------------------------------------------------------------- main

function Invoke-Nightly {
    $started = Get-Date

    foreach ($tool in @('uv', 'git')) {
        if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
            throw "Required tool '$tool' was not found on PATH."
        }
    }

    # Environment ---------------------------------------------------------------
    if (-not $env:OLLAMA_MODELS) { $env:OLLAMA_MODELS = 'F:\Ollama\models' }
    $env:PYTHONUTF8 = '1'
    $env:PYTHONIOENCODING = 'utf-8'
    try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch { }

    $defaults = Get-PipelineDefaults
    $effBackend = $Backend
    if (-not $effBackend) { $effBackend = $env:RADAR_BACKEND }
    if (-not $effBackend) { $effBackend = $defaults.Backend }
    if ($effBackend -notin @('claude', 'ollama')) {
        throw "Unknown backend '$effBackend' (expected claude or ollama)."
    }

    $effModel = $Model
    $modelNote = ''
    if (-not $effModel) {
        if ($effBackend -eq 'claude') { $effModel = $defaults.ClaudeModel } else { $effModel = $defaults.OllamaModel }
        $modelNote = ' (pipeline default)'
    }

    Write-Log "Remote Radar nightly run, $Today"
    Write-Log "Repo        : $RepoRoot"
    Write-Log "Backend     : $effBackend"
    Write-Log "Model       : $effModel$modelNote"
    Write-Log "OLLAMA_MODELS: $env:OLLAMA_MODELS"
    Write-Log ("Push        : {0}" -f $(if ($NoPush) { 'disabled (-NoPush)' } else { 'if a remote exists' }))
    Write-Log ("Mode        : {0}" -f $(if ($DryRun) { 'DRY RUN (no fetch, extract, commit or push)' } else { 'live' }))

    # Step 1: credentials -------------------------------------------------------
    if ($effBackend -eq 'claude') {
        if (-not $env:ANTHROPIC_API_KEY) {
            $userKey = [Environment]::GetEnvironmentVariable('ANTHROPIC_API_KEY', 'User')
            if ($userKey) { $env:ANTHROPIC_API_KEY = $userKey }
        }
        if (-not $env:ANTHROPIC_API_KEY) {
            throw 'Backend is claude but ANTHROPIC_API_KEY is not set (process or User environment).'
        }
        Write-Log 'ANTHROPIC_API_KEY: available (value not printed)'
    }

    # Step 2: Ollama ------------------------------------------------------------
    if ($effBackend -eq 'ollama') {
        $up = Test-OllamaUp
        if ($DryRun) {
            if ($up) { Write-Plan "Ollama already answers at $OllamaUrl" }
            else     { Write-Plan "Ollama is down: would start 'ollama app.exe' and wait up to $OllamaWaitSeconds s" }
            if ($up) {
                $have = @(Get-OllamaModelNames)
                $want = Get-ModelTagForCompare $effModel
                if ($have -contains $want) { Write-Plan "model '$effModel' is installed" }
                else { Write-Plan "WARNING: model '$effModel' not listed by the running server (a live run would stop here)" }
            }
        }
        else {
            if ($up) {
                Write-Log "Ollama already answers at $OllamaUrl"
            }
            else {
                Start-OllamaServer
                if (-not (Wait-OllamaUp)) {
                    throw "Ollama did not respond at $OllamaUrl within $OllamaWaitSeconds s."
                }
                Write-Log 'Ollama is up'
            }
            $have = @(Get-OllamaModelNames)
            $want = Get-ModelTagForCompare $effModel
            if ($have -notcontains $want) {
                throw "Model '$effModel' is not installed in Ollama (OLLAMA_MODELS=$env:OLLAMA_MODELS). Run: ollama pull $effModel"
            }
            Write-Log "Model '$effModel' is installed"
        }
    }

    # Step 3: pipeline ----------------------------------------------------------
    $runArgs = @('run', 'radar', 'run-all', '--backend', $effBackend)
    if ($Model) { $runArgs += @('--model', $Model) }
    $runText = 'uv ' + ($runArgs -join ' ')
    if ($DryRun) {
        Write-Plan "(in $PipelineDir) $runText"
    }
    else {
        Write-Log "Running: $runText"
        $code = Invoke-Native -FilePath 'uv' -Arguments $runArgs -WorkingDirectory $PipelineDir
        if ($code -ne 0) { throw "radar run-all failed with exit code $code." }
        Write-Log 'Pipeline finished'
    }

    # Step 4: commit and push ---------------------------------------------------
    $dataChanged = @(Get-NativeOutput -FilePath 'git' -Arguments @('status', '--porcelain', '-uall', '--', $WebDataRel))
    $remotes = @(Get-NativeOutput -FilePath 'git' -Arguments @('remote'))
    $commitMsg = "data: nightly snapshot ${Today} (${effBackend}:${effModel})"

    if ($DryRun) {
        if ($dataChanged.Count -gt 0) {
            Write-Plan ("$WebDataRel currently has {0} uncommitted change(s) (a live run would re-check after the pipeline)" -f $dataChanged.Count)
        }
        else {
            Write-Plan "$WebDataRel has no uncommitted changes right now (a live run commits only if the pipeline changes it)"
        }
        Write-Plan "if changed: git add -- $WebDataRel"
        Write-Plan "if changed: git commit -m `"$commitMsg`" -- $WebDataRel"
        if ($NoPush) { Write-Plan 'push: skipped (-NoPush)' }
        elseif ($remotes.Count -eq 0) { Write-Plan 'push: skipped (no git remote configured)' }
        else { Write-Plan ("push: git push (remote(s): {0})" -f ($remotes -join ', ')) }
        Write-Plan "data\ (SQLite, logs) is never added to git"
        Remove-OldLogs -WhatIfOnly
        Write-Plan "log file would be: $LogFile"
        Write-Log 'Dry run complete. Nothing was fetched, extracted, committed or pushed.'
        return
    }

    $dataChanged = @(Get-NativeOutput -FilePath 'git' -Arguments @('status', '--porcelain', '-uall', '--', $WebDataRel))
    if ($dataChanged.Count -eq 0) {
        Write-Log "$WebDataRel unchanged; nothing to commit"
    }
    else {
        Write-Log ("$WebDataRel changed ({0} file(s)); committing" -f $dataChanged.Count)
        $code = Invoke-Native -FilePath 'git' -Arguments @('add', '--', $WebDataRel)
        if ($code -ne 0) { throw "git add failed with exit code $code." }
        # Pathspec form commits only these paths, even if something else is staged.
        $code = Invoke-Native -FilePath 'git' -Arguments @('commit', '-m', $commitMsg, '--', $WebDataRel)
        if ($code -ne 0) { throw "git commit failed with exit code $code." }
        Write-Log "Committed: $commitMsg"

        if ($NoPush) {
            Write-Log 'Push skipped (-NoPush)'
        }
        elseif ($remotes.Count -eq 0) {
            Write-Log 'Push skipped (no git remote configured)'
        }
        else {
            $upstream = @(Get-NativeOutput -FilePath 'git' -Arguments @('rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}'))
            if ($upstream.Count -gt 0) {
                $pushArgs = @('push')
            }
            else {
                $remoteName = $remotes[0]
                if ($remotes -contains 'origin') { $remoteName = 'origin' }
                $pushArgs = @('push', '--set-upstream', $remoteName, 'HEAD')
            }
            Write-Log ('Running: git ' + ($pushArgs -join ' '))
            $code = Invoke-Native -FilePath 'git' -Arguments $pushArgs
            if ($code -ne 0) { throw "git push failed with exit code $code." }
            Write-Log 'Pushed'
        }
    }

    Write-Log ("Done in {0:N0} s" -f ((Get-Date) - $started).TotalSeconds)
}

# ----------------------------------------------------------------------------- entry point

$exitCode = 0
$transcribing = $false

if (-not $DryRun) {
    New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
    try {
        Start-Transcript -Path $LogFile -Append | Out-Null
        $transcribing = $true
    }
    catch {
        Write-Host "WARNING: could not start transcript at ${LogFile}: $($_.Exception.Message)"
    }
}

try {
    Invoke-Nightly
    if (-not $DryRun) { Remove-OldLogs }
}
catch {
    Write-Log $_.Exception.Message 'ERROR'
    if ($_.ScriptStackTrace) { Write-Log $_.ScriptStackTrace 'ERROR' }
    $exitCode = 1
}
finally {
    if ($transcribing) {
        try { Stop-Transcript | Out-Null } catch { }
    }
}

exit $exitCode
