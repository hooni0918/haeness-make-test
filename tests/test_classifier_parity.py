"""Source-classification parity (⑪) + accuracy (⑫ anchored ignores, ⑬ case).

The shell gate (router.sh) and the Python controller (hes_controller.is_source_file)
re-implement "is this a gated source file?" in two languages. They are kept in
lockstep by hand (sharing code would force a python<->shell call on the
PreToolUse hot path); this test pins that lockstep on a corpus of tricky paths
so any drift fails CI. The same corpus exercises the ⑫/⑬ fixes.
"""

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROUTER = os.path.join(ROOT, ".claude", "hooks", "router.sh")

sys.path.insert(0, os.path.join(ROOT, "tools"))
import hes_controller  # noqa: E402

_CFG = hes_controller.load_config()

# (repo-relative path, expected is_source). Non-control-plane only (so the
# self-protection guard never interferes with the classification signal).
CORPUS = [
    ("src/foo.py", True),
    ("src/FOO.PY", True),            # ⑬ case-insensitive extension
    ("app/Main.SWIFT", True),        # ⑬ case-insensitive (swift)
    ("src/mytools/helper.py", True),  # ⑫ 'mytools' must NOT match ignore 'tools/'
    ("pkg/contest/x.py", True),       # ⑫ 'contest' must NOT match ignore 'tests/'...
    ("tools/x.py", False),           # ⑫ real 'tools/' segment -> ignored
    ("tests/x.py", False),           # ⑫ real 'tests/' segment -> ignored
    ("a/tools/b.py", False),         # ⑫ mid-path segment -> ignored
    ("src/test_x.py", False),        # ignore_basename_globs (test_*.py)
    ("src/notes.txt", False),        # no source glob
]


def _router_is_source(rel):
    """True iff router.sh classifies `rel` as a gated source file. Probe with
    print() content: source -> DENY (no-print error); not source -> silent allow."""
    payload = {
        "tool_name": "Write",
        "tool_input": {
            "file_path": os.path.join(ROOT, rel),
            "content": '"""m."""\nprint("x")\n',
        },
    }
    proc = subprocess.run(
        ["bash", ROUTER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return False
    try:
        return json.loads(out)["hookSpecificOutput"]["permissionDecision"] == "deny"
    except (ValueError, KeyError):
        return False  # plain-text inform = warn only = not an error-gated source


def test_router_and_controller_agree_and_match_expected():
    mismatches = []
    for rel, expected in CORPUS:
        r = _router_is_source(rel)
        c = hes_controller.is_source_file(rel, _CFG)
        if not (r == c == expected):
            mismatches.append(
                "{}: router={} controller={} expected={}".format(rel, r, c, expected)
            )
    assert not mismatches, "classification drift/▲:\n" + "\n".join(mismatches)
