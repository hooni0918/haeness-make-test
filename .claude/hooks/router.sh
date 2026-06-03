#!/usr/bin/env bash
set -euo pipefail

# router.sh — THE single PreToolUse entrypoint. Reads one JSON object on stdin,
# runs the enabled gates against the PROPOSED content, and emits exactly one
# decision (deny JSON, plain-text inform, or silent allow).

# a. Resolve own dir, source lib/common.sh, ROOT.
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"
ROOT="$(hes_root)"

# b. Read stdin EXACTLY once.
INPUT="$(cat)"

# c. Extract tool_name and file_path.
tool_name="$(jq -r '.tool_name // empty' <<<"$INPUT")"
file_path="$(jq -r '.tool_input.file_path // empty' <<<"$INPUT")"

# d. No file_path -> nothing to gate.
if [ -z "$file_path" ]; then
  hes_allow
fi

# e. Temp file for proposed content; clean on exit.
CONTENT_FILE="$(mktemp "${TMPDIR:-/tmp}/hes_content.XXXXXX")"
trap 'rm -f "$CONTENT_FILE"' EXIT

case "$tool_name" in
  Write)
    jq -r '.tool_input.content // empty' <<<"$INPUT" >"$CONTENT_FILE"
    ;;
  Edit)
    jq -r '.tool_input.new_string // empty' <<<"$INPUT" >"$CONTENT_FILE"
    ;;
  MultiEdit)
    jq -r '.tool_input.edits[]?.new_string // empty' <<<"$INPUT" >"$CONTENT_FILE"
    ;;
  *)
    # Unknown tool — nothing to gate.
    hes_allow
    ;;
esac

# f. Derive rel path, basename, change line count.
case "$file_path" in
  "${ROOT}/"*) rel="${file_path#"${ROOT}/"}" ;;
  *) rel="$file_path" ;;
esac
base="$(basename "$file_path")"
# Count lines robustly: awk END{NR} counts a final line that lacks a trailing
# newline too (wc -l would undercount it by 1 and skew the gate2/3 thresholds).
change_lines="$(awk 'END{print NR}' "$CONTENT_FILE" 2>/dev/null || echo 0)"
case "$change_lines" in ''|*[!0-9]*) change_lines=0 ;; esac

# g. Load config and decide whether this is a SOURCE file.
CONFIG="${ROOT}/.claude/config.json"
if [ ! -f "$CONFIG" ]; then
  # No config -> nothing we can enforce.
  hes_allow
fi

mode="$(jq -r '.mode // "enforce"' "$CONFIG")"

# Source-glob match.
is_source="false"
while IFS= read -r glob; do
  [ -n "$glob" ] || continue
  if hes_basename_match "$glob" "$base"; then
    is_source="true"
    break
  fi
done < <(jq -r '.source_globs[]?' "$CONFIG")

if [ "$is_source" != "true" ]; then
  hes_allow
fi

# Ignore by path substring.
while IFS= read -r sub; do
  [ -n "$sub" ] || continue
  case "$rel" in
    *"$sub"*) hes_allow ;;
  esac
done < <(jq -r '.ignore_path_substrings[]?' "$CONFIG")

# Ignore by basename glob.
while IFS= read -r glob; do
  [ -n "$glob" ] || continue
  if hes_basename_match "$glob" "$base"; then
    hes_allow
  fi
done < <(jq -r '.ignore_basename_globs[]?' "$CONFIG")

# Common env for all gates.
export HES_ROOT="$ROOT"
export HES_FILE_PATH="$rel"
export HES_BASENAME="$base"
export HES_CONTENT_FILE="$CONTENT_FILE"
export HES_CHANGE_LINES="$change_lines"

VIOLATIONS=""

append_violations() {
  # $1 = block of violation lines (possibly empty / trailing newline).
  local block="$1"
  [ -n "$block" ] || return 0
  if [ -n "$VIOLATIONS" ]; then
    VIOLATIONS="${VIOLATIONS}"$'\n'"${block}"
  else
    VIOLATIONS="${block}"
  fi
}

# h. Gate 1 — always run (the only HARD guarantee).
g1="$(bash "${SELF_DIR}/gate1-shell.sh" || true)"
append_violations "$g1"

# Thresholds. Force integers — a malformed (non-numeric) config value would
# otherwise abort the `[ -ge ]` test under set -e and could fail-open past
# gate1, the one hard guarantee.
gate2_min="$(jq -r '.thresholds.gate2_min_lines // 50' "$CONFIG")"
gate3_min="$(jq -r '.thresholds.gate3_min_lines // 200' "$CONFIG")"
case "$gate2_min" in ''|*[!0-9]*) gate2_min=50 ;; esac
case "$gate3_min" in ''|*[!0-9]*) gate3_min=200 ;; esac

# i. Gate 2 — enabled + size threshold.
gate2_enabled="$(jq -r '.gates.gate2.enabled // false' "$CONFIG")"
if [ "$gate2_enabled" = "true" ] && [ "$change_lines" -ge "$gate2_min" ]; then
  export HES_GATE2_MODEL="$(jq -r '.gates.gate2.model // empty' "$CONFIG")"
  g2="$(bash "${SELF_DIR}/gate2-semantic.sh" || true)"
  append_violations "$g2"
fi

# j. Gate 3 — enabled + size threshold.
gate3_enabled="$(jq -r '.gates.gate3.enabled // false' "$CONFIG")"
if [ "$gate3_enabled" = "true" ] && [ "$change_lines" -ge "$gate3_min" ]; then
  export HES_GATE3_MODEL="$(jq -r '.gates.gate3.model // empty' "$CONFIG")"
  g3="$(bash "${SELF_DIR}/gate3-architect.sh" || true)"
  append_violations "$g3"
fi

# k. Count error-severity violations.
error_count=0
if [ -n "$VIOLATIONS" ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    sev="${line%%|*}"
    if [ "$sev" = "error" ]; then
      error_count=$((error_count + 1))
    fi
  done <<<"$VIOLATIONS"
fi

# Build a joined error-message string for deny reason.
error_msgs=""
if [ "$error_count" -gt 0 ]; then
  while IFS= read -r line; do
    [ -n "$line" ] || continue
    sev="${line%%|*}"
    [ "$sev" = "error" ] || continue
    # message is the 3rd pipe field onward.
    rest="${line#*|}"        # drop severity
    msg="${rest#*|}"         # drop gate
    if [ -n "$error_msgs" ]; then
      error_msgs="${error_msgs}; ${msg}"
    else
      error_msgs="${msg}"
    fi
  done <<<"$VIOLATIONS"
fi

hes_log "router" "info" "tool=${tool_name} file=${rel} lines=${change_lines} mode=${mode} errors=${error_count} violations=$(printf '%s' "$VIOLATIONS" | grep -c . || true)"

# l. Decide.
if [ "$mode" = "enforce" ] && [ "$error_count" -gt 0 ]; then
  hes_deny "Blocked by HES gate: ${error_msgs}"
elif [ -n "$VIOLATIONS" ]; then
  summary="HES gate warnings for ${rel}:"$'\n'"${VIOLATIONS}"
  hes_inform "$summary"
else
  hes_allow
fi
