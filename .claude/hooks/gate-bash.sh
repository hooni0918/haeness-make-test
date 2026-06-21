#!/usr/bin/env bash
set -euo pipefail

# gate-bash.sh — PreToolUse hook for the Bash tool.
#
# Scope: pre-block ONLY Bash writes to the HES *control plane* (rules, config,
# settings, hooks, CONVENTIONS.md). router.sh's self-protection guard (step g2)
# covers Edit/Write/MultiEdit but NOT Bash, so without this a single
# `echo '{}' > .claude/cache/rules.json` disables every gate in one unhooked
# write. General source writes via Bash are intentionally NOT parsed here —
# shell parsing is unreliable and would cause false positives; those are caught
# after the fact by gate-stop.sh (turn-end working-tree rescan).
# Known residual: writes via interpreters (`python -c "open(...,'w')"`) are not
# detected here, and their control-plane targets are not source files so the
# Stop rescan won't see them either.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"
ROOT="$(hes_root)"

INPUT="$(cat)"
command_str="$(jq -r '.tool_input.command // empty' <<<"$INPUT")"
[ -n "$command_str" ] || hes_allow

mode="enforce"
CONFIG="${ROOT}/.claude/config.json"
if [ -f "$CONFIG" ]; then
  mode="$(jq -r '.mode // "enforce"' "$CONFIG")"
fi

if [ "$mode" = "enforce" ] && [ "${HES_ALLOW_SELF_EDIT:-}" != "1" ]; then
  # Control-plane path tokens — keep in sync with router.sh step g2.
  cp_re='(\.claude/hooks/|\.claude/cache/rules\.json|\.claude/config\.json|\.claude/settings\.json|CONVENTIONS\.md)'
  # (a) redirect INTO a control-plane file: '>' or '>>' then a path with a CP token.
  redir_re=">>?[[:space:]]*[^[:space:];|&]*${cp_re}"
  # (b) a write-capable tool naming a control-plane path as an argument.
  tool_re="(^|[[:space:];&|])(tee|sed[[:space:]]+-i|dd|truncate|cp|mv|install|ln)[[:space:]][^;&|]*${cp_re}"
  if printf '%s' "$command_str" | grep -qE "$redir_re" \
    || printf '%s' "$command_str" | grep -qE "$tool_re"; then
    hes_deny "Blocked by HES gate: [hes-self-protect] Bash가 HES control plane 파일을 수정하려 함 — 사람이 직접 편집 후 'python3 tools/parse_conventions.py', 또는 HES_ALLOW_SELF_EDIT=1 로 우회."
  fi
fi

hes_allow
