#!/usr/bin/env bash
set -euo pipefail

# skill_integrate.sh — HES Layer 4 V9->HES Integration Bridge.
#
# Takes a v9-produced "skill candidate" markdown file and safely integrates it
# as a Claude Code skill ONLY after passing HES checks AND explicit human
# approval. Pipeline (each step printed):
#   a. ADAPTER     — validate/normalize via tools/skill_adapter.py; abort if invalid.
#   b. CONFLICT    — reject if .claude/skills/<name>/ already exists.
#   c. REGRESSION  — if tests/ + pytest present, run 'pytest -q'; must pass.
#   d. AI REVIEW   — if tools/ai_review.sh exists, call it (advisory only).
#   e. HUMAN GATE  — without --approve: print verdict, instruct re-run, EXIT 0,
#                    DO NOT install.
#   f. INSTALL     — with --approve AND all prior steps OK: create
#                    .claude/skills/<name>/SKILL.md from the candidate.
#
# The human gate is a HARD requirement: NEVER install without --approve.
#
# Usage: bash tools/skill_integrate.sh <candidate.md> [--approve]

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SELF_DIR}/.." && pwd)"

# Pull in hes_log if available; otherwise define a no-frills fallback.
COMMON="${ROOT}/.claude/hooks/lib/common.sh"
if [ -f "$COMMON" ]; then
  # shellcheck source=/dev/null
  source "$COMMON"
fi
if ! declare -F hes_log >/dev/null 2>&1; then
  hes_log() { printf '[log] %s | %s | %s\n' "${1:-?}" "${2:-?}" "${3:-}" >&2; }
fi

# --- temp workspace (normalized candidate lands here) -----------------------
WORKDIR="$(mktemp -d "${TMPDIR:-/tmp}/hes_skill_integrate.XXXXXX")"
cleanup() { rm -rf "$WORKDIR" 2>/dev/null || true; }
trap cleanup EXIT

die() {
  printf 'ABORT: %s\n' "$1" >&2
  exit "${2:-1}"
}

# --- arg parsing ------------------------------------------------------------
CANDIDATE=""
APPROVE="false"
for arg in "$@"; do
  case "$arg" in
    --approve) APPROVE="true" ;;
    -h | --help)
      printf 'Usage: bash tools/skill_integrate.sh <candidate.md> [--approve]\n'
      exit 0
      ;;
    -*)
      die "unknown flag: $arg"
      ;;
    *)
      if [ -z "$CANDIDATE" ]; then
        CANDIDATE="$arg"
      else
        die "unexpected extra argument: $arg"
      fi
      ;;
  esac
done

[ -n "$CANDIDATE" ] || die "missing required argument: <candidate.md>"
[ -f "$CANDIDATE" ] || die "candidate file not found: $CANDIDATE"

ADAPTER_PY="${ROOT}/tools/skill_adapter.py"
[ -f "$ADAPTER_PY" ] || die "skill_adapter.py not found at $ADAPTER_PY"

printf '=== HES Layer 4 — Skill Integration Bridge ===\n'
printf 'candidate: %s\n' "$CANDIDATE"
printf 'approve:   %s\n\n' "$APPROVE"

# --- step a: ADAPTER --------------------------------------------------------
printf '[a] ADAPTER: validating/normalizing candidate ...\n'
NORMALIZED="${WORKDIR}/SKILL.md"
ADAPTER_OUT=""
ADAPTER_RC=0
ADAPTER_OUT="$(python3 "$ADAPTER_PY" "$CANDIDATE" --out "$NORMALIZED" 2>&1)" || ADAPTER_RC=$?
printf '%s\n' "$ADAPTER_OUT"

if [ "$ADAPTER_RC" -ne 0 ]; then
  hes_log "layer4" "error" "adapter rejected candidate: $CANDIDATE"
  die "adapter reports the candidate is INVALID (exit ${ADAPTER_RC}); not integrating." "$ADAPTER_RC"
fi
[ -f "$NORMALIZED" ] || die "adapter reported valid but produced no normalized candidate."

# Extract the skill name from the normalized candidate's JSON summary.
SKILL_NAME="$(printf '%s' "$ADAPTER_OUT" | python3 -c 'import sys,json; print(json.load(sys.stdin)["name"])' 2>/dev/null || true)"
[ -n "$SKILL_NAME" ] || die "could not determine skill name from adapter output."
printf '    -> valid; skill name = %s\n\n' "$SKILL_NAME"

# --- step b: CONFLICT -------------------------------------------------------
printf '[b] CONFLICT: checking for an existing skill named %s ...\n' "$SKILL_NAME"
SKILL_DIR="${ROOT}/.claude/skills/${SKILL_NAME}"
if [ -e "$SKILL_DIR" ]; then
  hes_log "layer4" "error" "name collision for skill: $SKILL_NAME"
  die "a skill named '${SKILL_NAME}' already exists at ${SKILL_DIR}; refusing to overwrite." 2
fi
printf '    -> no collision.\n\n'

# --- step c: REGRESSION -----------------------------------------------------
printf '[c] REGRESSION: checking for a test suite ...\n'
PYTEST_BIN=""
if command -v pytest >/dev/null 2>&1; then
  PYTEST_BIN="pytest"
elif python3 -m pytest --version >/dev/null 2>&1; then
  PYTEST_BIN="python3 -m pytest"
fi

if [ -d "${ROOT}/tests" ] && [ -n "$PYTEST_BIN" ]; then
  printf '    -> tests/ + pytest found; running "%s -q" ...\n' "$PYTEST_BIN"
  PYTEST_RC=0
  # Run from ROOT so relative imports in tests resolve.
  ( cd "$ROOT" && $PYTEST_BIN -q ) || PYTEST_RC=$?
  if [ "$PYTEST_RC" -ne 0 ]; then
    hes_log "layer4" "error" "regression suite FAILED before installing $SKILL_NAME"
    die "regression suite FAILED (pytest exit ${PYTEST_RC}); a new skill must not break the repo." "$PYTEST_RC"
  fi
  printf '    -> regression suite PASSED.\n\n'
else
  printf '    -> no regression suite (tests/ dir or pytest absent); continuing.\n\n'
fi

# --- step d: AI REVIEW (advisory) ------------------------------------------
printf '[d] AI REVIEW: looking for tools/ai_review.sh ...\n'
AI_REVIEW="${ROOT}/tools/ai_review.sh"
AI_VERDICT="(skipped — tools/ai_review.sh not present)"
if [ -f "$AI_REVIEW" ]; then
  printf '    -> found; requesting advisory opinion ...\n'
  AI_OUT=""
  AI_OUT="$(bash "$AI_REVIEW" <"$NORMALIZED" 2>&1 || true)"
  printf '%s\n' "$AI_OUT"
  AI_VERDICT="$AI_OUT"
else
  printf '    -> %s\n' "$AI_VERDICT"
fi
printf '\n'

# --- step e: HUMAN GATE -----------------------------------------------------
printf '=== VERDICT ===\n'
printf '  candidate : %s\n' "$CANDIDATE"
printf '  skill name: %s\n' "$SKILL_NAME"
printf '  adapter   : VALID\n'
printf '  conflict  : none\n'
printf '  regression: PASS / not-applicable\n'
printf '  ai review : %s\n' "$AI_VERDICT"
printf '  install to: %s/SKILL.md\n' "$SKILL_DIR"
printf '===============\n\n'

if [ "$APPROVE" != "true" ]; then
  printf '[e] HUMAN GATE: --approve was NOT passed. NOT installing.\n'
  printf '    Re-run with --approve to install.\n'
  hes_log "layer4" "info" "human gate held skill $SKILL_NAME (no --approve)"
  exit 0
fi
printf '[e] HUMAN GATE: --approve passed; proceeding to install.\n\n'

# --- step f: INSTALL --------------------------------------------------------
printf '[f] INSTALL: installing skill %s ...\n' "$SKILL_NAME"
mkdir -p "$SKILL_DIR"
cp "$NORMALIZED" "${SKILL_DIR}/SKILL.md"
printf '    -> installed: %s/SKILL.md\n' "$SKILL_DIR"
hes_log "layer4" "info" "installed skill $SKILL_NAME at ${SKILL_DIR}/SKILL.md"
exit 0
