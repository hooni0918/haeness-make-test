#!/usr/bin/env bash
set -euo pipefail

# gate1-shell.sh — pure shell/grep gate (0 tokens). Evaluates the PROPOSED
# content in $HES_CONTENT_FILE against the rules in rules.json. Prints zero or
# more pipe-delimited violation lines:  <severity>|gate1|<message>
# ALWAYS exits 0 — violations are DATA on stdout, not exit status.

SELF_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib/common.sh
source "${SELF_DIR}/lib/common.sh"

ROOT="${HES_ROOT:-$(hes_root)}"
CONTENT_FILE="${HES_CONTENT_FILE:-}"
BASENAME="${HES_BASENAME:-}"
RULES="${ROOT}/.claude/cache/rules.json"

# Nothing to do without content or rules.
if [ -z "$CONTENT_FILE" ] || [ ! -f "$CONTENT_FILE" ] || [ ! -f "$RULES" ]; then
  exit 0
fi

rule_count="$(jq -r '.rules | length' "$RULES" 2>/dev/null || echo 0)"
[ -n "$rule_count" ] || rule_count=0

i=0
while [ "$i" -lt "$rule_count" ]; do
  id="$(jq -r ".rules[$i].id // empty" "$RULES")"
  severity="$(jq -r ".rules[$i].severity // \"warn\"" "$RULES")"
  rtype="$(jq -r ".rules[$i].type // empty" "$RULES")"
  pattern="$(jq -r ".rules[$i].pattern // empty" "$RULES")"
  max="$(jq -r ".rules[$i].max // empty" "$RULES")"
  message="$(jq -r ".rules[$i].message // empty" "$RULES")"

  # Does this rule apply to the current basename?
  applies="false"
  while IFS= read -r glob; do
    [ -n "$glob" ] || continue
    if hes_basename_match "$glob" "$BASENAME"; then
      applies="true"
      break
    fi
  done < <(jq -r ".rules[$i].applies[]?" "$RULES")

  if [ "$applies" != "true" ]; then
    i=$((i + 1))
    continue
  fi

  case "$rtype" in
    forbid_pattern)
      m="$(grep -nE "$pattern" "$CONTENT_FILE" || true)"
      if [ -n "$m" ]; then
        while IFS= read -r hit; do
          [ -n "$hit" ] || continue
          lineno="${hit%%:*}"
          printf '%s|gate1|[%s] %s (line %s)\n' "$severity" "$id" "$message" "$lineno"
        done <<<"$m"
      fi
      ;;
    require_pattern)
      # Distinguish "no match" (grep exit 1 -> fire) from a regex ERROR
      # (grep exit >=2 -> skip + log, never a spurious violation/false deny).
      rc=0
      grep -qE "$pattern" "$CONTENT_FILE" 2>/dev/null || rc=$?
      if [ "$rc" -eq 1 ]; then
        printf '%s|gate1|[%s] %s\n' "$severity" "$id" "$message"
      elif [ "$rc" -ge 2 ]; then
        hes_log "gate1" "warn" "invalid regex in require_pattern rule ${id}"
      fi
      ;;
    max_line_length)
      [ -n "$max" ] || max=100
      offenders="$(awk -v max="$max" 'length($0) > max { print NR }' "$CONTENT_FILE" || true)"
      if [ -n "$offenders" ]; then
        while IFS= read -r lineno; do
          [ -n "$lineno" ] || continue
          printf '%s|gate1|[%s] %s (line %s)\n' "$severity" "$id" "$message" "$lineno"
        done <<<"$offenders"
      fi
      ;;
    filename_pattern)
      # Same exit-1 (no match -> fire) vs exit->=2 (regex error -> skip) split.
      rc=0
      printf '%s' "$BASENAME" | grep -qE "$pattern" 2>/dev/null || rc=$?
      if [ "$rc" -eq 1 ]; then
        printf '%s|gate1|[%s] %s\n' "$severity" "$id" "$message"
      elif [ "$rc" -ge 2 ]; then
        hes_log "gate1" "warn" "invalid regex in filename_pattern rule ${id}"
      fi
      ;;
    *)
      # Unknown rule type — skip.
      :
      ;;
  esac

  i=$((i + 1))
done

exit 0
