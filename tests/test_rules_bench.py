"""Regression guard: the HES rule benchmark must stay at 0 FP / 0 FN.

This turns ``tools/bench_rules.py`` from a manual measurement into an enforced
gate: if a rule starts firing on clean code (false positive) or stops catching a
violation it should (false negative), this test fails. The benchmark runs the
real Gate 1 over the labeled corpus in ``tools/bench/rule_fixtures.json``.
"""

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_rule_benchmark_is_clean():
    proc = subprocess.run(
        [sys.executable, os.path.join("tools", "bench_rules.py")],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    # Exit 0 == CLEAN (every rule precision/recall 1.00, 0 FP, 0 FN).
    assert proc.returncode == 0, (
        "rule benchmark regressed:\n" + proc.stdout + proc.stderr
    )
    assert "VERDICT: CLEAN" in proc.stdout
