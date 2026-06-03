#!/usr/bin/env python3
"""Parse CONVENTIONS.md rule blocks into .claude/cache/rules.json.

Rules live in fenced code blocks. A fence OPEN line is exactly three backtick
characters immediately followed by the word ``rule`` (``` + "rule"). The block
ends at the next line that is exactly three backticks. Inside a block, each
non-empty line is ``key: value``.

This module is stdlib-only and resolves all paths relative to its own location
(script lives in ``tools/``; project root is its parent dir; output is written
to ``<root>/.claude/cache/rules.json``).

Usage:
    python3 tools/parse_conventions.py
"""

import json
import os
import sys

FENCE = "```"
FENCE_OPEN = "```rule"

# Keys recognized inside a rule block. Anything else is ignored.
KNOWN_KEYS = {"id", "severity", "applies", "type", "pattern", "max", "message"}


def _warn(msg):
    """Print a warning to stderr without aborting the run."""
    sys.stderr.write("warning: {}\n".format(msg))


def _coerce(key, value):
    """Convert a raw string value into its typed representation.

    - 'applies' -> list (split on commas, strip each element)
    - 'max'     -> int
    - everything else -> string, preserved VERBATIM (no backslash mangling)
    """
    if key == "applies":
        return [part.strip() for part in value.split(",")]
    if key == "max":
        return int(value)
    return value


def parse_rules(text):
    """Parse the markdown text and return a list of rule dicts.

    Prose outside rule blocks is ignored. A block whose parsing raises (e.g. a
    non-integer 'max') is skipped with a stderr warning, and parsing continues.
    """
    rules = []
    lines = text.splitlines()
    i = 0
    n = len(lines)

    while i < n:
        # A fence-open line is EXACTLY three backticks followed by "rule",
        # with no other characters (after stripping trailing whitespace only).
        if lines[i].rstrip() == FENCE_OPEN:
            block_start = i
            i += 1
            block_lines = []
            closed = False
            # Collect until the next line that is EXACTLY three backticks.
            while i < n:
                if lines[i].rstrip() == FENCE:
                    closed = True
                    i += 1
                    break
                block_lines.append(lines[i])
                i += 1

            if not closed:
                _warn(
                    "unterminated rule block starting at line {} - skipped".format(
                        block_start + 1
                    )
                )
                continue

            try:
                rule = _parse_block(block_lines, block_start + 1)
            except Exception as exc:  # noqa: BLE001 - keep going on any bad block
                _warn(
                    "malformed rule block at line {}: {} - skipped".format(
                        block_start + 1, exc
                    )
                )
                continue

            if rule is None:
                continue
            rules.append(rule)
        else:
            i += 1

    return rules


def _parse_block(block_lines, block_line_no):
    """Turn the raw lines of one block into a rule dict (or None if empty)."""
    rule = {}
    for raw in block_lines:
        # Non-empty means it has non-whitespace content.
        if raw.strip() == "":
            continue
        if ":" not in raw:
            _warn(
                "ignoring line without ':' in block at line {}: {!r}".format(
                    block_line_no, raw
                )
            )
            continue
        # Only split on the FIRST colon so messages may contain colons.
        key, value = raw.split(":", 1)
        key = key.strip()
        value = value.strip()
        if key not in KNOWN_KEYS:
            _warn(
                "ignoring unknown key {!r} in block at line {}".format(
                    key, block_line_no
                )
            )
            continue
        rule[key] = _coerce(key, value)

    if not rule:
        _warn("empty rule block at line {} - skipped".format(block_line_no))
        return None
    return rule


def main(argv=None):
    # Resolve paths relative to THIS script, not the cwd.
    script_dir = os.path.dirname(os.path.abspath(__file__))
    root = os.path.dirname(script_dir)
    conventions_path = os.path.join(root, "CONVENTIONS.md")
    out_dir = os.path.join(root, ".claude", "cache")
    out_path = os.path.join(out_dir, "rules.json")

    if not os.path.isfile(conventions_path):
        sys.stderr.write(
            "error: CONVENTIONS.md not found at {}\n".format(conventions_path)
        )
        return 1

    with open(conventions_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    rules = parse_rules(text)

    out = {
        "version": 1,
        "generated_from": "CONVENTIONS.md",
        "rules": rules,
    }

    os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, indent=2, ensure_ascii=False)
        fh.write("\n")

    print("wrote {} rules -> {}".format(len(rules), out_path))
    return 0


if __name__ == "__main__":
    sys.exit(main())
