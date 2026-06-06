# HARNESS.md — Operator's Guide

A **layered-gate enforcement harness** that sits between Claude Code and your
source tree. Whenever Claude tries to `Edit`, `Write`, or `MultiEdit` a source
file, a **PreToolUse hook** intercepts the *proposed* content **before it is
written to disk** and runs it through a ladder of gates. Hard (error-severity)
violations cause the hook to **DENY** the write; Claude never touches the file.

This is a Claude↔OS enforcement layer: the rules live in your repo, the OS
runs them via the hook, and they apply to *every* edit regardless of what the
model intends.

---

## The 4-gate ladder (and why it saves tokens)

Changes flow through progressively more expensive gates. Cheap gates run
first and catch most violations, so the expensive ones rarely fire.

| Gate | Engine | Cost | Catches | When it runs |
|------|--------|------|---------|--------------|
| **Gate 1** | Pure shell / `grep` vs `rules.json` | **0 tokens** | Mechanical rules: forbidden patterns (e.g. `print()`), required patterns (e.g. module docstring), filename conventions, max line length | **Always** |
| **Gate 2** | **Haiku** on the diff | ~300 tokens | Semantic smells a regex can't see (naming intent, obvious logic mistakes) | change **≥ 50 lines** *and* enabled |
| **Gate 3** | **Sonnet** on the diff + `ARCHITECTURE.md` | higher | Architectural drift (layering, boundaries, coupling) | change **≥ 200 lines** *and* enabled |
| **Gate 4** | **Human** | — | Anything the machine can't decide | out of scope for this harness |

**Token rationale:** the vast majority of edits are small and are fully judged
by Gate 1 at **zero token cost**. Only larger changes pay for an LLM gate, and
only the diff/content is sent — never the whole repo. Sonnet (Gate 3) is
reserved for big structural changes where architecture review actually matters.

**Gate 1 is the only hard guarantee.** Gates 2 and 3 are **fail-open**: if they
are disabled, the change is below their size threshold, the `claude` CLI is
missing, or the model call errors/times out, they emit **no** violations and the
change proceeds (a warning is logged). They can only *add* protection, never
remove Gate 1's.

---

## Flow

```
Claude proposes an Edit/Write/MultiEdit
            │
            ▼
   PreToolUse hook  ──►  .claude/hooks/router.sh   (reads stdin JSON once)
            │
            ▼
        gate1-shell.sh        (always; 0 tokens)
            │
            ▼
   change ≥ 50 lines AND gate2 enabled?  ──► gate2-semantic.sh   (Haiku, fail-open)
            │
            ▼
   change ≥ 200 lines AND gate3 enabled? ──► gate3-architect.sh  (Sonnet, fail-open)
            │
            ▼
   any error-severity violation?
        ├─ yes ─►  DENY   (emit deny JSON; write is blocked)
        └─ no  ─►  ALLOW  (silent in enforce mode; warnings printed in warn mode)
```

The router collects violation lines from every gate (pipe-delimited
`severity|gate|message`), then decides: **any `error` ⇒ deny**, otherwise allow
(surfacing `warn` lines as information).

---

## File map

| Path | Purpose |
|------|---------|
| `.claude/settings.json` | Wires the `PreToolUse` hook (`matcher: Edit\|Write\|MultiEdit`) to `bash .claude/hooks/router.sh`. |
| `.claude/config.json` | Gate toggles, size thresholds, source globs, and `mode` (`enforce`\|`warn`). |
| `.claude/cache/rules.json` | Machine-readable rules compiled from `CONVENTIONS.md`. Read by Gate 1. |
| `.claude/logs/.gitkeep` | Keeps the logs dir in git; the actual `*.log` files are gitignored. |
| `.claude/logs/gates.log` | Runtime log of gate decisions and warnings (not tracked in git). |
| `.claude/hooks/lib/common.sh` | Shared helpers (`hes_root`, `hes_log`, `hes_deny`, `hes_allow`, `hes_inform`, `hes_basename_match`), sourced by the router and gates. |
| `.claude/hooks/router.sh` | **Single entrypoint.** Reads the PreToolUse JSON from stdin once, runs the gates, emits exactly one decision. |
| `.claude/hooks/gate1-shell.sh` | Gate 1: grep checks against `rules.json` (0 tokens). |
| `.claude/hooks/gate2-semantic.sh` | Gate 2: Haiku on the diff (guarded, fail-open). |
| `.claude/hooks/gate3-architect.sh` | Gate 3: Sonnet architecture review (guarded, fail-open). |
| `tools/parse_conventions.py` | Compiles `CONVENTIONS.md` → `.claude/cache/rules.json`. |
| `CONVENTIONS.md` | Human-readable conventions **plus** machine-parseable rule blocks. |
| `ARCHITECTURE.md` | Architecture doc, read by Gate 3 for context. |
| `HARNESS.md` | This operator's guide. |

---

## The 3 core principles

1. **Parse rules once into a cache.** `CONVENTIONS.md` is the human source of
   truth; `tools/parse_conventions.py` compiles it into `.claude/cache/rules.json`.
   The hook reads only the compiled cache on every edit — no re-parsing of prose,
   no LLM cost for mechanical checks.
2. **Send only the diff/content to LLM gates.** Gates 2 and 3 never see the whole
   repo — just the proposed new code (and, for Gate 3, `ARCHITECTURE.md`). This
   keeps each call to a few hundred tokens.
3. **Pick the gate by change size.** Small changes stop at the free Gate 1. Gate 2
   (Haiku) only engages at ≥ 50 changed lines; Gate 3 (Sonnet) only at ≥ 200.
   You pay for intelligence only when the change is big enough to warrant it.

---

## How to use

### 1. Edit conventions, then refresh the rule cache
Edit the rule blocks in `CONVENTIONS.md`, then recompile the cache:

```bash
python3 tools/parse_conventions.py
```

This regenerates `.claude/cache/rules.json`. Gate 1 picks up the new rules on the
next edit. **Always re-run this after changing `CONVENTIONS.md`** — the hook reads
the cache, not the Markdown.

### 2. Toggle the LLM gates
Edit `.claude/config.json` to turn Gate 2 / Gate 3 on or off, adjust their size
thresholds, and choose the enforcement mode:

- `enabled: true|false` per gate — disable to skip the gate entirely (fail-open).
- `mode: "enforce"` — error-severity violations **block** the write.
- `mode: "warn"` — violations are **printed as information** to the model but the
  write is **allowed** (good for rolling out a new rule without breaking flow).

### 3. Read the logs
Gate decisions and fail-open warnings are appended to:

```
.claude/logs/gates.log
```

Format: `<timestamp> | <gate> | <level> | <message>`. This file is gitignored;
the directory is kept via `.gitkeep`.

---

## How to test manually

You don't need Claude Code running to exercise the harness — just pipe a fake
PreToolUse JSON object into the router. Build the JSON with `jq` so quoting is
always valid. Run these from the **project root**.

### A) A change that should be DENIED (contains `print()`)

```bash
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'def divide(a, b):\n    print("debugging")\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

Expected output — the deny decision. The reason is built as
`Blocked by HES gate: ` followed by each error rule's `message` (the internal
`error|gate1|…` pipe encoding is stripped and never appears here):

```json
{
  "hookSpecificOutput": {
    "hookEventName": "PreToolUse",
    "permissionDecision": "deny",
    "permissionDecisionReason": "Blocked by HES gate: [no-print] print() is forbidden — use the logging module (line 2)"
  }
}
```

When Claude Code receives this, the write is **blocked**.

### B) A clean change that should be ALLOWED

```bash
jq -nc \
  --arg fp "$PWD/src/calculator.py" \
  --arg c $'"""Calculator module."""\n\n\ndef divide(a, b):\n    return a / b\n' \
  '{tool_name:"Write", tool_input:{file_path:$fp, content:$c}}' \
| bash .claude/hooks/router.sh
```

Expected: **no output, exit code 0** (silent allow). In `warn` mode you may see
plain-text warnings instead of JSON, but the write still proceeds.

> Tip: an `Edit` payload uses `tool_input.new_string` (and `old_string`) instead
> of `tool_input.content`; a `MultiEdit` payload uses `tool_input.edits[]` (an
> array of `{old_string,new_string}`). The router handles all three shapes.

---

## iOS / Swift support (implemented)

The harness is language-agnostic — it keys off file globs and regex rules — so
the same Layer-0 gate enforces Swift conventions too. This is no longer
hypothetical: `*.swift` rules ship in `CONVENTIONS.md`, a clean SwiftUI sample
lives in `samples/ios/`, and the gate is verified end-to-end against it.

**Swift rules in force** (`applies: *.swift`, compiled into `rules.json`):

| id | severity | catches |
|----|----------|---------|
| `swift-no-print` | error | `print(` — use `os.Logger` instead |
| `swift-no-force-cast` | error | `as!` force casts |
| `swift-no-force-try` | error | `try!` force tries |
| `swift-no-force-unwrap` | warn | heuristic force-unwrap `x!` |
| `swift-max-line-120` | warn | lines over 120 cols (SwiftLint default) |

**Cross-engine regex.** The token rules use a branch form (`^kw!|[^word]kw!`)
that works on BSD grep, GNU grep, and ugrep alike. Heads-up: if your local
`grep` is ugrep, its `(^|[^…])` group silently misses some keywords (`try!` at
column 0 in particular), which is why the branch form is deliberate. Indented
Swift — every real case — is caught on all three engines.

**Verify it yourself:**

```bash
# clean SwiftUI sample -> silent allow
jq -nc --arg fp "$PWD/samples/ios/CounterView.swift" \
  --rawfile c samples/ios/CounterView.swift \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' \
| bash .claude/hooks/router.sh          # no output = allow

# print / force-cast / force-try -> deny
jq -nc --arg fp "$PWD/Bad.swift" \
  --arg c $'func f() {\n    print("x")\n    let s = a as! String\n    let d = try! load()\n}\n' \
  '{tool_name:"Write",tool_input:{file_path:$fp,content:$c}}' \
| bash .claude/hooks/router.sh          # permissionDecision: deny
```

To add or change Swift rules, edit the `*.swift` rule blocks in `CONVENTIONS.md`
and re-run `python3 tools/parse_conventions.py`. `source_globs` in
`.claude/config.json` already includes `*.swift`; `settings.json` and the router
need no changes.
