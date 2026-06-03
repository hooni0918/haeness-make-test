#!/usr/bin/env bash
# common.sh — shared helpers sourced by router.sh and gate scripts.
# NOTE: This file is sourced, not executed. Do NOT set -e here (it would
# leak strict mode side-effects into sourcing scripts unpredictably); the
# sourcing scripts own their own strict-mode settings.

# hes_root: echo the project root.
# common.sh lives at <root>/.claude/hooks/lib/, so ../../.. from this file = root.
hes_root() {
  echo "${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
}

# hes_log <gate> <level> <msg>: append a line to <root>/.claude/logs/gates.log.
# NEVER fail the calling script if logging fails.
hes_log() {
  local gate="${1:-?}" level="${2:-?}" msg="${3:-}"
  local root logdir logfile ts
  root="$(hes_root)"
  logdir="${root}/.claude/logs"
  logfile="${logdir}/gates.log"
  ts="$(date '+%Y-%m-%dT%H:%M:%S%z' 2>/dev/null || echo '?')"
  {
    mkdir -p "$logdir" 2>/dev/null && printf '%s | %s | %s | %s\n' "$ts" "$gate" "$level" "$msg" >>"$logfile"
  } || true
}

# hes_basename_match <glob> <name>: return 0 if name matches glob (case glob, UNQUOTED).
hes_basename_match() {
  local glob="$1" name="$2"
  case "$name" in
    $glob) return 0 ;;
    *) return 1 ;;
  esac
}

# hes_deny <reason>: emit the PreToolUse deny JSON (reason escaped via jq), exit 0.
hes_deny() {
  local reason="${1:-Blocked by HES gate}"
  jq -n --arg r "$reason" \
    '{hookSpecificOutput:{hookEventName:"PreToolUse",permissionDecision:"deny",permissionDecisionReason:$r}}'
  exit 0
}

# hes_allow: allow silently (no output), exit 0.
hes_allow() {
  exit 0
}

# hes_inform <text>: print plain text (warn mode) so the model sees it, exit 0.
hes_inform() {
  local text="${1:-}"
  printf '%s\n' "$text"
  exit 0
}
