@echo off
cd /d "%~dp0"
echo === FastPATH Setup ===
echo.

echo [1/2] Installing Python dependencies...
uv sync
if errorlevel 1 (
    echo FAILED: uv sync
    pause
    exit /b 1
)
echo.

echo [2/2] Building Rust tile scheduler (release, this may take a while)...
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
if errorlevel 1 (
    echo FAILED: maturin build
    pause
    exit /b 1
)
echo.

echo === Setup complete. Run 'run.bat' to start FastPATH. ===
pause
