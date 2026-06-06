#!/usr/bin/env python3
"""HES rule benchmark — measure per-rule precision/recall against a labeled corpus.

Why this exists: gate decisions are recorded in ``.claude/logs/gates.log``, but a
log cannot tell you a rule's *false-positive rate* — that needs ground truth. So
this harness runs the REAL Gate 1 (``.claude/hooks/gate1-shell.sh``) over a
labeled corpus (``tools/bench/rule_fixtures.json``) where every snippet is tagged
with the rule ids it *should* fire, then reports, per rule:

    TP  rule fired on a snippet that expected it
    FP  rule fired on a snippet that did NOT expect it   (false positive / noise)
    FN  rule expected on a snippet but did NOT fire       (false negative / miss)
    precision = TP / (TP + FP)        recall = TP / (TP + FN)

It does NOT reimplement any rule logic: it invokes ``gate1-shell.sh`` through the
documented ``HES_*`` environment contract (exactly like ``hes_controller.py``) and
parses the ``severity|gate1|[id] message`` lines it prints.

This is the measurement counterpart to the gate: "decide rules by measurement, not
by guessing." The harness exits non-zero if ANY rule has a false positive or a
false negative, so a green run means the rule set converged to 0 findings — usable
as a CI gate.

Usage:
    python3 tools/bench_rules.py [--json] [--quiet]

Exit codes:
    0  CLEAN  — every fixture matched exactly (0 FP, 0 FN)
    1  FAILED — at least one false positive or false negative
    2  usage / internal error
"""

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
GATE1 = os.path.join(ROOT, ".claude", "hooks", "gate1-shell.sh")
RULES = os.path.join(ROOT, ".claude", "cache", "rules.json")
FIXTURES = os.path.join(SCRIPT_DIR, "bench", "rule_fixtures.json")

# Gate 1 prints "severity|gate1|[rule-id] message (line N)"; pull the first [id].
RULE_ID_RE = re.compile(r"\[([^\]]+)\]")


def _eprint(msg):
    sys.stderr.write("{}\n".format(msg))


def all_rule_ids():
    """Return the list of rule ids declared in rules.json (coverage baseline)."""
    with open(RULES, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    return [r["id"] for r in data.get("rules", []) if "id" in r]


def fired_rules(content, basename):
    """Run Gate 1 over `content` (as a file named `basename`); return fired ids."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".bench", delete=False
    )
    try:
        tmp.write(content)
        tmp.close()
        change_lines = content.count("\n")
        if content and not content.endswith("\n"):
            change_lines += 1
        env = dict(os.environ)
        env["HES_ROOT"] = ROOT
        env["HES_BASENAME"] = basename
        env["HES_FILE_PATH"] = basename
        env["HES_CONTENT_FILE"] = tmp.name
        env["HES_CHANGE_LINES"] = str(change_lines)
        proc = subprocess.run(
            ["bash", GATE1],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        fired = set()
        for line in proc.stdout.splitlines():
            if not line.strip():
                continue
            match = RULE_ID_RE.search(line)
            if match:
                fired.add(match.group(1))
        return fired
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass


def _ratio(numerator, denominator):
    """precision/recall helper; None when the denominator is 0 (undefined)."""
    if denominator == 0:
        return None
    return numerator / denominator


def _fmt(value):
    return "  -  " if value is None else "{:.2f}".format(value)


def run_benchmark():
    """Execute every fixture and return (rule_stats, case_results, totals)."""
    with open(FIXTURES, "r", encoding="utf-8") as fh:
        doc = json.load(fh)
    fixtures = doc.get("fixtures", [])

    rule_ids = all_rule_ids()
    stats = {rid: {"tp": 0, "fp": 0, "fn": 0} for rid in rule_ids}

    def bump(rid, key):
        stats.setdefault(rid, {"tp": 0, "fp": 0, "fn": 0})[key] += 1

    case_results = []
    total_fp = total_fn = passed = 0

    for fx in fixtures:
        basename = fx["basename"]
        expect = set(fx.get("expect", []))
        fired = fired_rules(fx["content"], basename)

        tp = fired & expect
        fp = fired - expect
        fn = expect - fired
        for rid in tp:
            bump(rid, "tp")
        for rid in fp:
            bump(rid, "fp")
        for rid in fn:
            bump(rid, "fn")

        total_fp += len(fp)
        total_fn += len(fn)
        ok = not fp and not fn
        if ok:
            passed += 1
        case_results.append(
            {
                "id": fx["id"],
                "ok": ok,
                "expect": sorted(expect),
                "fired": sorted(fired),
                "false_positive": sorted(fp),
                "false_negative": sorted(fn),
            }
        )

    totals = {
        "fixtures": len(fixtures),
        "passed": passed,
        "false_positives": total_fp,
        "false_negatives": total_fn,
        "verdict": "CLEAN" if (total_fp == 0 and total_fn == 0) else "FAILED",
    }
    return stats, case_results, totals


def build_report(stats, case_results, totals):
    """Human-readable report lines."""
    lines = []
    lines.append(
        "HES rule benchmark — {} fixtures over {} rules".format(
            totals["fixtures"], len(stats)
        )
    )
    lines.append("")
    lines.append(
        "  {:<24} {:>3} {:>3} {:>3}  {:>5} {:>5}  {}".format(
            "rule", "TP", "FP", "FN", "prec", "rec", "status"
        )
    )
    lines.append("  " + "-" * 60)
    for rid in sorted(stats):
        s = stats[rid]
        prec = _ratio(s["tp"], s["tp"] + s["fp"])
        rec = _ratio(s["tp"], s["tp"] + s["fn"])
        if s["tp"] + s["fp"] + s["fn"] == 0:
            status = "untested"
        elif s["fp"] == 0 and s["fn"] == 0:
            status = "ok"
        else:
            status = "FP={} FN={}".format(s["fp"], s["fn"])
        lines.append(
            "  {:<24} {:>3} {:>3} {:>3}  {:>5} {:>5}  {}".format(
                rid, s["tp"], s["fp"], s["fn"], _fmt(prec), _fmt(rec), status
            )
        )

    failing = [c for c in case_results if not c["ok"]]
    if failing:
        lines.append("")
        lines.append("  failing fixtures:")
        for c in failing:
            detail = []
            if c["false_positive"]:
                detail.append("unexpected={}".format(c["false_positive"]))
            if c["false_negative"]:
                detail.append("missing={}".format(c["false_negative"]))
            lines.append("    - {}: {}".format(c["id"], "; ".join(detail)))

    lines.append("")
    lines.append(
        "fixtures: {}/{} passed   false positives: {}   false negatives: {}".format(
            totals["passed"],
            totals["fixtures"],
            totals["false_positives"],
            totals["false_negatives"],
        )
    )
    lines.append("VERDICT: {}".format(totals["verdict"]))
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="bench_rules.py",
        description="Measure HES rule precision/recall against a labeled corpus.",
    )
    parser.add_argument(
        "--json", action="store_true", help="emit a machine-readable JSON report"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="print only the VERDICT line"
    )
    args = parser.parse_args(argv)

    for path in (GATE1, RULES, FIXTURES):
        if not os.path.isfile(path):
            _eprint("error: required file not found: {}".format(path))
            return 2

    stats, case_results, totals = run_benchmark()
    exit_code = 0 if totals["verdict"] == "CLEAN" else 1

    if args.json:
        payload = {
            "verdict": totals["verdict"],
            "totals": totals,
            "rules": {
                rid: {
                    **s,
                    "precision": _ratio(s["tp"], s["tp"] + s["fp"]),
                    "recall": _ratio(s["tp"], s["tp"] + s["fn"]),
                }
                for rid, s in stats.items()
            },
            "cases": case_results,
            "exit_code": exit_code,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return exit_code

    if args.quiet:
        print("VERDICT: {}".format(totals["verdict"]))
        return exit_code

    for line in build_report(stats, case_results, totals):
        print(line)
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
