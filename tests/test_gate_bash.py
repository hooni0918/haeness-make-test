"""Tests for the PreToolUse Bash gate (gate-bash.sh).

It pre-blocks ONLY Bash writes to the HES control plane; everything else is
allowed (the Stop rescan is the net for general source writes).
"""

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE_BASH = os.path.join(ROOT, ".claude", "hooks", "gate-bash.sh")


def _decision(command, extra_env=None):
    payload = {"tool_name": "Bash", "tool_input": {"command": command}}
    env = dict(os.environ, CLAUDE_PROJECT_DIR=ROOT)
    if extra_env:
        env.update(extra_env)
    proc = subprocess.run(
        ["bash", GATE_BASH],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=env,
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return "allow"
    return json.loads(out)["hookSpecificOutput"]["permissionDecision"]


def test_redirect_into_rules_json_denied():
    assert _decision("echo '{}' > %s/.claude/cache/rules.json" % ROOT) == "deny"


def test_append_into_config_denied():
    assert _decision("echo x >> %s/.claude/config.json" % ROOT) == "deny"


def test_sed_inplace_on_hook_denied():
    assert _decision("sed -i s/a/b/ %s/.claude/hooks/router.sh" % ROOT) == "deny"


def test_tee_conventions_denied():
    assert _decision("foo | tee %s/CONVENTIONS.md" % ROOT) == "deny"


def test_override_env_allows():
    d = _decision(
        "echo x > %s/.claude/config.json" % ROOT,
        extra_env={"HES_ALLOW_SELF_EDIT": "1"},
    )
    assert d == "allow"


def test_reading_control_plane_allowed():
    # A read (no write operator) must not be blocked.
    assert _decision("cat %s/.claude/config.json 2>/dev/null" % ROOT) == "allow"
    assert _decision("grep -r foo %s/.claude/hooks/" % ROOT) == "allow"


def test_normal_source_write_allowed():
    # Not control-plane -> allowed here; gate-stop.sh is the net for these.
    assert _decision("echo 'print(1)' > /tmp/hes_notes.py") == "allow"


def test_benign_commands_allowed():
    for c in ["ls -la", "python app.py", "mvn package", "git status"]:
        assert _decision(c) == "allow"
