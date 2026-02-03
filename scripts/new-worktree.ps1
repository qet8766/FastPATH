<#
.SYNOPSIS
    Creates a git worktree for parallel feature development.

.DESCRIPTION
    Sets up a new git worktree at a sibling directory, creates a Python
    virtual environment, and builds the Rust extension.

.PARAMETER Branch
    Branch name (must start with feature/, fix/, or infra/).

.PARAMETER Base
    Base branch to create from. Defaults to master.

.PARAMETER Fast
    Use dev-fast Rust profile (skips LTO, much faster builds).

.EXAMPLE
    .\scripts\new-worktree.ps1 -Branch feature/annotations
    .\scripts\new-worktree.ps1 -Branch feature/rust-perf -Fast
#>

param(
    [Parameter(Mandatory)]
    [string]$Branch,

    [string]$Base = "master",

    [switch]$Fast
)

$ErrorActionPreference = "Stop"

# Validate branch name prefix
if ($Branch -notmatch "^(feature|fix|infra)/") {
    Write-Error "Branch name must start with 'feature/', 'fix/', or 'infra/'. Got: $Branch"
    exit 1
}

# Derive worktree directory path
$slug = $Branch -replace "/", "-"
$repoRoot = git -C $PSScriptRoot rev-parse --show-toplevel
$worktreeDir = Join-Path (Split-Path $repoRoot -Parent) "FastPATH-wt-$slug"

if (Test-Path $worktreeDir) {
    Write-Error "Worktree directory already exists: $worktreeDir"
    exit 1
}

Write-Host "Creating worktree at: $worktreeDir" -ForegroundColor Cyan
Write-Host "  Branch: $Branch (from $Base)" -ForegroundColor Cyan

# Create worktree with new branch
git worktree add -b $Branch $worktreeDir $Base
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "`nInstalling Python dependencies..." -ForegroundColor Cyan
Push-Location $worktreeDir
try {
    uv sync
    if ($LASTEXITCODE -ne 0) { throw "uv sync failed" }

    Write-Host "`nBuilding Rust extension..." -ForegroundColor Cyan
    if ($Fast) {
        uv run maturin develop --profile dev-fast --manifest-path src/fastpath_core/Cargo.toml
    } else {
        uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
    }
    if ($LASTEXITCODE -ne 0) { throw "maturin develop failed" }

    Write-Host "`n--- Worktree ready ---" -ForegroundColor Green
    Write-Host "Directory:  $worktreeDir"
    Write-Host "Branch:     $Branch"
    Write-Host ""
    Write-Host "To start working:"
    Write-Host "  cd `"$worktreeDir`""
    Write-Host "  uv run python -m fastpath        # Run viewer"
    Write-Host "  uv run python -m pytest tests/   # Run tests"
} finally {
    Pop-Location
}
