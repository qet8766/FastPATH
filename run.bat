@echo off
cd /d "%~dp0"
echo Starting FastPATH...
uv run python -m fastpath %*
if errorlevel 1 (
    echo.
    echo Error occurred. Press any key to exit.
    pause >nul
)
