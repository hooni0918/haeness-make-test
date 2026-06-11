#!/usr/bin/env bash
set -euo pipefail

# skill_pipeline.sh — HES Layer 2->4 orchestrator. The one-command version of
# the README §4 flow:
#
#   v9 generates a skill            (Layer 2: tools/v9_generate.py)
#         |
#   v9 first-pass quality loop      (Layer 2: critique/revise inside the generator)
#         |
#   HES verifies role/conflict/     (Layer 0+1+3: skill_adapter via
#   regression                       skill_integrate.sh steps a-c)
#         |
#   AI Reviewer advisory            (Layer 1: tools/ai_review.sh, step d)
#         |
#   HUMAN approves                  (Gate 4: --approve, step e)
#         |
#   install into .claude/skills/    (Layer 4: step f)
#
# Without --approve this stops at the human gate: full verdict, NOTHING
# installed. The human gate lives in skill_integrate.sh and is NOT bypassable
# from here — this script only forwards the flag.
#
# Usage: bash tools/skill_pipeline.sh "<goal>" [--rounds N] [--model M]
#                                     [--out PATH] [--approve]

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${SELF_DIR}/.." && pwd)"

GENERATOR="${SELF_DIR}/v9_generate.py"
BRIDGE="${SELF_DIR}/skill_integrate.sh"

die() {
  printf 'ABORT: %s\n' "$1" >&2
  exit "${2:-1}"
}

[ -f "$GENERATOR" ] || die "v9_generate.py not found at $GENERATOR"
[ -f "$BRIDGE" ] || die "skill_integrate.sh not found at $BRIDGE"
command -v python3 >/dev/null 2>&1 || die "python3 not found on PATH"

# --- arg parsing --------------------------------------------------------------
GOAL=""
APPROVE="false"
GEN_ARGS=()
while [ "$#" -gt 0 ]; do
  case "$1" in
    --approve) APPROVE="true" ;;
    --rounds | --model | --out | --claude-cmd | --timeout)
      [ "$#" -ge 2 ] || die "flag $1 needs a value"
      GEN_ARGS+=("$1" "$2")
      shift
      ;;
    -h | --help)
      printf 'Usage: bash tools/skill_pipeline.sh "<goal>" [--rounds N] [--model M] [--out PATH] [--approve]\n'
      exit 0
      ;;
    -*)
      die "unknown flag: $1"
      ;;
    *)
      if [ -z "$GOAL" ]; then
        GOAL="$1"
      else
        die "unexpected extra argument: $1"
      fi
      ;;
  esac
  shift
done
[ -n "$GOAL" ] || die 'missing required argument: "<goal>"'

printf '=== HES Skill Pipeline (Layer 2 -> 4) ===\n'
printf 'goal:    %s\n' "$GOAL"
printf 'approve: %s\n\n' "$APPROVE"

# --- stage 1: Layer 2 — generate + first-pass quality loop --------------------
printf '[1/2] GENERATE + QUALITY (Layer 2) ...\n'
GEN_RC=0
GEN_JSON="$(python3 "$GENERATOR" "$GOAL" ${GEN_ARGS[@]+"${GEN_ARGS[@]}"})" || GEN_RC=$?
if [ "$GEN_RC" -ne 0 ]; then
  printf '%s\n' "$GEN_JSON"
  die "Layer 2 generation failed (exit ${GEN_RC}); nothing to integrate." "$GEN_RC"
fi

CANDIDATE="$(printf '%s' "$GEN_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin)["out"] or "")' 2>/dev/null || true)"
[ -n "$CANDIDATE" ] || die "could not read candidate path from generator output."
printf '    -> candidate: %s\n\n' "$CANDIDATE"

# --- stage 2: Layer 0/1/3/4 — adapter, conflict, regression, AI review,
#     human gate, install (all inside skill_integrate.sh) ----------------------
printf '[2/2] INTEGRATE (Layer 0/1/3/4) ...\n'
if [ "$APPROVE" = "true" ]; then
  bash "$BRIDGE" "$CANDIDATE" --approve
else
  bash "$BRIDGE" "$CANDIDATE"
fi
