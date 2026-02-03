# Git Worktree Guide for FastPATH

## What git worktree does

`git worktree` lets you check out **multiple branches simultaneously** in separate directories, all sharing the same `.git` history. Instead of stashing/switching branches, you just `cd` to another folder.

```
C:/chest/projects/FastPATH/          <- main worktree (master)
C:/chest/projects/FastPATH-wt/feat/  <- worktree for a feature branch
C:/chest/projects/FastPATH-wt/fix/   <- worktree for a bugfix branch
```

All three share one `.git` database. Commits in any worktree are visible to the others.

---

## Setup: Create a sibling directory for worktrees

Keep worktrees **outside** the main repo to avoid nesting confusion.

```bash
mkdir C:/chest/projects/FastPATH-wt
```

---

## Core Workflow

### 1. Create a worktree for a new branch

```bash
# From the main repo:
cd C:/chest/projects/FastPATH

# Create branch + worktree in one command:
git worktree add ../FastPATH-wt/feat-overlay -b feat-overlay
```

This creates `C:/chest/projects/FastPATH-wt/feat-overlay/` with the full source tree checked out on the new `feat-overlay` branch.

### 2. Create a worktree for an existing branch

```bash
git worktree add ../FastPATH-wt/fix-gray-tiles fix-gray-tiles
```

### 3. Create a worktree from a remote branch

```bash
git fetch origin
git worktree add ../FastPATH-wt/review origin/some-pr-branch
```

---

## Per-Worktree Setup (required for this codebase)

Each worktree is a **bare checkout** with no `.venv`, no Rust `target/`, and no built `.pyd`. You must bootstrap each one:

### Step 1: Create the venv

```bash
cd C:/chest/projects/FastPATH-wt/feat-overlay
uv sync
```

This creates a `.venv/` inside the worktree. It's gitignored, so it won't interfere.

### Step 2: Build the Rust extension

```bash
uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
```

The `target/` directory is also gitignored. Each worktree gets its own.

### Step 3: Verify

```bash
uv run python -m pytest tests/ -v       # tests pass
uv run python -m fastpath               # viewer launches (if on viewer branch)
```

### One-liner bootstrap

```bash
cd C:/chest/projects/FastPATH-wt/feat-overlay && uv sync && uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
```

---

## Listing and Removing Worktrees

```bash
# List all worktrees:
git worktree list

# Remove a worktree (after merging/done):
git worktree remove ../FastPATH-wt/feat-overlay

# If the directory was already deleted manually:
git worktree prune
```

---

## Key Rules

1. **Never check out the same branch in two worktrees.** Git blocks this by default -- if you see `fatal: 'master' is already checked out`, that's the safety guard working. Use a new branch name.

2. **Don't nest worktrees inside each other.** Always use `../FastPATH-wt/` (sibling directory), not a subdirectory of the main repo.

3. **Each worktree needs its own `uv sync` + `maturin develop`.** The `.venv/` and `target/` are local to each worktree. Changes to `pyproject.toml` or Rust code in one worktree won't auto-build in another.

4. **Commits are shared instantly.** If you commit on `feat-overlay` in one worktree, `git log feat-overlay` in any other worktree shows it immediately (they share the `.git` database).

5. **Always `git worktree remove` before deleting a branch.** If you `git branch -d feat-overlay` while its worktree still exists, git will warn you. Remove the worktree first.

6. **Windows path length**: Keep worktree paths short. `C:/chest/projects/FastPATH-wt/feat/` is better than deeply nested paths. Windows has a 260-char path limit that can bite with deep dependency trees.

---

## Practical Scenarios

### Scenario A: Work on a feature while keeping master clean

```bash
git worktree add ../FastPATH-wt/annotation-export -b annotation-export
cd ../FastPATH-wt/annotation-export
uv sync && uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
# ... develop, commit, push ...
git push -u origin annotation-export
# When done:
cd C:/chest/projects/FastPATH
git worktree remove ../FastPATH-wt/annotation-export
git branch -d annotation-export  # if merged
```

### Scenario B: Quick hotfix while mid-feature

```bash
# You're mid-feature in main worktree. Don't stash -- just:
git worktree add ../FastPATH-wt/hotfix -b hotfix/tile-decode
cd ../FastPATH-wt/hotfix
uv sync && uv run maturin develop --release --manifest-path src/fastpath_core/Cargo.toml
# Fix, test, commit, push, PR, merge
cd C:/chest/projects/FastPATH
git worktree remove ../FastPATH-wt/hotfix
```

### Scenario C: Compare two branches side-by-side

```bash
git worktree add ../FastPATH-wt/compare origin/experiment
# Now you can run both versions simultaneously in different terminals
```

---

## Disk Usage

Each worktree duplicates the working tree but **not** git history. Expect per-worktree:

| Component | Size | Shared? |
|-----------|------|---------|
| `.git` history | ~50 MB | Yes (one copy) |
| Source files | ~5 MB | No (per worktree) |
| `.venv/` | ~829 MB | No (per worktree) |
| `target/` (Rust) | ~485 MB | No (per worktree) |
| **Total per extra worktree** | **~1.3 GB** | |

If disk space is tight, remove worktrees promptly after merging.

---

## Verification

After creating your first worktree, confirm everything works:

```bash
# 1. List worktrees -- should show main + new:
git worktree list

# 2. In the new worktree, verify branch:
cd C:/chest/projects/FastPATH-wt/<name>
git branch --show-current

# 3. Run tests:
uv run python -m pytest tests/ -v

# 4. Clean removal:
cd C:/chest/projects/FastPATH
git worktree remove ../FastPATH-wt/<name>
git worktree list   # should only show main
```
