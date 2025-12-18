#!/usr/bin/env bash
set -euo pipefail

DEV_DIR="$HOME/英単語テスト/英単語テスト_cp"
PROD_DIR="$HOME/英単語テスト/英単語テスト"

echo "==> Check develop worktree..."
cd "$DEV_DIR"
branch="$(git branch --show-current)"
if [ "$branch" != "develop" ]; then
  echo "ERROR: develop worktree is not on 'develop' (current: $branch)"
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: develop has uncommitted changes. Commit/stash first."
  exit 1
fi

echo "==> Fetch & pull develop..."
git fetch origin
git pull --ff-only origin develop

echo "==> Check main worktree..."
cd "$PROD_DIR"
branch="$(git branch --show-current)"
if [ "$branch" != "main" ]; then
  echo "ERROR: main worktree is not on 'main' (current: $branch)"
  exit 1
fi

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: main has uncommitted changes. Commit/stash first."
  exit 1
fi

echo "==> Fetch & pull main..."
git fetch origin
git pull --ff-only origin main

echo "==> Merge develop -> main (no-ff)..."
git merge --no-ff --no-edit origin/develop

echo "==> Push main..."
git push origin main

echo "✅ Done: develop changes promoted to main and pushed."
