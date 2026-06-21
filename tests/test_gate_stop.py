"""Integration tests for the Stop-hook rescan (gate-stop.sh).

gate-stop.sh runs the real script but against a throwaway HES project (its own
git repo + copied hooks/controller/config/rules), so it exercises the full
git-status -> hes_controller -> decision:block path end to end.
"""

import json
import os
import shutil
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
GATE_STOP = os.path.join(ROOT, ".claude", "hooks", "gate-stop.sh")

# Files a minimal HES-enabled project needs for the Stop rescan to function.
_COPY = [
    ".claude/hooks/gate1-shell.sh",
    ".claude/hooks/lib/common.sh",
    ".claude/config.json",
    ".claude/cache/rules.json",
    "tools/hes_controller.py",
]


def _git(repo, *args):
    subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True
    )


def _make_project(tmp_path):
    for rel in _COPY:
        dst = tmp_path / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(os.path.join(ROOT, rel), dst)
    (tmp_path / "src").mkdir(exist_ok=True)
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "config", "user.email", "t@example.com")
    _git(tmp_path, "config", "user.name", "t")
    (tmp_path / "README").write_text("base\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "base")
    return tmp_path


def _run_stop(project_dir, stop_active=False):
    payload = {"stop_hook_active": stop_active, "session_id": "t"}
    proc = subprocess.run(
        ["bash", GATE_STOP],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(project_dir)),
    )
    assert proc.returncode == 0, proc.stderr
    return proc.stdout.strip()


def test_violating_file_blocks_stop(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "src" / "bad.py").write_text('"""m."""\nprint("x")\n')
    obj = json.loads(_run_stop(proj))
    assert obj["decision"] == "block"
    assert "bad.py" in obj["reason"]


def test_clean_tree_allows_stop(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "src" / "good.py").write_text('"""m."""\n\n\ndef f():\n    return 1\n')
    assert _run_stop(proj) == ""


def test_stop_hook_active_short_circuits(tmp_path):
    proj = _make_project(tmp_path)
    (proj / "src" / "bad.py").write_text('"""m."""\nprint("x")\n')
    # Even with a violation present, an already-active stop must not re-block.
    assert _run_stop(proj, stop_active=True) == ""


def test_non_git_dir_fails_open(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "bad.py").write_text('print("x")\n')
    assert _run_stop(tmp_path) == ""
