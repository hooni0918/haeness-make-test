"""Regression tests for the Tier-1 hardening of the PreToolUse gate.

These pin the holes closed: self-modification of the control plane, path
traversal past the ignore list, and the fix-hint in deny reasons. They drive
the real shell hooks via subprocess so a regression in router.sh / gate1 fails
CI, not just the Python wrappers.
"""

import hashlib
import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROUTER = os.path.join(ROOT, ".claude", "hooks", "router.sh")


def _run_router(file_path, content, extra_env=None, project_dir=ROOT):
    """Pipe a Write tool-call through router.sh; return (decision, reason).

    decision is 'deny', 'inform' (plain-text warn output), or 'allow' (silent).
    """
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": file_path, "content": content},
    }
    env = dict(os.environ, CLAUDE_PROJECT_DIR=project_dir)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["bash", ROUTER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return "allow", ""
    try:
        obj = json.loads(out)
        hs = obj["hookSpecificOutput"]
        return hs["permissionDecision"], hs["permissionDecisionReason"]
    except (ValueError, KeyError):
        return "inform", out


# --- (1) self-protection of the control plane -----------------------------

def test_self_modify_rules_json_is_denied():
    decision, reason = _run_router(
        os.path.join(ROOT, ".claude", "cache", "rules.json"), '{"rules":[]}'
    )
    assert decision == "deny"
    assert "hes-self-protect" in reason


def test_self_modify_a_hook_is_denied():
    decision, reason = _run_router(
        os.path.join(ROOT, ".claude", "hooks", "router.sh"), "echo pwned\n"
    )
    assert decision == "deny"
    assert "hes-self-protect" in reason


def test_self_modify_override_env_allows():
    decision, _ = _run_router(
        os.path.join(ROOT, ".claude", "config.json"),
        '{"mode":"warn"}',
        extra_env={"HES_ALLOW_SELF_EDIT": "1"},
    )
    assert decision == "allow"


# --- (2) path-traversal can no longer dodge the ignore list ----------------

def test_path_traversal_into_ignored_dir_is_denied():
    # '<root>/tools/../src/foo.py' resolves to src/foo.py (a gated path) but the
    # literal string contains 'tools/' (an ignore substring). Before normpath
    # this was silently allowed.
    decision, reason = _run_router(
        os.path.join(ROOT, "tools", "..", "src", "foo.py"),
        '"""m."""\nprint("x")\n',
    )
    assert decision == "deny"
    assert "no-print" in reason


# --- (4) fix-hint flows into the deny reason -------------------------------

def test_naive_print_denied_with_fix_hint():
    decision, reason = _run_router(
        os.path.join(ROOT, "src", "foo.py"), '"""m."""\nprint("x")\n'
    )
    assert decision == "deny"
    assert "no-print" in reason
    assert "fix:" in reason  # actionable remediation, not just the violation


def test_clean_source_is_not_denied():
    decision, _ = _run_router(
        os.path.join(ROOT, "src", "foo.py"), '"""m."""\n\n\ndef f():\n    return 1\n'
    )
    assert decision != "deny"


# --- (3) staleness guard (hash-based, via the real router path) -------------
# The warning lives in router.sh (not gate1), keyed on the source hash embedded
# in rules.json — so it surfaces interactively but never pollutes the [rule-id]
# stream that bench_rules.py / hes_controller.py parse from gate1.

def _mini_root(tmp_path, conventions_text, recorded_sha):
    """A throwaway project root the real router.sh can run against: config +
    compiled rules (carrying a recorded source hash) + CONVENTIONS.md. The hook
    scripts still come from this repo (router resolves them by its own path)."""
    (tmp_path / ".claude" / "cache").mkdir(parents=True)
    (tmp_path / ".claude" / "config.json").write_text(
        json.dumps(
            {
                "mode": "enforce",
                "source_globs": ["*.py"],
                "ignore_path_substrings": [],
                "ignore_basename_globs": [],
                "gates": {"gate1": {"enabled": True}},
            }
        )
    )
    (tmp_path / ".claude" / "cache" / "rules.json").write_text(
        json.dumps({"version": 1, "source_sha256": recorded_sha, "rules": []})
    )
    (tmp_path / "CONVENTIONS.md").write_text(conventions_text)
    return tmp_path


def test_stale_rules_warns_when_hash_differs(tmp_path):
    root = _mini_root(tmp_path, "# rules v2\n", recorded_sha="0" * 64)
    decision, reason = _run_router(
        str(root / "x.py"), "x = 1\n", project_dir=str(root)
    )
    assert decision == "inform"
    assert "stale-rules" in reason


def test_no_stale_warning_when_hash_matches(tmp_path):
    text = "# rules v2\n"
    sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
    root = _mini_root(tmp_path, text, recorded_sha=sha)
    decision, _ = _run_router(str(root / "x.py"), "x = 1\n", project_dir=str(root))
    assert decision == "allow"
