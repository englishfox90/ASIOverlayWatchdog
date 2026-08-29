<#
.SYNOPSIS
    Start or stop PFR Sentinel capture from a NINA Advanced Sequencer step.

.DESCRIPTION
    Calls Sentinel's capture-control API (POST /capture/start | /capture/stop).
    This is the zero-C# half of the NINA integration: drop an "External Script"
    instruction into a sequence, point it at the matching .bat wrapper, and
    capture follows the observing session.

    Credentials are read out of Sentinel's own config.json, so there is nothing
    to paste into NINA. The token is never printed, logged, or echoed - not
    even with -Verbose.

    The call blocks until capture actually reaches the requested state (or the
    timeout elapses), so the sequence does not advance while capture is still
    spinning up. Both commands are idempotent: re-running Start on a running
    capture, or Stop twice on abort, succeeds rather than failing the sequence.

.PARAMETER Command
    'start' or 'stop'.

.PARAMETER TimeoutSeconds
    How long to wait for the target state. 1-300, default 30.

.PARAMETER BaseUrl
    Override the server URL (e.g. http://127.0.0.1:8080). Defaults to the
    host/port in Sentinel's config.

.PARAMETER Token
    Override the bearer token. Defaults to output.api_token in Sentinel's config.

.PARAMETER ConfigPath
    Override the path to Sentinel's config.json.

.EXAMPLE
    .\Invoke-SentinelCapture.ps1 -Command start

.NOTES
    Exit codes (NINA fails the sequence step on any non-zero):
      0  success, including idempotent no-ops
      2  Sentinel config.json not found
      3  control API not enabled, or no token configured
      4  Sentinel not reachable
      5  authentication rejected
      6  timed out waiting for the target state
      7  capture reported a failure
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet('start', 'stop')]
    [string]$Command,

    [ValidateRange(1, 300)]
    [int]$TimeoutSeconds = 30,

    [string]$BaseUrl,
    [string]$Token,
    [string]$ConfigPath
)

# Windows PowerShell 5.1 is what the .bat wrapper launches, so this script must
# stay parseable there: no ternary (? :), no null-coalescing (??), no `clean`
# PS7-only syntax. A parse error here fails the whole NINA step with a wall of
# red rather than a usable message.
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Write-Step([string]$Message) {
    # NINA surfaces script stdout in the sequence log.
    Write-Output "[Sentinel] $Message"
}

function Fail([int]$Code, [string]$Message) {
    Write-Output "[Sentinel] ERROR: $Message"
    exit $Code
}

# --- Locate Sentinel's configuration -------------------------------------
if (-not $ConfigPath) {
    $ConfigPath = Join-Path $env:LOCALAPPDATA 'PFRSentinel\config.json'
}

$needsConfig = (-not $BaseUrl) -or (-not $Token)
$output = $null

if ($needsConfig) {
    if (-not (Test-Path -LiteralPath $ConfigPath)) {
        Fail 2 "Sentinel config not found at $ConfigPath. Pass -BaseUrl and -Token explicitly if Sentinel runs elsewhere."
    }
    try {
        $config = Get-Content -LiteralPath $ConfigPath -Raw -Encoding UTF8 | ConvertFrom-Json
    } catch {
        Fail 2 "Could not read Sentinel config at $ConfigPath."
    }
    if (-not $config.PSObject.Properties.Name.Contains('output')) {
        Fail 3 "Sentinel config has no 'output' section - is this a current Sentinel install?"
    }
    $output = $config.output
}

function Get-OutputValue([string]$Name, $Default) {
    if ($null -eq $output) { return $Default }
    if ($output.PSObject.Properties.Name -contains $Name) {
        $value = $output.$Name
        if ($null -ne $value -and "$value" -ne '') { return $value }
    }
    return $Default
}

if (-not $BaseUrl) {
    $host_ = Get-OutputValue 'webserver_host' '127.0.0.1'
    # A wildcard bind is an address to listen on, not one to connect to.
    # http://0.0.0.0:8080 does not resolve - and the control API's Host
    # allow-list accepts loopback anyway, so that is the right target.
    if ($host_ -in @('0.0.0.0', '::', '[::]', '')) { $host_ = '127.0.0.1' }
    $port = Get-OutputValue 'webserver_port' 8080
    $BaseUrl = "http://${host_}:${port}"
}
$BaseUrl = $BaseUrl.TrimEnd('/')

$controlPath = (Get-OutputValue 'webserver_control_path' '/capture').TrimEnd('/')

if (-not $Token) {
    if (-not (Get-OutputValue 'webserver_control_enabled' $false)) {
        Fail 3 "The capture control API is switched off in Sentinel. Enable it on the Output tab, then retry."
    }
    $Token = Get-OutputValue 'api_token' ''
    if (-not $Token) {
        Fail 3 "No control API token is configured in Sentinel. Enable the control API on the Output tab to mint one."
    }
}

# --- Issue the command ----------------------------------------------------
$uri = "$BaseUrl$controlPath/$Command"
$body = @{ wait = $true; timeout = $TimeoutSeconds } | ConvertTo-Json -Compress

Write-Step "$Command -> $uri (waiting up to ${TimeoutSeconds}s)"

# Give the HTTP client headroom over the server-side wait so a server that is
# about to answer isn't cut off by our own client timeout.
$clientTimeout = $TimeoutSeconds + 15

try {
    $response = Invoke-RestMethod -Uri $uri -Method Post -Body $body `
        -ContentType 'application/json' `
        -Headers @{ Authorization = "Bearer $Token" } `
        -TimeoutSec $clientTimeout
} catch {
    $err = $_
    $webResponse = $null
    if ($err.Exception.PSObject.Properties.Name -contains 'Response') {
        $webResponse = $err.Exception.Response
    }

    if ($null -eq $webResponse) {
        Fail 4 "Sentinel is not reachable at $BaseUrl. Is it running with the web server enabled?"
    }

    $status = [int]$webResponse.StatusCode

    # Sentinel puts the real cause in the response body - "No ZWO cameras
    # detected", and a machine-readable `code`. Read it before branching;
    # "check the log" is a poor substitute for the reason we were just handed.
    # PowerShell 7 hands the body to $_.ErrorDetails.Message; Windows PowerShell
    # 5.1 requires reading the response stream. Try both - the .bat wrapper does
    # not pin which one runs.
    $detail = $null
    $errCode = $null
    $raw = $null
    if ($err.PSObject.Properties.Name -contains 'ErrorDetails' -and $err.ErrorDetails) {
        $raw = $err.ErrorDetails.Message
    }
    if (-not $raw) {
        try {
            $reader = New-Object System.IO.StreamReader($webResponse.GetResponseStream())
            $raw = $reader.ReadToEnd()
        } catch { }
    }
    if ($raw) {
        try {
            $parsed = $raw | ConvertFrom-Json
            if ($parsed.PSObject.Properties.Name -contains 'message') { $detail = $parsed.message }
            elseif ($parsed.PSObject.Properties.Name -contains 'error') { $detail = $parsed.error }
            if ($parsed.PSObject.Properties.Name -contains 'code') { $errCode = $parsed.code }
        } catch { }
    }

    if ($detail) { Write-Output "[Sentinel] Server said: $detail" }

    # 503 has two causes needing opposite fixes; `code` is what separates them.
    if ($status -eq 503) {
        if ($errCode -eq 'control_unavailable') {
            Fail 3 "Sentinel is running but capture control is not wired up. Restart Sentinel."
        }
        Fail 3 "The capture control API is switched off in Sentinel. Enable it on the Output tab."
    }

    switch ($status) {
        401 { Fail 5 "Authentication rejected. Regenerate the token on Sentinel's Output tab." }
        403 { Fail 5 "Request rejected by the Host allow-list. Sentinel only accepts control calls from the same machine." }
        504 { Fail 6 "Timed out after ${TimeoutSeconds}s waiting for capture to $Command." }
        500 {
            if ($detail) { Fail 7 $detail }
            Fail 7 "Capture reported a failure while trying to $Command. Check Sentinel's log."
        }
        default { Fail 4 "Unexpected HTTP $status from Sentinel." }
    }
}

# --- Report ---------------------------------------------------------------
$result = $response.result
$state = $response.state

switch ($result) {
    'already_running' { Write-Step "Capture was already running (no change)." }
    'already_stopped' { Write-Step "Capture was already stopped (no change)." }
    'started'         { Write-Step "Capture started (state: $state)." }
    'stopped'         { Write-Step "Capture stopped (state: $state)." }
    default           { Write-Step "Result: $result (state: $state)." }
}

exit 0
