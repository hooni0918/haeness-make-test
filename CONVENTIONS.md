# Coding Conventions

These conventions are **ENFORCED** by the HES (Hook-Enforced Standards) gate harness.
When you Edit, Write, or MultiEdit a source file, a PreToolUse hook intercepts the
proposed content *before* it is written and runs a series of gates against it.
Gate 1 is a pure shell/grep pass (0 tokens) that evaluates the machine-readable rule
blocks below. Hard (error-severity) violations cause the write to be **denied**.

The prose in this file explains the intent; the fenced `rule` blocks under
"Rules (machine-readable)" are the source of truth that the harness parses into
`.claude/cache/rules.json`.

## Principles

- **Prefer logging over `print()`.** Diagnostic output belongs in the `logging`
  module, not in `print()` calls. `print()` is forbidden in source files.
- **Use explicit imports — no wildcards.** Never write `from module import *`.
  Import the specific names you use so dependencies stay visible and tooling works.
- **Write module docstrings.** Every module should begin with a `"""docstring"""`
  describing what it contains.
- **Keep lines reasonable.** Lines should be at most 100 columns wide.
- **Use snake_case Python filenames.** Python file basenames should match
  `snake_case` (lowercase letters, digits, and underscores).

## Rules (machine-readable)

```rule
id: no-print
severity: error
applies: *.py
type: forbid_pattern
pattern: (^|[^a-zA-Z_.])print[[:space:]]*\(
message: print() is forbidden — use the logging module
```

```rule
id: no-wildcard-import
severity: error
applies: *.py
type: forbid_pattern
pattern: ^[[:space:]]*from[[:space:]]+[^[:space:]]+[[:space:]]+import[[:space:]]+\*
message: wildcard imports (from x import *) are forbidden
```

```rule
id: module-docstring
severity: warn
applies: *.py
type: require_pattern
pattern: """
message: module should start with a docstring
```

```rule
id: max-line-100
severity: warn
applies: *.py
type: max_line_length
max: 100
message: line exceeds 100 characters
```

```rule
id: py-snake-case-file
severity: warn
applies: *.py
type: filename_pattern
pattern: ^[a-z_][a-z0-9_]*\.py$
message: Python files should be snake_case
```
