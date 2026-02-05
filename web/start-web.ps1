# FastPATH Web Viewer Startup Script
# Starts both uvicorn (API) and Caddy (front door) with proper coordination

param(
    [string]$SlideDir = "C:\chest\projects\fastpath_web\WSIs",
    [string]$JunctionDir = "C:\chest\projects\fastpath_web\.fastpath_junctions",
    [string]$DistDir = "C:\chest\projects\fastpath_web\web\client\dist",
    [string]$HttpsAddr = "https://localhost",
    [switch]$Dev,        # Use HMR mode with Vite
    [switch]$NoBrowser,  # Don't open browser
    [switch]$Build       # Rebuild client before starting
)

$ErrorActionPreference = "Stop"
$projectRoot = "C:\chest\projects\fastpath_web"

Write-Host "FastPATH Web Viewer Startup" -ForegroundColor Cyan
Write-Host "============================" -ForegroundColor Cyan

# Set environment variables globally for child processes
$env:FASTPATH_WEB_SLIDE_DIRS = $SlideDir
$env:FASTPATH_WEB_JUNCTION_DIR = $JunctionDir
$env:FASTPATH_WEB_DIST_DIR = $DistDir
$env:FASTPATH_WEB_HTTPS_ADDR = $HttpsAddr

Write-Host "Slide Dir:    $SlideDir"
Write-Host "Junction Dir: $JunctionDir"
Write-Host "Dist Dir:     $DistDir"
Write-Host "HTTPS Addr:   $HttpsAddr"
Write-Host "Mode:         $(if ($Dev) { 'Development (HMR)' } else { 'Production' })"
Write-Host ""

# Track processes
$script:processes = @()

function Cleanup {
    Write-Host "`nShutting down services..." -ForegroundColor Yellow
    foreach ($proc in $script:processes) {
        if ($proc -and -not $proc.HasExited) {
            Write-Host "Stopping PID $($proc.Id)..."
            try {
                # Kill process tree
                taskkill /F /T /PID $proc.Id 2>$null
            } catch {}
        }
    }
    Write-Host "Done." -ForegroundColor Green
}

# Handle Ctrl+C via trap
trap {
    Cleanup
    break
}

try {
    Set-Location $projectRoot

    # Build client if requested or if dist doesn't exist (production mode only)
    if (-not $Dev) {
        $indexPath = Join-Path $DistDir "index.html"
        if ($Build -or -not (Test-Path $indexPath)) {
            Write-Host "Building client..." -ForegroundColor Yellow
            Push-Location "web\client"
            try {
                if (-not (Test-Path "node_modules")) {
                    Write-Host "Installing npm dependencies..."
                    npm install
                    if ($LASTEXITCODE -ne 0) { throw "npm install failed" }
                }
                npm run build
                if ($LASTEXITCODE -ne 0) { throw "Client build failed" }
            } finally {
                Pop-Location
            }
            Write-Host "Client built successfully." -ForegroundColor Green
        }
    }

    # Start uvicorn
    Write-Host "Starting uvicorn (API server on :8000)..." -ForegroundColor Yellow
    $uvicornProc = Start-Process -FilePath "uv" -ArgumentList @(
        "run", "--group", "dev",
        "uvicorn", "web.server.main:app",
        "--host", "127.0.0.1",
        "--port", "8000"
    ) -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden
    $script:processes += $uvicornProc

    # Wait for uvicorn to be ready
    Write-Host "Waiting for uvicorn..."
    $maxWait = 30
    $waited = 0
    while ($waited -lt $maxWait) {
        Start-Sleep -Milliseconds 500
        $waited += 0.5
        try {
            $response = Invoke-WebRequest -Uri "http://127.0.0.1:8000/api/slides" -TimeoutSec 2 -ErrorAction Stop
            Write-Host "uvicorn ready (status: $($response.StatusCode))" -ForegroundColor Green
            break
        } catch {
            if ($uvicornProc.HasExited) {
                throw "uvicorn exited with code $($uvicornProc.ExitCode)"
            }
        }
    }
    if ($waited -ge $maxWait) {
        throw "uvicorn did not start within ${maxWait}s"
    }

    # Start Vite in dev mode
    if ($Dev) {
        Write-Host "Starting Vite (HMR on :5173)..." -ForegroundColor Yellow
        $clientDir = Join-Path $projectRoot "web\client"

        # Install deps if needed
        if (-not (Test-Path (Join-Path $clientDir "node_modules"))) {
            Push-Location $clientDir
            npm install
            Pop-Location
        }

        $viteProc = Start-Process -FilePath "npm" -ArgumentList "run", "dev" `
            -WorkingDirectory $clientDir -PassThru -WindowStyle Hidden
        $script:processes += $viteProc

        # Wait for Vite
        Write-Host "Waiting for Vite..."
        $waited = 0
        while ($waited -lt 20) {
            Start-Sleep -Milliseconds 500
            $waited += 0.5
            try {
                $null = Invoke-WebRequest -Uri "http://127.0.0.1:5173" -TimeoutSec 2 -ErrorAction Stop
                Write-Host "Vite ready" -ForegroundColor Green
                break
            } catch {
                if ($viteProc.HasExited) {
                    throw "Vite exited unexpectedly"
                }
            }
        }
    }

    # Start Caddy
    Write-Host "Starting Caddy (front door)..." -ForegroundColor Yellow
    $caddyfile = if ($Dev) { "web\Caddyfile.dev" } else { "web\Caddyfile" }
    $caddyPath = Join-Path $projectRoot $caddyfile

    $caddyProc = Start-Process -FilePath "caddy" -ArgumentList "run", "--config", $caddyPath `
        -WorkingDirectory $projectRoot -PassThru -WindowStyle Hidden
    $script:processes += $caddyProc

    # Wait briefly for Caddy
    Start-Sleep -Seconds 2
    if ($caddyProc.HasExited) {
        throw "Caddy exited with code $($caddyProc.ExitCode)"
    }
    Write-Host "Caddy ready" -ForegroundColor Green

    # Determine URL
    $browseUrl = if ($Dev) {
        "http://127.0.0.1:8080/"
    } else {
        $HttpsAddr + "/"
    }

    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "FastPATH Web Viewer is running!" -ForegroundColor Green
    Write-Host "Browse: $browseUrl" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "Services:" -ForegroundColor Gray
    Write-Host "  uvicorn (API):  http://127.0.0.1:8000/api/slides"
    if ($Dev) {
        Write-Host "  Vite (HMR):     http://127.0.0.1:5173/"
        Write-Host "  Caddy (HTTP):   http://127.0.0.1:8080/"
    } else {
        Write-Host "  Caddy (HTTPS):  $HttpsAddr/"
    }
    Write-Host ""
    Write-Host "Press Ctrl+C to stop all services" -ForegroundColor Yellow
    Write-Host "========================================" -ForegroundColor Green

    # Open browser
    if (-not $NoBrowser) {
        Start-Process $browseUrl
    }

    # Keep running until any process exits or Ctrl+C
    while ($true) {
        Start-Sleep -Seconds 1

        foreach ($proc in $script:processes) {
            if ($proc.HasExited) {
                Write-Host "A service exited (PID $($proc.Id), code $($proc.ExitCode))" -ForegroundColor Red
                throw "Service terminated unexpectedly"
            }
        }
    }
} catch {
    Write-Host "Error: $_" -ForegroundColor Red
} finally {
    Cleanup
}
