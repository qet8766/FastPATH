<#
.SYNOPSIS
    Removes a git worktree and optionally deletes the branch.

.DESCRIPTION
    Cleans up a worktree created by new-worktree.ps1. Removes the worktree
    directory and optionally deletes the local branch.

.PARAMETER Branch
    Branch name of the worktree to remove.

.PARAMETER DeleteBranch
    Also delete the local branch after removing the worktree.

.PARAMETER Force
    Force removal even if the worktree has uncommitted changes.

.EXAMPLE
    .\scripts\remove-worktree.ps1 -Branch feature/test
    .\scripts\remove-worktree.ps1 -Branch feature/test -DeleteBranch
#>

param(
    [Parameter(Mandatory)]
    [string]$Branch,

    [switch]$DeleteBranch,

    [switch]$Force
)

$ErrorActionPreference = "Stop"

$slug = $Branch -replace "/", "-"
$repoRoot = git -C $PSScriptRoot rev-parse --show-toplevel
$worktreeDir = Join-Path (Split-Path $repoRoot -Parent) "FastPATH-wt-$slug"

if (-not (Test-Path $worktreeDir)) {
    Write-Error "Worktree directory not found: $worktreeDir"
    exit 1
}

# Check we're not inside the worktree we're about to remove
$currentDir = (Get-Location).Path
if ($currentDir.StartsWith($worktreeDir)) {
    Write-Error "Cannot remove worktree while inside it. Please cd to a different directory."
    exit 1
}

Write-Host "Removing worktree: $worktreeDir" -ForegroundColor Cyan

if ($Force) {
    git worktree remove --force $worktreeDir
} else {
    git worktree remove $worktreeDir
}
if ($LASTEXITCODE -ne 0) { exit 1 }

Write-Host "Worktree removed." -ForegroundColor Green

if ($DeleteBranch) {
    Write-Host "Deleting branch: $Branch" -ForegroundColor Cyan
    git branch -d $Branch
    if ($LASTEXITCODE -ne 0) {
        Write-Warning "Branch not fully merged. Use 'git branch -D $Branch' to force delete."
    } else {
        Write-Host "Branch deleted." -ForegroundColor Green
    }
}

# Prune stale worktree references
git worktree prune
