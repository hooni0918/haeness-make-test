"""Tests for tools/v9_eval.py (Layer 2 champion-vs-challenger eval harness).

The model CLI is stubbed: it keys on marker strings embedded in each
meta-prompt, so the two contenders deterministically produce different
quality candidates — entirely offline.
"""

import json
import os
import stat
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

import v9_eval
from v9_eval import decide_winner

GOOD_SKILL = """---
name: tidy-imports
description: Reorder and prune imports whenever a Python file is edited.
---

# Tidy Imports

## Steps
1. Group imports.
"""

BAD_SKILL = """---
name: tidy-imports
---

# Missing description
"""


def _make_meta(path, marker):
    path.write_text(
        "# v9 Meta-Prompt — Skill Author\nversion: 9\n\n{}\n\n"
        "## Quality checklist\n- C1\n".format(marker)
    )


def _setup(tmp_path, monkeypatch, champion_good, challenger_good):
    """v9 dir with marked champion/challenger metas + a marker-keyed stub CLI."""
    v9 = tmp_path / "v9"
    v9.mkdir()
    _make_meta(v9 / "meta_prompt.md", "CHAMPION_MARKER")
    _make_meta(v9 / "meta_prompt.candidate.md", "CHALLENGER_MARKER")
    monkeypatch.setenv("HES_V9_DIR", str(v9))

    (tmp_path / "good.md").write_text(GOOD_SKILL)
    (tmp_path / "bad.md").write_text(BAD_SKILL)
    champ_out = "good.md" if champion_good else "bad.md"
    chall_out = "good.md" if challenger_good else "bad.md"

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "fake-claude"
    stub.write_text(
        "#!/bin/sh\n"
        "prompt=$(cat)\n"
        "case \"$prompt\" in\n"
        "  *'### V9:CRITIQUE ###'*) echo PASS ;;\n"
        "  *CHAMPION_MARKER*) cat '{champ}' ;;\n"
        "  *CHALLENGER_MARKER*) cat '{chall}' ;;\n"
        "  *) echo PASS ;;\n"
        "esac\n".format(champ=tmp_path / champ_out, chall=tmp_path / chall_out)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    monkeypatch.setenv("PATH", "{}{}{}".format(bin_dir, os.pathsep, os.environ["PATH"]))

    goals = tmp_path / "goals.json"
    goals.write_text(json.dumps(["goal one", "goal two"]))
    return goals


def _run(goals, capsys):
    rc = v9_eval.main(["--goals", str(goals), "--claude-cmd", "fake-claude"])
    return rc, json.loads(capsys.readouterr().out)


def test_losing_challenger_is_rejected(tmp_path, monkeypatch, capsys):
    goals = _setup(tmp_path, monkeypatch, champion_good=True, challenger_good=False)
    rc, verdict = _run(goals, capsys)
    assert rc == 1
    assert verdict["winner"] == "champion"
    assert verdict["champion"]["valid"] == 2
    assert verdict["challenger"]["valid"] == 0
    # Verdict file is written for v9_improve to consume as evidence.
    saved = json.loads(open(os.environ["HES_EVAL_VERDICT"]).read())
    assert saved["challenger_sha256"] == verdict["challenger_sha256"]


def test_winning_challenger_exits_zero(tmp_path, monkeypatch, capsys):
    goals = _setup(tmp_path, monkeypatch, champion_good=False, challenger_good=True)
    rc, verdict = _run(goals, capsys)
    assert rc == 0
    assert verdict["winner"] == "challenger"


def test_tie_retains_champion():
    even = {"valid": 2, "problems": 1, "rounds": 1, "errors": 0}
    assert decide_winner(even, dict(even)) == "champion"


def test_tiebreakers_in_priority_order():
    champ = {"valid": 2, "problems": 3, "rounds": 1, "errors": 0}
    # Same validity, fewer problems -> challenger.
    assert decide_winner(champ, {**champ, "problems": 1}) == "challenger"
    # Same validity+problems, fewer rounds -> challenger.
    assert decide_winner(champ, {**champ, "rounds": 0}) == "challenger"
    # Validity dominates everything else.
    assert decide_winner(champ, {**champ, "valid": 1, "problems": 0}) == "champion"
