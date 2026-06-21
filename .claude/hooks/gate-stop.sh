#!/usr/bin/env bash
set -euo pipefail

# gate-stop.sh — Stop hook. Once per turn, rescans git-changed SOURCE files
# through the Layer-1 controller (gate1). This is the net that catches file
# writes via paths the PreToolUse gates never see (Bash heredoc/redirect/sed,
# sub-agents, interpreters, etc.). It cannot undo the write (already on disk)
# but blocks the STOP so the model is told to fix the violation before ending
# the turn. Fail-open everywhere: no git / no python3 / no controller / nothing
# changed -> allow the stop silently.
#
# Why a Stop hook (not PostToolUse): the Claude Code docs recommend a Stop hook
# for "see every file change ... scan the working tree once per turn" —
# PostToolUse cannot undo and is not told which files a Bash command touched.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"
ROOT="$(hes_root)"

INPUT="$(cat)"

# Loop guard: if this stop is already a continuation forced by a prior block,
# let it stop (the docs warn an unconditional re-block runs Claude forever).
active="$(jq -r '.stop_hook_active // false' <<<"$INPUT" 2>/dev/null || echo false)"
[ "$active" = "true" ] && exit 0

command -v git >/dev/null 2>&1 || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
git -C "$ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || exit 0

CONTROLLER="${ROOT}/tools/hes_controller.py"
[ -f "$CONTROLLER" ] || exit 0

# Collect added/modified/untracked files that still exist (skip deletes). The
# controller does its own source-glob/ignore filtering, so pass everything.
files=()
while IFS= read -r line; do
  [ -n "$line" ] || continue
  path="${line:3}"                                        # strip 'XY ' prefix
  case "$line" in *" -> "*) path="${line##* -> }" ;; esac # rename -> take dest
  path="${path%\"}"; path="${path#\"}"                    # unquote if quoted
  [ -f "${ROOT}/${path}" ] || continue
  files+=("${ROOT}/${path}")
# -uall expands untracked directories to individual files (plain --porcelain
# collapses a new dir to 'dir/', which is not a file and would be skipped).
done < <(git -C "$ROOT" status --porcelain -uall 2>/dev/null || true)

# Guard before expanding the array (empty-array expansion errors under set -u).
[ "${#files[@]}" -gt 0 ] || exit 0

out="$(python3 "$CONTROLLER" --json --files "${files[@]}" 2>/dev/null || true)"
[ -n "$out" ] || exit 0

verdict="$(printf '%s' "$out" | jq -r '.verdict // empty' 2>/dev/null || echo)"
[ "$verdict" = "REJECTED" ] || exit 0

reason="$(printf '%s' "$out" | jq -r '
  [ .files[]?
    | select((((.violations // []) | map(select(.severity=="error")) | length) > 0)
             or (((.errors // []) | length) > 0))
    | "• " + .file + ": "
      + (([ (.violations // [])[] | select(.severity=="error") | .message ] + (.errors // []))
         | join("; ")) ]
  | join("\n")' 2>/dev/null || echo)"

hes_stop_block "HES gate1 위반이 디스크에 기록됨 (Bash 등 PreToolUse 미적용 경로). 수정 후 다시 진행하세요:"$'\n'"${reason}"
