"""Tests for tools/skill_adapter.py (Layer 3 structural validation)."""

import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

from skill_adapter import kebabify, parse_frontmatter, validate_and_normalize


VALID = """---
name: my-skill
description: Does one thing well.
---

# My Skill

Body text.
"""


def test_valid_candidate_passes_unchanged():
    result, normalized = validate_and_normalize(VALID)
    assert result["valid"] is True
    assert result["name"] == "my-skill"
    assert result["description"] == "Does one thing well."
    assert result["problems"] == []
    assert normalized.startswith("---\nname: my-skill\n")
    assert "# My Skill" in normalized


def test_non_kebab_name_is_normalized_with_problem_note():
    text = VALID.replace("name: my-skill", "name: My Skill")
    result, _ = validate_and_normalize(text)
    assert result["valid"] is True
    assert result["name"] == "my-skill"
    assert any("kebab" in p for p in result["problems"])


def test_missing_description_is_invalid():
    text = VALID.replace("description: Does one thing well.", "")
    result, normalized = validate_and_normalize(text)
    assert result["valid"] is False
    assert normalized is None


def test_missing_frontmatter_is_invalid():
    result, _ = validate_and_normalize("# Just a doc\n\nNo frontmatter here.\n")
    assert result["valid"] is False
    assert any("fence" in p for p in result["problems"])


def test_unterminated_frontmatter_is_invalid():
    result, _ = validate_and_normalize("---\nname: x\ndescription: y\n")
    assert result["valid"] is False
    assert any("unterminated" in p for p in result["problems"])


def test_quoted_values_are_stripped():
    text = VALID.replace("name: my-skill", 'name: "my-skill"')
    result, _ = validate_and_normalize(text)
    assert result["valid"] is True
    assert result["name"] == "my-skill"


def test_kebabify_unusable_input_yields_empty():
    assert kebabify("  ___  ") == ""
    assert kebabify("Hello World!") == "hello-world"


def test_parse_frontmatter_splits_on_first_colon_only():
    meta, body, err = parse_frontmatter(
        "---\nname: a\ndescription: when: always\n---\nbody\n"
    )
    assert err is None
    assert meta["description"] == "when: always"
    assert body == "body"
