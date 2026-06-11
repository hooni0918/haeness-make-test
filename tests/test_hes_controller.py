"""Tests for tools/hes_controller.py (Layer 1 batch controller)."""

import os
import stat
import sys

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools")
)

from hes_controller import gate_file, is_source_file, parse_violation

CFG = {
    "mode": "enforce",
    "source_globs": ["*.py", "*.swift"],
    "ignore_path_substrings": ["tests/", "tools/"],
    "ignore_basename_globs": ["test_*.py"],
}


# --- is_source_file -----------------------------------------------------------
def test_source_glob_match():
    assert is_source_file("src/calculator.py", CFG) is True
    assert is_source_file("src/readme.md", CFG) is False


def test_ignore_path_substring_wins():
    assert is_source_file("tools/helper.py", CFG) is False
    assert is_source_file("tests/anything.py", CFG) is False


def test_ignore_basename_glob_wins():
    assert is_source_file("src/test_foo.py", CFG) is False


# --- parse_violation ----------------------------------------------------------
def test_parse_violation_normal():
    v = parse_violation("error|gate1|[no-print] forbidden (line 2)")
    assert v == {
        "severity": "error",
        "gate": "gate1",
        "message": "[no-print] forbidden (line 2)",
    }


def test_parse_violation_extra_pipes_stay_in_message():
    v = parse_violation("warn|gate2|msg|with|pipes")
    assert v["message"] == "msg|with|pipes"


def test_parse_violation_malformed_becomes_warn():
    v = parse_violation("garbage line without pipes")
    assert v["severity"] == "warn"
    assert v["gate"] == "?"


def test_parse_violation_unknown_severity_downgraded_to_warn():
    assert parse_violation("fatal|gate1|boom")["severity"] == "warn"


# --- gate2 short-circuit (mirrors router.sh) -----------------------------------
def _make_stub_claude(tmp_path, marker):
    """Install a fake `claude` on PATH that records being called."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stub = bin_dir / "claude"
    stub.write_text(
        "#!/bin/sh\ncat >/dev/null\ntouch '{}'\necho PASS\n".format(marker)
    )
    stub.chmod(stub.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return bin_dir


def _gate2_cfg(mode):
    return {
        "mode": mode,
        "gates": {
            "gate1": {"enabled": True},
            "gate2": {"enabled": True, "model": "stub-model"},
            "gate3": {"enabled": False, "model": ""},
        },
    }


BAD_CONTENT = 'print("x")\n'  # gate1 error: no-print


def test_enforce_mode_short_circuits_gate2(tmp_path, monkeypatch):
    marker = tmp_path / "gate2-called"
    bin_dir = _make_stub_claude(tmp_path, marker)
    monkeypatch.setenv("PATH", "{}{}{}".format(bin_dir, os.pathsep, os.environ["PATH"]))

    res = gate_file("src/x.py", BAD_CONTENT, _gate2_cfg("enforce"), 1, 99999)
    assert any(v["severity"] == "error" for v in res["violations"])
    assert not marker.exists(), "gate2 must be skipped once gate1 errored (enforce)"


def test_warn_mode_still_runs_gate2(tmp_path, monkeypatch):
    marker = tmp_path / "gate2-called"
    bin_dir = _make_stub_claude(tmp_path, marker)
    monkeypatch.setenv("PATH", "{}{}{}".format(bin_dir, os.pathsep, os.environ["PATH"]))

    gate_file("src/x.py", BAD_CONTENT, _gate2_cfg("warn"), 1, 99999)
    assert marker.exists(), "warn mode keeps every enabled gate running"
