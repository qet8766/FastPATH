@echo off
REM FastPATH Web Viewer Quick Start
REM Usage: start-web.bat [dev]

setlocal

set FASTPATH_WEB_SLIDE_DIRS=C:\chest\projects\fastpath_web\WSIs
set FASTPATH_WEB_JUNCTION_DIR=C:\chest\projects\fastpath_web\.fastpath_junctions
set FASTPATH_WEB_DIST_DIR=C:\chest\projects\fastpath_web\web\client\dist
set FASTPATH_WEB_HTTPS_ADDR=https://localhost

cd /d C:\chest\projects\fastpath_web

if "%1"=="dev" (
    echo Starting in DEVELOPMENT mode ^(HMR^)...
    powershell -ExecutionPolicy Bypass -File web\start-web.ps1 -Dev
) else (
    echo Starting in PRODUCTION mode...
    powershell -ExecutionPolicy Bypass -File web\start-web.ps1
)
