"""Tests for tools/v9_improve.py (auto-feedback + evidence-based promotion).

Promotion is deterministic (no model call), so these tests exercise the real
code path end to end against a tmp v9 dir.
"""

import hashlib
import json
import os
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

import v9_improve

META = "# v9 Meta-Prompt — Skill Author\nversion: 9\n\n## Quality checklist\n- C1\n"
CANDIDATE = "# v9 Meta-Prompt — Skill Author\nversion: 9\n\n## Quality checklist\n- C1 sharpened\n"


def _setup_v9(tmp_path, monkeypatch):
    v9 = tmp_path / "v9"
    v9.mkdir()
    (v9 / "meta_prompt.md").write_text(META)
    (v9 / "meta_prompt.candidate.md").write_text(CANDIDATE)
    monkeypatch.setenv("HES_V9_DIR", str(v9))
    return v9


def _write_verdict(winner, candidate_path):
    sha = hashlib.sha256(open(candidate_path, "rb").read()).hexdigest()
    verdict = {
        "winner": winner,
        "goals": 2,
        "champion": {"valid": 1},
        "challenger": {"valid": 2 if winner == "challenger" else 0},
        "challenger_sha256": sha,
    }
    with open(os.environ["HES_EVAL_VERDICT"], "w") as fh:
        json.dump(verdict, fh)


def test_promote_with_winning_evidence(tmp_path, monkeypatch, capsys):
    v9 = _setup_v9(tmp_path, monkeypatch)
    _write_verdict("challenger", v9 / "meta_prompt.candidate.md")
    rc = v9_improve.main(["--approve"])
    assert rc == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["new_version"] == 10
    assert "version: 10" in (v9 / "meta_prompt.md").read_text()
    assert (v9 / "archive" / "meta_prompt.v9.md").exists()
    assert not (v9 / "meta_prompt.candidate.md").exists()


def test_promote_refuses_losing_candidate(tmp_path, monkeypatch):
    v9 = _setup_v9(tmp_path, monkeypatch)
    _write_verdict("champion", v9 / "meta_prompt.candidate.md")
    assert v9_improve.main(["--approve"]) == 1
    # Nothing moved: live stays v9, candidate stays in place.
    assert "version: 9" in (v9 / "meta_prompt.md").read_text()
    assert (v9 / "meta_prompt.candidate.md").exists()


def test_force_overrides_losing_evidence(tmp_path, monkeypatch, capsys):
    v9 = _setup_v9(tmp_path, monkeypatch)
    _write_verdict("champion", v9 / "meta_prompt.candidate.md")
    assert v9_improve.main(["--approve", "--force"]) == 0
    assert "version: 10" in (v9 / "meta_prompt.md").read_text()


def test_stale_verdict_is_ignored_as_evidence(tmp_path, monkeypatch):
    """A verdict for an OLD candidate must not block (or bless) a new one."""
    v9 = _setup_v9(tmp_path, monkeypatch)
    _write_verdict("champion", v9 / "meta_prompt.candidate.md")
    # Candidate changes after the eval ran -> verdict hash no longer matches.
    (v9 / "meta_prompt.candidate.md").write_text(CANDIDATE + "\nchanged\n")
    assert v9_improve.main(["--approve"]) == 0  # human authority, loud warning


def test_promote_without_any_verdict_warns_but_proceeds(tmp_path, monkeypatch):
    _setup_v9(tmp_path, monkeypatch)
    assert v9_improve.main(["--approve"]) == 0


def test_load_recent_feedback_collects_failures(tmp_path, monkeypatch):
    runs = tmp_path / "runs.jsonl"
    records = [
        {"kind": "generate", "goal": "good goal", "valid": True, "problems": []},
        {
            "kind": "generate",
            "goal": "bad goal",
            "valid": False,
            "problems": ["missing description"],
        },
        {
            "kind": "integrate",
            "status": "regression-failed",
            "name": "broken-skill",
            "detail": "pytest exit 1",
        },
        {"kind": "integrate", "status": "installed", "name": "fine-skill"},
    ]
    runs.write_text("\n".join(json.dumps(r) for r in records) + "\n")
    monkeypatch.setenv("HES_RUNS_FILE", str(runs))

    fb = v9_improve.load_recent_feedback()
    assert "bad goal" in fb
    assert "missing description" in fb
    assert "regression-failed" in fb
    # Successes are not "feedback" — the loop learns from failures.
    assert "good goal" not in fb
    assert "fine-skill" not in fb
