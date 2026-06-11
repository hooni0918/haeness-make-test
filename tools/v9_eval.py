#!/usr/bin/env python3
"""HES Layer 2 — Meta-prompt eval harness (champion vs challenger).

A self-improvement loop is only as trustworthy as its eval. This runner
replays a FIXED goal set (``tools/v9/eval_goals.json``) through the live
meta-prompt (**champion**) and a candidate (**challenger**), scores both, and
writes a verdict that ``v9_improve.py --approve`` consumes as promotion
evidence. The model proposes; the evidence promotes; the human signs.

Scoring is DETERMINISTIC-first, per goal, in priority order:
  1. structural validity (skill_adapter)   — the hard signal
  2. residual problem count after the loop — fewer is better
  3. revise rounds used                    — fewer is better

Ties go to the champion (incumbent advantage — never churn the live prompt
without evidence). Self-preferential-bias guard: the generator never grades
itself; grading is arithmetic over signals produced under IDENTICAL
conditions for both contenders.

Exit codes: 0 = challenger wins, 1 = champion retains (or tie), 2 = error.
Progress goes to stderr; the verdict JSON goes to stdout and to
``$HES_EVAL_VERDICT`` (default ``build/eval/verdict.json``).

Usage:
    python3 tools/v9_eval.py [--goals FILE] [--challenger PATH] [--rounds N]
        [--model MODEL] [--claude-cmd CMD] [--timeout SECONDS] [--out FILE]
"""

import argparse
import hashlib
import json
import os
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from v9_generate import (  # noqa: E402
    _eprint,
    append_run,
    default_meta_path,
    read_version,
    resolve_model,
    run_generation,
    v9_dir,
)

DEFAULT_GOALS = os.path.join(SCRIPT_DIR, "v9", "eval_goals.json")


def default_verdict_path():
    return os.environ.get("HES_EVAL_VERDICT") or os.path.join(
        ROOT, "build", "eval", "verdict.json"
    )


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def load_goals(path):
    with open(path, "r", encoding="utf-8") as fh:
        goals = json.load(fh)
    if not isinstance(goals, list) or not all(isinstance(g, str) for g in goals):
        raise ValueError("goals file must be a JSON array of strings")
    if not goals:
        raise ValueError("goals file is empty")
    return goals


def score_contender(label, meta, goals, model, claude_cmd, timeout, rounds):
    """Run every goal through one meta-prompt; return aggregate + per-goal rows."""
    agg = {"valid": 0, "problems": 0, "rounds": 0, "errors": 0}
    rows = []
    for i, goal in enumerate(goals):
        _eprint("[eval:{}] goal {}/{}: {!r}".format(label, i + 1, len(goals), goal[:60]))
        try:
            summary, _ = run_generation(goal, meta, model, claude_cmd, timeout, rounds)
            row = {
                "goal": goal,
                "valid": summary["valid"],
                "problems": len(summary["problems"]),
                "rounds_used": summary["rounds_used"],
            }
            if summary["valid"]:
                agg["valid"] += 1
            agg["problems"] += len(summary["problems"])
            agg["rounds"] += summary["rounds_used"]
        except RuntimeError as exc:
            # A dead generation scores as a failure, not an aborted eval —
            # both contenders must be measured over the SAME goal set.
            row = {"goal": goal, "valid": False, "error": str(exc)}
            agg["errors"] += 1
        rows.append(row)
    return agg, rows


def decide_winner(champ, chall):
    """Deterministic comparison; ties retain the champion."""
    if chall["valid"] != champ["valid"]:
        return "challenger" if chall["valid"] > champ["valid"] else "champion"
    if chall["problems"] != champ["problems"]:
        return "challenger" if chall["problems"] < champ["problems"] else "champion"
    if chall["rounds"] != champ["rounds"]:
        return "challenger" if chall["rounds"] < champ["rounds"] else "champion"
    return "champion"  # tie -> incumbent advantage


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="v9_eval.py",
        description="HES Layer 2 eval: replay a fixed goal set through the "
        "live meta-prompt vs a challenger and emit a promotion verdict.",
    )
    parser.add_argument(
        "--goals", default=DEFAULT_GOALS, help="JSON array of goal strings"
    )
    parser.add_argument(
        "--challenger",
        default=None,
        help="challenger meta-prompt (default: tools/v9/meta_prompt.candidate.md)",
    )
    parser.add_argument("--rounds", type=int, default=1, help="quality rounds per goal")
    parser.add_argument("--model", default=None, help="model id override")
    parser.add_argument(
        "--claude-cmd",
        default=os.environ.get("HES_CLAUDE_CMD", "claude"),
        help="model CLI to invoke",
    )
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument(
        "--out", default=None, help="verdict path (default: build/eval/verdict.json)"
    )
    args = parser.parse_args(argv)

    if shutil.which(args.claude_cmd) is None:
        _eprint("error: model CLI not found: {!r}".format(args.claude_cmd))
        return 2

    champion_path = default_meta_path()
    challenger_path = args.challenger or os.path.join(
        v9_dir(), "meta_prompt.candidate.md"
    )
    for label, path in (("champion", champion_path), ("challenger", challenger_path)):
        if not os.path.isfile(path):
            _eprint("error: {} meta-prompt not found at {}".format(label, path))
            return 2

    try:
        goals = load_goals(args.goals)
    except (OSError, ValueError) as exc:
        _eprint("error: could not load goals: {}".format(exc))
        return 2

    with open(champion_path, "r", encoding="utf-8") as fh:
        champion_meta = fh.read()
    with open(challenger_path, "r", encoding="utf-8") as fh:
        challenger_meta = fh.read()

    model = resolve_model(args.model)
    _eprint(
        "[eval] {} goals x 2 contenders, model={}, rounds={}".format(
            len(goals), model, args.rounds
        )
    )

    champ_agg, champ_rows = score_contender(
        "champion", champion_meta, goals, model, args.claude_cmd, args.timeout,
        args.rounds,
    )
    chall_agg, chall_rows = score_contender(
        "challenger", challenger_meta, goals, model, args.claude_cmd, args.timeout,
        args.rounds,
    )

    winner = decide_winner(champ_agg, chall_agg)
    verdict = {
        "winner": winner,
        "goals": len(goals),
        "champion": {
            "file": champion_path,
            "version": read_version(champion_meta),
            **champ_agg,
        },
        "challenger": {
            "file": challenger_path,
            "version": read_version(challenger_meta),
            **chall_agg,
        },
        "challenger_sha256": sha256_file(challenger_path),
        "per_goal": {"champion": champ_rows, "challenger": chall_rows},
    }

    out_path = args.out or default_verdict_path()
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(verdict, fh, ensure_ascii=False, indent=2)
        fh.write("\n")

    append_run(
        {
            "kind": "eval",
            "winner": winner,
            "goals": len(goals),
            "champion": champ_agg,
            "challenger": chall_agg,
        }
    )

    _eprint(
        "[verdict] winner={} | champion valid {}/{} problems {} | "
        "challenger valid {}/{} problems {}".format(
            winner,
            champ_agg["valid"], len(goals), champ_agg["problems"],
            chall_agg["valid"], len(goals), chall_agg["problems"],
        )
    )
    _eprint("[verdict] written: {}".format(out_path))
    print(json.dumps(verdict, ensure_ascii=False, indent=2))
    return 0 if winner == "challenger" else 1


if __name__ == "__main__":
    sys.exit(main())
