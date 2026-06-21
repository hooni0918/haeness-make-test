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

# hes_normpath <path>: lexically normalize a path (collapse '.', '..', '//')
# WITHOUT touching the filesystem — the target may not exist yet (it is a
# PROPOSED write). Done in awk (already a dependency, and bash-3.2 safe; an
# array-pop in pure bash needs negative indices unavailable on macOS 3.2).
# This closes the path-traversal hole where '.../tools/../src/x.py' contained
# the literal 'tools/' and dodged the ignore list while writing to src/.
hes_normpath() {
  awk -v p="$1" 'BEGIN{
    abs = (p ~ /^\//); n = split(p, a, "/"); top = 0
    for (i = 1; i <= n; i++) { s = a[i]
      if (s == "" || s == ".") continue
      if (s == "..") { if (top > 0 && st[top] != "..") top--; else if (!abs) st[++top] = ".." }
      else st[++top] = s }
    out = ""; for (i = 1; i <= top; i++) out = out (i > 1 ? "/" : "") st[i]
    print (abs ? "/" out : out) }'
}

# hes_sha256 <file>: print the hex sha256 of a file, portably (macOS 'shasum',
# Linux 'sha256sum'). Empty string if neither tool exists — callers treat an
# empty hash as "cannot determine" and skip the check (fail-quiet, never block).
hes_sha256() {
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$1" 2>/dev/null | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" 2>/dev/null | awk '{print $1}'
  fi
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

# hes_stop_block <reason>: emit a Stop "block" decision and exit 0. Stop hooks
# use a TOP-LEVEL `decision`/`reason` (not the PreToolUse hookSpecificOutput
# shape); "block" prevents Claude from stopping and feeds the reason back so it
# fixes the violation before ending the turn.
hes_stop_block() {
  local reason="${1:-Blocked by HES Stop rescan}"
  jq -n --arg r "$reason" '{decision:"block",reason:$r}'
  exit 0
}
