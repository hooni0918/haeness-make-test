#!/usr/bin/env python3
"""Reconstruct the would-be post-write file for an Edit/MultiEdit tool call.

Reads the PreToolUse JSON on stdin, reads the current on-disk file, applies the
edit(s) in memory (matching the Edit/MultiEdit tool's first-occurrence /
replace_all semantics), and prints the resulting WHOLE file to stdout. This lets
the gate evaluate whole-file rules (require_pattern, AST) against what the file
will actually look like, not just the changed fragment.

Exits non-zero and prints nothing whenever reconstruction is not safe (file
missing, old_string absent or ambiguous) so the caller can fall back to the
proposed fragment. stdlib-only.
"""

import json
import sys


def main():
    try:
        payload = json.loads(sys.stdin.read())
    except ValueError:
        return 2

    tool = payload.get("tool_name")
    ti = payload.get("tool_input") or {}
    file_path = ti.get("file_path")
    if not file_path:
        return 2

    if tool == "Edit":
        edits = [ti]
    elif tool == "MultiEdit":
        edits = ti.get("edits") or []
    else:
        return 2

    try:
        with open(file_path, "r", encoding="utf-8") as fh:
            content = fh.read()
    except OSError:
        return 2  # no on-disk file (e.g. brand-new) -> fall back to fragment

    for edit in edits:
        old = edit.get("old_string", "")
        new = edit.get("new_string", "")
        if old == "":
            return 2  # creation/whole-replace semantics vary; bail to fragment
        if edit.get("replace_all"):
            if old not in content:
                return 2
            content = content.replace(old, new)
        else:
            if content.count(old) != 1:
                return 2  # absent or ambiguous -> cannot reconstruct safely
            content = content.replace(old, new, 1)

    sys.stdout.write(content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
