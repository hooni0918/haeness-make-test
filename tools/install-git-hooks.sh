#!/usr/bin/env bash
set -euo pipefail

# install-git-hooks.sh — install the HES pre-commit hook into this repo's git
# hooks directory so the gate enforces on every `git commit`, including commits
# made outside Claude Code. Idempotent: re-running overwrites the installed
# hook with the current source. Does NOT modify anything outside the git hooks
# directory.

# Resolve the repo root from this script's own location so it works from any
# cwd: the script lives at <root>/tools/install-git-hooks.sh.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SELF_DIR}/.." && pwd)"

SRC="${SELF_DIR}/git-hooks/pre-commit"

if [ ! -f "$SRC" ]; then
  printf 'error: hook source not found at %s\n' "$SRC" >&2
  exit 1
fi

# Resolve the git hooks directory (honours core.hooksPath and worktrees).
# `--git-path hooks` may return a relative path, so resolve it against ROOT.
HOOKS_REL="$(git -C "$ROOT" rev-parse --git-path hooks)"
case "$HOOKS_REL" in
  /*) HOOKS_DIR="$HOOKS_REL" ;;
  *)  HOOKS_DIR="${ROOT}/${HOOKS_REL}" ;;
esac

DEST="${HOOKS_DIR}/pre-commit"

mkdir -p "$HOOKS_DIR"
cp "$SRC" "$DEST"
chmod +x "$DEST"

printf 'Installed HES pre-commit hook:\n'
printf '  source: %s\n' "$SRC"
printf '  dest:   %s\n' "$DEST"
printf '\n'
printf 'The gate now runs on every `git commit` (override with `git commit --no-verify`).\n'
printf 'To uninstall:\n'
printf '  rm %s\n' "$DEST"
