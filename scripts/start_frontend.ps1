param(
    [int]$Port = 8509,
    [string]$PythonPath = "",
    [switch]$NoBrowser,
    [switch]$CheckOnly
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"
$env:STREAMLIT_BROWSER_GATHER_USAGE_STATS = "false"

$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $RepoRoot

function Test-PortOpen {
    param([int]$CandidatePort)
    $client = New-Object System.Net.Sockets.TcpClient
    try {
        $async = $client.BeginConnect("127.0.0.1", $CandidatePort, $null, $null)
        if (-not $async.AsyncWaitHandle.WaitOne(250, $false)) {
            return $false
        }
        $client.EndConnect($async)
        return $true
    }
    catch {
        return $false
    }
    finally {
        $client.Close()
    }
}

function Test-StreamlitHealth {
    param([int]$CandidatePort)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://localhost:$CandidatePort/_stcore/health" -TimeoutSec 2
        return ($response.StatusCode -eq 200 -and "$($response.Content)".Trim() -eq "ok")
    }
    catch {
        return $false
    }
}

function Resolve-BrowserCommand {
    $candidates = @(
        "msedge.exe",
        "chrome.exe",
        "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
        "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
        "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
        "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe"
    )
    foreach ($candidate in $candidates) {
        if (-not $candidate) {
            continue
        }
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) {
            return $command.Source
        }
        if (Test-Path -LiteralPath $candidate) {
            return $candidate
        }
    }
    return ""
}

function Open-FrontendBrowser {
    param([string]$Url)
    if ($NoBrowser) {
        return
    }
    $browser = Resolve-BrowserCommand
    if (-not $browser) {
        Write-Warning "Browser auto-open skipped. Open manually: $Url"
        return
    }
    try {
        Start-Process -FilePath $browser -ArgumentList $Url | Out-Null
    }
    catch {
        Write-Warning "Browser auto-open failed. Open manually: $Url"
    }
}

function Resolve-PythonCommand {
    if ($PythonPath.Trim()) {
        return @{ File = $PythonPath.Trim(); PrefixArgs = @() }
    }

    $python = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($python) {
        return @{ File = $python.Source; PrefixArgs = @() }
    }

    $py = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($py) {
        return @{ File = $py.Source; PrefixArgs = @("-3") }
    }

    throw "Python was not found on PATH. Install Python or pass -PythonPath."
}

$pythonCommand = Resolve-PythonCommand
$pythonFile = $pythonCommand.File
$pythonPrefixArgs = @($pythonCommand.PrefixArgs)

try {
    $streamlitVersion = & $pythonFile @pythonPrefixArgs -c "import streamlit; print(streamlit.__version__)"
}
catch {
    throw "Streamlit is not available for Python: $pythonFile. Run: pip install -r requirements.txt"
}

$SelectedPort = $null
for ($candidate = $Port; $candidate -le ($Port + 20); $candidate++) {
    if (Test-StreamlitHealth -CandidatePort $candidate) {
        $url = "http://localhost:$candidate"
        Write-Host "FinTrace frontend is already running: $url"
        Open-FrontendBrowser -Url $url
        exit 0
    }
    if (-not (Test-PortOpen -CandidatePort $candidate)) {
        $SelectedPort = $candidate
        break
    }
}

if (-not $SelectedPort) {
    throw "No free port found from $Port to $($Port + 20)."
}

$Url = "http://localhost:$SelectedPort"
Write-Host "Repo: $RepoRoot"
Write-Host "Python: $pythonFile"
Write-Host "Streamlit: $streamlitVersion"
Write-Host "URL: $Url"

if ($CheckOnly) {
    Write-Host "CheckOnly passed. The frontend was not started."
    exit 0
}

$BrowserCommand = Resolve-BrowserCommand
if (-not $NoBrowser -and $BrowserCommand) {
    Start-Job -ScriptBlock {
        param($HealthUrl, $FrontendUrl, $BrowserPath)
        for ($i = 0; $i -lt 60; $i++) {
            try {
                $response = Invoke-WebRequest -UseBasicParsing -Uri $HealthUrl -TimeoutSec 2
                if ($response.StatusCode -eq 200 -and "$($response.Content)".Trim() -eq "ok") {
                    Start-Process -FilePath $BrowserPath -ArgumentList $FrontendUrl | Out-Null
                    return
                }
            }
            catch {
                Start-Sleep -Seconds 1
            }
        }
    } -ArgumentList "http://localhost:$SelectedPort/_stcore/health", $Url, $BrowserCommand | Out-Null
}
elseif (-not $NoBrowser) {
    Write-Warning "Browser auto-open skipped. Open manually: $Url"
}

Write-Host ""
Write-Host "Starting Streamlit. Close this window or press Ctrl+C to stop the frontend."
Write-Host ""

& $pythonFile @pythonPrefixArgs -m streamlit run streamlit_app.py --server.port $SelectedPort --server.headless true
