"""Tests for tools/parse_conventions.py (CONVENTIONS.md -> rules.json)."""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

from parse_conventions import parse_rules


def test_parses_rule_blocks_with_typed_values():
    text = (
        "prose before\n"
        "```rule\n"
        "id: no-print\n"
        "severity: error\n"
        "applies: *.py, *.swift\n"
        "type: forbid_pattern\n"
        "pattern: print\\(\n"
        "message: no print\n"
        "```\n"
        "prose between\n"
        "```rule\n"
        "id: max-line\n"
        "severity: warn\n"
        "applies: *.py\n"
        "type: max_line_length\n"
        "max: 100\n"
        "message: too long\n"
        "```\n"
    )
    rules = parse_rules(text)
    assert len(rules) == 2
    assert rules[0]["applies"] == ["*.py", "*.swift"]
    assert rules[0]["pattern"] == "print\\("  # verbatim, no backslash mangling
    assert rules[1]["max"] == 100


def test_non_rule_fences_are_ignored():
    text = "```python\nprint('not a rule')\n```\n"
    assert parse_rules(text) == []


def test_unterminated_block_is_skipped(capsys):
    text = "```rule\nid: dangling\nseverity: warn\n"
    assert parse_rules(text) == []
    assert "unterminated" in capsys.readouterr().err


def test_malformed_max_skips_block_and_continues(capsys):
    text = (
        "```rule\nid: bad\nmax: ten\nmessage: x\n```\n"
        "```rule\nid: good\nseverity: warn\nmessage: y\n```\n"
    )
    rules = parse_rules(text)
    assert [r["id"] for r in rules] == ["good"]
    assert "malformed" in capsys.readouterr().err


def test_unknown_keys_are_ignored_with_warning(capsys):
    text = "```rule\nid: k\nbogus: nope\nmessage: m\n```\n"
    rules = parse_rules(text)
    assert rules == [{"id": "k", "message": "m"}]
    assert "unknown key" in capsys.readouterr().err
