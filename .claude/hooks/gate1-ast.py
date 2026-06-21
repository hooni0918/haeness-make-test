#!/usr/bin/env python3
"""gate1-ast.py — AST tier for the HES gate (Python only, stdlib `ast`).

Engaged in STRICT mode (HES_STRICT=1) it evaluates forbid rules marked
`match: ast` against the WHOLE file using Python's AST instead of line-oriented
regex — eliminating string/comment false positives and catching multiline and
simple aliased calls (`p = print; p(...)`) that regex structurally cannot. It
reads the same rules.json and the same HES_* env contract as gate1-shell.sh and
prints the same `severity|gate1|[id] message (line N)` lines.

Fails OPEN (prints nothing, exit 0) whenever the content does not parse — the
regex gate (gate1-shell.sh) remains the fallback for non-parseable fragments.
Attribute calls (obj.name(...)) are intentionally NOT flagged, to avoid FPs on
legitimately-named methods. Dependency-free (stdlib only; python3 already
required by the project).
"""

import ast
import fnmatch
import json
import os
import sys

ROOT = (
    os.environ.get("HES_ROOT")
    or os.environ.get("CLAUDE_PROJECT_DIR")
    or os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
RULES_PATH = os.path.join(ROOT, ".claude", "cache", "rules.json")


def _forbidden_call_lines(tree, name):
    """Lines of calls to `name`, direct or via a simple alias (`a = name`)."""
    aliases = {name}
    for node in ast.walk(tree):  # BFS over module body in source order
        if (
            isinstance(node, ast.Assign)
            and isinstance(node.value, ast.Name)
            and node.value.id in aliases
        ):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    aliases.add(tgt.id)
    lines = set()
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id in aliases
        ):
            lines.add(node.lineno)
    return sorted(lines)


def main():
    content_file = os.environ.get("HES_FULL_FILE") or os.environ.get("HES_CONTENT_FILE")
    basename = os.path.basename(os.environ.get("HES_BASENAME", "")).rstrip().lower()
    if not content_file or not os.path.isfile(content_file) or not os.path.isfile(RULES_PATH):
        return 0
    try:
        with open(content_file, encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
    except (OSError, SyntaxError, ValueError):
        return 0  # fail-open: not parseable -> regex gate is the fallback
    try:
        with open(RULES_PATH, encoding="utf-8") as fh:
            rules = json.load(fh).get("rules", [])
    except (OSError, ValueError):
        return 0

    for rule in rules:
        if rule.get("match") != "ast" or rule.get("type") != "forbid_pattern":
            continue
        applies = rule.get("applies") or []
        if not any(fnmatch.fnmatchcase(basename, g.lower()) for g in applies):
            continue
        name = rule.get("name")
        if not name:
            continue
        sev = rule.get("severity", "warn")
        msg = rule.get("message", "")
        disp = "{} — fix: {}".format(msg, rule["fix"]) if rule.get("fix") else msg
        for lineno in _forbidden_call_lines(tree, name):
            print("{}|gate1|[{}] {} (line {})".format(sev, rule.get("id"), disp, lineno))
    return 0


if __name__ == "__main__":
    sys.exit(main())
