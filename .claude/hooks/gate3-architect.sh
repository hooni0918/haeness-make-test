#!/usr/bin/env bash
set -euo pipefail

# gate3-architect.sh — Sonnet for architecture-level review (rare). Same shape
# as gate2 but ALSO feeds ARCHITECTURE.md into the prompt. FAIL-OPEN: any
# problem -> print NO violations, exit cleanly. Prints  error|gate3|<msg> lines.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"

ROOT="${HES_ROOT:-$(hes_root)}"
CONTENT_FILE="${HES_CONTENT_FILE:-}"
MODEL="${HES_GATE3_MODEL:-}"
ARCH="${ROOT}/ARCHITECTURE.md"

# --- FAIL-OPEN guards ---------------------------------------------------------
if [ -z "$CONTENT_FILE" ] || [ ! -f "$CONTENT_FILE" ] || [ ! -s "$CONTENT_FILE" ]; then
  hes_log "gate3" "warn" "skip: empty/missing content"
  exit 0
fi
if ! command -v claude >/dev/null 2>&1; then
  hes_log "gate3" "warn" "skip: claude CLI not found (fail-open)"
  exit 0
fi
if [ -z "$MODEL" ]; then
  hes_log "gate3" "warn" "skip: no model configured (fail-open)"
  exit 0
fi

# --- Build the prompt (includes ARCHITECTURE.md if present) -------------------
arch_doc=""
if [ -f "$ARCH" ]; then
  arch_doc="$(cat "$ARCH")"
fi
content="$(cat "$CONTENT_FILE")"

PROMPT="You are an architecture review gate. Below is the project ARCHITECTURE document
and a proposed code change. Report ONLY architecture-level violations (layering,
dependency direction, module boundaries, responsibility leaks).

ARCHITECTURE.md:
---
${arch_doc}
---

Proposed code:
---
${content}
---

Reply with ONLY one violation per line in EXACTLY this format:
error|gate3|<short message>
If there are no architecture violations, reply with the single word: PASS"

# --- Call the model (guarded, fail-open) -------------------------------------
out="$(printf '%s' "$PROMPT" | claude -p --model "$MODEL" --output-format text 2>/dev/null || true)"

if [ -z "$out" ]; then
  hes_log "gate3" "warn" "skip: empty model response (fail-open)"
  exit 0
fi

while IFS= read -r line; do
  [ -n "$line" ] || continue
  case "$line" in
    PASS|pass|Pass) continue ;;
  esac
  printf '%s\n' "$line"
done <<<"$out"

exit 0
