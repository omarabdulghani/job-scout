$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$DashboardUrl = "http://127.0.0.1:8000/recommended_jobs_dashboard.html"
$HealthUrl = "http://127.0.0.1:8000/api/run-control"
$LogDir = Join-Path $ProjectRoot "logs"
$StdoutLog = Join-Path $LogDir "dashboard_server_stdout.log"
$StderrLog = Join-Path $LogDir "dashboard_server_stderr.log"

function Test-DashboardServer {
    try {
        Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 2 | Out-Null
        return $true
    }
    catch {
        return $false
    }
}

Set-Location $ProjectRoot
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

if (-not (Test-DashboardServer)) {
    Start-Process `
        -FilePath "python" `
        -ArgumentList @("serve_dashboard.py") `
        -WorkingDirectory $ProjectRoot `
        -WindowStyle Hidden `
        -RedirectStandardOutput $StdoutLog `
        -RedirectStandardError $StderrLog

    $ready = $false
    for ($attempt = 0; $attempt -lt 30; $attempt++) {
        Start-Sleep -Milliseconds 500
        if (Test-DashboardServer) {
            $ready = $true
            break
        }
    }

    if (-not $ready) {
        Write-Host "Dashboard server did not start within 15 seconds." -ForegroundColor Red
        Write-Host "Check logs:" -ForegroundColor Yellow
        Write-Host "  $StdoutLog"
        Write-Host "  $StderrLog"
        Read-Host "Press Enter to close"
        exit 1
    }
}

Start-Process $DashboardUrl
