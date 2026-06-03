#!/usr/bin/env bash
set -euo pipefail

# gate2-semantic.sh — Haiku on the diff (~300 tok). FAIL-OPEN: any problem
# (disabled, no claude CLI, empty content, model error/timeout) -> print NO
# violations and exit cleanly. Prints  error|gate2|<msg>  lines on real hits.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"

ROOT="${HES_ROOT:-$(hes_root)}"
CONTENT_FILE="${HES_CONTENT_FILE:-}"
MODEL="${HES_GATE2_MODEL:-}"
RULES="${ROOT}/.claude/cache/rules.json"

# --- FAIL-OPEN guards ---------------------------------------------------------
if [ -z "$CONTENT_FILE" ] || [ ! -f "$CONTENT_FILE" ] || [ ! -s "$CONTENT_FILE" ]; then
  hes_log "gate2" "warn" "skip: empty/missing content"
  exit 0
fi
if ! command -v claude >/dev/null 2>&1; then
  hes_log "gate2" "warn" "skip: claude CLI not found (fail-open)"
  exit 0
fi
if [ -z "$MODEL" ]; then
  hes_log "gate2" "warn" "skip: no model configured (fail-open)"
  exit 0
fi

# --- Build a compact prompt ---------------------------------------------------
rule_msgs="$(jq -r '.rules[]? | "- [\(.id)] \(.message)"' "$RULES" 2>/dev/null || true)"
content="$(cat "$CONTENT_FILE")"

PROMPT="You are a code-convention gate. Below are the project conventions and a proposed code change.
Report ONLY semantic convention violations that pure regex cannot catch.

Conventions:
${rule_msgs}

Proposed code:
---
${content}
---

Reply with ONLY one violation per line in EXACTLY this format:
error|gate2|<short message>
If there are no violations, reply with the single word: PASS"

# --- Call the model (guarded, fail-open) -------------------------------------
out="$(printf '%s' "$PROMPT" | claude -p --model "$MODEL" --output-format text 2>/dev/null || true)"

if [ -z "$out" ]; then
  hes_log "gate2" "warn" "skip: empty model response (fail-open)"
  exit 0
fi

# Print any non-empty, non-PASS lines verbatim.
while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in
    PASS|pass|Pass) continue ;;
  esac
  printf '%s\n' "$line"
done <<<"$out"

exit 0
