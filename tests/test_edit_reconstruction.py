"""⑩ Edit/MultiEdit whole-file reconstruction + strict_whole_file flag.

router.sh reconstructs the would-be post-write file so require_pattern is sound
(no docstring false-positive on a one-line edit), and forbid/max rules are
change-scoped by default but whole-file under strict_whole_file=true.
"""

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROUTER = os.path.join(ROOT, ".claude", "hooks", "router.sh")

_RULES = {
    "version": 1,  # no source_sha256 -> staleness check is skipped
    "rules": [
        {
            "id": "no-print",
            "severity": "error",
            "applies": ["*.py"],
            "type": "forbid_pattern",
            "pattern": r"(^|[^a-zA-Z_.])print[[:space:]]*\(",
            "message": "no print",
        },
        {
            "id": "module-docstring",
            "severity": "warn",
            "applies": ["*.py"],
            "type": "require_pattern",
            "pattern": '"""',
            "message": "module docstring required",
        },
    ],
}


def _mini_root(tmp_path, strict, files):
    cache = tmp_path / ".claude" / "cache"
    cache.mkdir(parents=True)
    (tmp_path / ".claude" / "config.json").write_text(
        json.dumps(
            {
                "mode": "enforce",
                "strict_whole_file": strict,
                "source_globs": ["*.py"],
                "ignore_path_substrings": [],
                "ignore_basename_globs": [],
                "gates": {"gate1": {"enabled": True}},
            }
        )
    )
    (cache / "rules.json").write_text(json.dumps(_RULES))
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
    return tmp_path


def _edit(root, rel, old, new):
    payload = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(root / rel),
            "old_string": old,
            "new_string": new,
        },
    }
    proc = subprocess.run(
        ["bash", ROUTER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return "allow", ""
    try:
        hs = json.loads(out)["hookSpecificOutput"]
        return hs["permissionDecision"], hs["permissionDecisionReason"]
    except (ValueError, KeyError):
        return "inform", out


def test_require_pattern_uses_full_file_no_fp(tmp_path):
    # File already has a docstring; an Edit to an unrelated line (new_string has
    # no docstring) must NOT trigger 'missing docstring' — the ⑩ FP fix.
    root = _mini_root(tmp_path, False, {"src/m.py": '"""doc."""\nx = 1\ny = 2\n'})
    dec, reason = _edit(root, "src/m.py", "x = 1", "x = 11")
    assert dec != "deny"
    assert "docstring" not in reason


def test_nonstrict_forbid_is_change_scoped(tmp_path):
    # Pre-existing print elsewhere; a clean Edit is allowed (default mode).
    root = _mini_root(tmp_path, False, {"src/m.py": '"""d."""\nprint("old")\nx=1\n'})
    dec, _ = _edit(root, "src/m.py", "x=1", "x=2")
    assert dec != "deny"


def test_strict_forbid_sees_whole_file(tmp_path):
    # Same scenario, strict=true -> the pre-existing print blocks the edit.
    root = _mini_root(tmp_path, True, {"src/m.py": '"""d."""\nprint("old")\nx=1\n'})
    dec, reason = _edit(root, "src/m.py", "x=1", "x=2")
    assert dec == "deny"
    assert "no-print" in reason


def test_edit_introducing_print_denied(tmp_path):
    root = _mini_root(tmp_path, False, {"src/m.py": '"""d."""\nx=1\n'})
    dec, reason = _edit(root, "src/m.py", "x=1", 'print("new")')
    assert dec == "deny"
    assert "no-print" in reason


def test_reconstruction_falls_back_when_oldstring_absent(tmp_path):
    # old_string not present -> prepare_content bails -> fragment used -> no crash.
    root = _mini_root(tmp_path, False, {"src/m.py": '"""d."""\nx=1\n'})
    dec, _ = _edit(root, "src/m.py", "NOT_PRESENT", "y=2")
    assert dec != "deny"
