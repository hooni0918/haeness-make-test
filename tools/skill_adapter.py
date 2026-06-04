#!/usr/bin/env python3
"""HES Layer 3 — Skill Authoring Adapter.

Takes a v9-produced "skill candidate" (a markdown file) and validates /
normalizes it into a *valid Claude Code skill candidate*.

A valid candidate is a markdown file whose first block is YAML frontmatter
delimited by lines that are exactly ``---``::

    ---
    name: my-skill
    description: One-line summary of what the skill does.
    ---
    <markdown body...>

Validation rules:
  * frontmatter MUST exist (a leading ``---`` / ``---`` block of ``key: value``)
  * ``name`` MUST be present and kebab-case (``^[a-z0-9]+(-[a-z0-9]+)*$``)
  * ``description`` MUST be present and non-empty

Normalization (best-effort, never fabricates a name):
  * a ``name`` that differs from its kebab-cased form is rewritten to kebab-case
    (e.g. ``My Skill`` -> ``my-skill``); this is recorded as a problem only when
    the *original* was empty/missing (which stays invalid).
  * surrounding whitespace on values is stripped.
  * the body is preserved verbatim.

CLI:
    python3 tools/skill_adapter.py <input.md> [--out <candidate.md>]

Exit 0 if valid, 1 if invalid. A JSON summary is printed to stdout:
    {"valid": bool, "name": str|null, "description": str|null, "problems": []}

Stdlib only. Paths are resolved independently of the current working dir so the
CLI works from anywhere.
"""

import argparse
import json
import os
import re
import sys

KEBAB_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
FENCE = "---"


def kebabify(value):
    """Best-effort convert an arbitrary string to kebab-case.

    Lowercases, replaces any run of non-alphanumeric chars with a single
    hyphen, and trims leading/trailing hyphens. Returns "" if nothing usable
    remains.
    """
    lowered = value.strip().lower()
    # Any run of characters that are NOT [a-z0-9] becomes a single hyphen.
    hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered)
    return hyphenated.strip("-")


def parse_frontmatter(text):
    """Split *text* into (frontmatter_dict, body, error).

    The frontmatter is the block between a leading line that is exactly ``---``
    and the next line that is exactly ``---``. Each non-empty frontmatter line
    is parsed as ``key: value`` (split on the FIRST colon). Lines without a
    colon are ignored.

    Returns ``(meta, body, None)`` on success or ``(None, None, error_str)`` if
    there is no well-formed frontmatter block.
    """
    lines = text.splitlines()
    # Skip a leading UTF-8 BOM / blank lines before the opening fence.
    idx = 0
    while idx < len(lines) and lines[idx].strip() == "":
        idx += 1

    if idx >= len(lines) or lines[idx].strip() != FENCE:
        return None, None, "missing opening frontmatter fence ('---')"

    meta = {}
    j = idx + 1
    closed = False
    while j < len(lines):
        if lines[j].strip() == FENCE:
            closed = True
            j += 1
            break
        raw = lines[j]
        if raw.strip() != "" and ":" in raw:
            key, value = raw.split(":", 1)
            meta[key.strip()] = value.strip()
        j += 1

    if not closed:
        return None, None, "unterminated frontmatter block (missing closing '---')"

    body = "\n".join(lines[j:])
    return meta, body, None


def _strip_quotes(value):
    """Strip a single matching pair of surrounding quotes, if present."""
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def validate_and_normalize(text):
    """Validate *text* and return (result_dict, normalized_text).

    result_dict = {valid, name, description, problems:[...]}.
    normalized_text is the rebuilt candidate (frontmatter + body); it is only
    meaningful / written out when valid.
    """
    problems = []
    meta, body, err = parse_frontmatter(text)

    if err is not None:
        return (
            {"valid": False, "name": None, "description": None, "problems": [err]},
            None,
        )

    raw_name = _strip_quotes(meta.get("name", "").strip())
    raw_desc = _strip_quotes(meta.get("description", "").strip())

    # --- name ---
    final_name = None
    if raw_name == "":
        problems.append("frontmatter is missing a 'name' field")
    else:
        if KEBAB_RE.match(raw_name):
            final_name = raw_name
        else:
            normalized = kebabify(raw_name)
            if normalized and KEBAB_RE.match(normalized):
                final_name = normalized
                problems.append(
                    "'name' {!r} was not kebab-case; normalized to {!r}".format(
                        raw_name, normalized
                    )
                )
            else:
                problems.append(
                    "'name' {!r} cannot be normalized to kebab-case".format(raw_name)
                )

    # --- description ---
    final_desc = None
    if raw_desc == "":
        problems.append("frontmatter is missing a non-empty 'description' field")
    else:
        final_desc = raw_desc

    valid = final_name is not None and final_desc is not None

    result = {
        "valid": valid,
        "name": final_name,
        "description": final_desc,
        "problems": problems,
    }

    normalized_text = None
    if valid:
        body_text = body if body is not None else ""
        # Ensure exactly one blank line between frontmatter and body, and that
        # the body's own leading blank lines are not duplicated.
        body_text = body_text.lstrip("\n")
        normalized_text = (
            "---\n"
            "name: {}\n"
            "description: {}\n"
            "---\n".format(final_name, final_desc)
        )
        if body_text:
            normalized_text += "\n" + body_text
            if not normalized_text.endswith("\n"):
                normalized_text += "\n"

    return result, normalized_text


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="HES Layer 3 Skill Authoring Adapter: validate/normalize a "
        "v9 skill candidate markdown file."
    )
    parser.add_argument("input", help="path to the input markdown file")
    parser.add_argument(
        "--out",
        default=None,
        help="if given, write the normalized candidate to this path (only when valid)",
    )
    args = parser.parse_args(argv)

    input_path = os.path.abspath(os.path.expanduser(args.input))

    if not os.path.isfile(input_path):
        summary = {
            "valid": False,
            "name": None,
            "description": None,
            "problems": ["input file not found: {}".format(input_path)],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    with open(input_path, "r", encoding="utf-8") as fh:
        text = fh.read()

    result, normalized_text = validate_and_normalize(text)

    if result["valid"] and args.out:
        out_path = os.path.abspath(os.path.expanduser(args.out))
        out_dir = os.path.dirname(out_path)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as fh:
            fh.write(normalized_text)
        result["out"] = out_path

    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["valid"] else 1


if __name__ == "__main__":
    sys.exit(main())
