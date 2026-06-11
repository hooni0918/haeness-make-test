"""Tests for tools/v9_generate.py (Layer 2 generator + quality loop).

The model CLI is stubbed with a tiny shell script keyed on the V9 prompt
sentinels, so every test is offline and deterministic.
"""

import json
import os
import stat
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

import v9_generate

GOOD_SKILL = """---
name: tidy-imports
description: Reorder and prune imports whenever a Python file is edited.
---

# Tidy Imports

## When to use
- A Python file's import block was touched.

## Steps
1. Group stdlib / third-party / local imports.
2. Remove unused imports.

## Guardrails
- Never delete an import with side effects; verify with the test suite.
"""

BAD_SKILL = """---
name: tidy-imports
---

# Missing description
"""


def _install_stub(tmp_path, monkeypatch, generate_md, revise_md, critique_script):
    """Create a fake model CLI handling the three V9 sentinels."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (tmp_path / "gen.md").write_text(generate_md)
    (tmp_path / "rev.md").write_text(revise_md)
    stub = bin_dir / "fake-claude"
    stub.write_text(
        "#!/bin/sh\n"
        "prompt=$(cat)\n"
        "case \"$prompt\" in\n"
        "  *'### V9:GENERATE ###'*) cat '{gen}' ;;\n"
        "  *'### V9:CRITIQUE ###'*) {critique} ;;\n"
        "  *'### V9:REVISE ###'*) cat '{rev}' ;;\n"
        "  *) echo PASS ;;\n"
        "esac\n".format(
            gen=tmp_path / "gen.md", rev=tmp_path / "rev.md", critique=critique_script
        )
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", "{}{}{}".format(bin_dir, os.pathsep, os.environ["PATH"]))
    return "fake-claude"


def _run(argv, capsys):
    rc = v9_generate.main(argv)
    return rc, json.loads(capsys.readouterr().out)


def test_clean_generation_passes_first_round(tmp_path, monkeypatch, capsys):
    cmd = _install_stub(tmp_path, monkeypatch, GOOD_SKILL, GOOD_SKILL, "echo PASS")
    out = tmp_path / "candidate.md"
    rc, summary = _run(
        ["goal text", "--claude-cmd", cmd, "--out", str(out)], capsys
    )
    assert rc == 0
    assert summary["valid"] is True
    assert summary["name"] == "tidy-imports"
    assert summary["rounds_used"] == 0
    assert out.read_text().startswith("---\nname: tidy-imports\n")


def test_critique_problem_triggers_revise_round(tmp_path, monkeypatch, capsys):
    # First critique reports a problem, the second passes (stateful stub).
    state = tmp_path / "critiqued"
    critique = (
        "if [ -f '{0}' ]; then echo PASS; "
        "else touch '{0}'; echo 'problem: steps are vague'; fi".format(state)
    )
    cmd = _install_stub(tmp_path, monkeypatch, GOOD_SKILL, GOOD_SKILL, critique)
    out = tmp_path / "candidate.md"
    rc, summary = _run(
        ["goal text", "--claude-cmd", cmd, "--out", str(out)], capsys
    )
    assert rc == 0
    assert summary["valid"] is True
    assert summary["rounds_used"] == 1


def test_structurally_invalid_result_exits_1(tmp_path, monkeypatch, capsys):
    # Generator and reviser both emit a candidate missing its description, and
    # the critic happily passes it — the deterministic gate must still reject.
    cmd = _install_stub(tmp_path, monkeypatch, BAD_SKILL, BAD_SKILL, "echo PASS")
    rc, summary = _run(
        ["goal text", "--claude-cmd", cmd, "--rounds", "1"], capsys
    )
    assert rc == 1
    assert summary["valid"] is False
    assert summary["out"] is None


def test_missing_model_cli_fails_loud(capsys):
    rc = v9_generate.main(["goal", "--claude-cmd", "definitely-not-a-real-cli"])
    assert rc == 2


def test_strip_outer_fence():
    fenced = "```markdown\n---\nname: a\n---\nbody\n```"
    assert v9_generate.strip_outer_fence(fenced).startswith("---")
    plain = "---\nname: a\n---"
    assert v9_generate.strip_outer_fence(plain) == plain
