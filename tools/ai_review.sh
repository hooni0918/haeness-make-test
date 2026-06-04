#!/usr/bin/env bash
set -euo pipefail

# ai_review.sh — advisory AI reviewer for the HES controller (--ai-review) and
# the skill bridge. Reads a payload from STDIN (gate findings + a unified diff
# or file content) and prints a single verdict line on stdout.
#
# FAIL-OPEN and cheap by design: anything that goes wrong (no claude CLI, empty
# input, empty model response) yields an APPROVE line and exit 0. Exit code is
# ALWAYS 0 — this reviewer is advisory; the CALLER decides what to do with the
# APPROVE/REJECT verdict text.

# --- Resolve project root from this script's own location (tools/ is a child
# of root) so config lookups work regardless of cwd. ------------------------
SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SELF_DIR}/.." && pwd)"
CONFIG="${ROOT}/.claude/config.json"

# --- Pick the model: HES_REVIEW_MODEL override > config gates.gate2.model >
# hard-coded default. ---------------------------------------------------------
DEFAULT_MODEL="claude-haiku-4-5-20251001"
MODEL="${HES_REVIEW_MODEL:-}"
if [ -z "$MODEL" ]; then
  if command -v jq >/dev/null 2>&1 && [ -f "$CONFIG" ]; then
    MODEL="$(jq -r '.gates.gate2.model // empty' "$CONFIG" 2>/dev/null || true)"
  fi
fi
[ -n "$MODEL" ] || MODEL="$DEFAULT_MODEL"

# --- FAIL-OPEN: no claude CLI -> approve and skip. ---------------------------
if ! command -v claude >/dev/null 2>&1; then
  printf 'APPROVE (ai-review skipped: claude CLI not found)\n'
  exit 0
fi

# --- Read the payload from STDIN. --------------------------------------------
PAYLOAD="$(cat || true)"
if [ -z "$PAYLOAD" ]; then
  printf 'APPROVE (ai-review skipped: empty payload)\n'
  exit 0
fi

# --- Build a compact prompt. The model must answer on the FIRST line with
# exactly APPROVE or REJECT followed by a one-line reason. --------------------
PROMPT="You are an advisory code reviewer for a convention-gate harness.
Below are gate findings and a code change (a unified diff or file content).
Decide whether the change should be APPROVED or REJECTED.

On the FIRST line reply with EXACTLY one word, APPROVE or REJECT, followed by a
single short one-line reason on the same line. Do not add any other lines.

--- PAYLOAD ---
${PAYLOAD}
--- END PAYLOAD ---"

# --- Call the model (guarded, fail-open). ------------------------------------
out="$(printf '%s' "$PROMPT" | claude -p --model "$MODEL" --output-format text 2>/dev/null || true)"

if [ -z "$out" ]; then
  printf 'APPROVE (ai-review skipped: empty response)\n'
  exit 0
fi

# --- Print the model's verdict line (first non-empty line). ------------------
verdict=""
while IFS= read -r line; do
  if [ -n "$line" ]; then
    verdict="$line"
    break
  fi
done <<<"$out"

if [ -z "$verdict" ]; then
  printf 'APPROVE (ai-review skipped: blank response)\n'
  exit 0
fi

printf '%s\n' "$verdict"
exit 0
