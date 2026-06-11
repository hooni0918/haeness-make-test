#!/usr/bin/env python3
"""HES Layer 2 — v9 Auto-Improvement Lane (meta-prompt self-improvement).

Improves the v9 meta-prompt ITSELF, closing the loop with two safeguards a
naive self-improvement loop lacks:

  1. **Automatic feedback.** ``propose`` reads the runs log
     (``.claude/logs/v9_runs.jsonl``) and feeds recent failures — invalid
     candidates, residual problems, rejected integrations — into the
     improvement prompt. The loop learns from what actually went wrong, not
     from what the model imagines went wrong.
  2. **Evidence-based promotion.** ``--approve`` looks for a fresh eval
     verdict (``tools/v9_eval.py``: champion vs challenger over a fixed goal
     set). If the verdict says the challenger LOST, promotion is refused
     (``--force`` overrides). No verdict -> loud warning, human's call.

The model proposes; the evidence promotes; the human signs.

    propose (default):  meta_prompt.md + runs-log feedback [+ --feedback file]
                        -> claude -> tools/v9/meta_prompt.candidate.md
    --approve:          verify eval evidence -> archive live prompt as
                        tools/v9/archive/meta_prompt.v<N>.md -> bump the
                        ``version:`` line to <N+1> -> install the candidate.
                        (No model call; deterministic.)

Output: progress to stderr, one JSON summary to stdout.

Usage:
    python3 tools/v9_improve.py [--feedback FILE] [--model MODEL]
        [--claude-cmd CMD] [--timeout SECONDS]
    python3 tools/v9_improve.py --approve [--force]
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)

sys.path.insert(0, SCRIPT_DIR)
from v9_generate import (  # noqa: E402
    VERSION_RE,
    append_run,
    call_model,
    read_version,
    resolve_model,
    runs_file,
    strip_outer_fence,
    v9_dir,
)

IMPROVE_SENTINEL = "### V9:IMPROVE ###"
FEEDBACK_LIMIT = 20


def _eprint(msg):
    sys.stderr.write("{}\n".format(msg))


def _paths():
    """(live, candidate, archive_dir) under the v9 dir (env-overridable)."""
    base = v9_dir()
    return (
        os.path.join(base, "meta_prompt.md"),
        os.path.join(base, "meta_prompt.candidate.md"),
        os.path.join(base, "archive"),
    )


def default_verdict_path():
    return os.environ.get("HES_EVAL_VERDICT") or os.path.join(
        ROOT, "build", "eval", "verdict.json"
    )


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


# --- automatic feedback from the runs log -------------------------------------
def load_recent_feedback(limit=FEEDBACK_LIMIT):
    """Collect recent FAILURE evidence from the runs log as bullet lines.

    Failures worth learning from: invalid/problem-laden generations and
    integrations that died before install. Returns "" when there is nothing.
    """
    path = runs_file()
    if not os.path.isfile(path):
        return ""
    bullets = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    for raw in reversed(lines):
        if len(bullets) >= limit:
            break
        raw = raw.strip()
        if not raw:
            continue
        try:
            rec = json.loads(raw)
        except ValueError:
            continue
        kind = rec.get("kind")
        if kind == "generate":
            problems = rec.get("problems") or []
            if rec.get("valid") and not problems:
                continue
            detail = "; ".join(str(p) for p in problems[:3])
            if rec.get("error"):
                detail = (detail + "; " if detail else "") + str(rec["error"])
            bullets.append(
                "- goal {!r}: {}{}".format(
                    rec.get("goal", "?"),
                    "INVALID. " if not rec.get("valid") else "",
                    detail or "residual problems",
                )
            )
        elif kind == "integrate" and rec.get("status") in (
            "adapter-invalid",
            "conflict",
            "regression-failed",
        ):
            bullets.append(
                "- integration {} for {!r}: {}".format(
                    rec["status"], rec.get("name") or rec.get("candidate", "?"),
                    rec.get("detail", ""),
                )
            )
    return "\n".join(bullets)


def build_improve_prompt(meta, feedback):
    feedback_block = ""
    if feedback:
        feedback_block = (
            "\n=== RECENT FAILURE EVIDENCE (from the runs log + operator) ===\n"
            "{}\n".format(feedback)
        )
    return (
        "{}\nYou maintain the meta-prompt of a skill-authoring pipeline. "
        "Below is the CURRENT meta-prompt{}.\n\n"
        "=== CURRENT META PROMPT ===\n{}\n{}\n"
        "Propose an improved meta-prompt that would have PREVENTED the "
        "failures above: tighten the output contract, sharpen the quality "
        "checklist, remove ambiguity. KEEP the overall document structure "
        "(title, 'version:' line, Role / Output contract / Quality checklist "
        "sections) and KEEP the 'version:' line value unchanged (promotion "
        "bumps it). Reply with ONLY the full improved meta-prompt markdown — "
        "no explanations, no surrounding code fences.".format(
            IMPROVE_SENTINEL,
            " and recent failure evidence" if feedback else "",
            meta,
            feedback_block,
        )
    )


def propose(args):
    """Generate a candidate meta-prompt next to the live one. FAIL-LOUD."""
    meta_path, candidate_path, _ = _paths()
    if shutil.which(args.claude_cmd) is None:
        _eprint("error: model CLI not found: {!r}".format(args.claude_cmd))
        return 2
    with open(meta_path, "r", encoding="utf-8") as fh:
        meta = fh.read()
    current_version = read_version(meta)
    if current_version is None:
        _eprint("error: live meta prompt has no 'version: N' line — refusing.")
        return 2

    # Feedback = automatic (runs log) + optional operator file.
    feedback_parts = []
    auto_fb = load_recent_feedback()
    if auto_fb:
        feedback_parts.append(auto_fb)
        _eprint(
            "[propose] {} failure record(s) pulled from the runs log".format(
                auto_fb.count("\n") + 1
            )
        )
    if args.feedback:
        try:
            with open(args.feedback, "r", encoding="utf-8") as fh:
                feedback_parts.append(fh.read())
        except OSError as exc:
            _eprint("error: could not read feedback file: {}".format(exc))
            return 2
    feedback = "\n".join(p for p in feedback_parts if p.strip())

    model = resolve_model(args.model)
    _eprint("[propose] model={} current_version={}".format(model, current_version))
    try:
        improved = strip_outer_fence(
            call_model(
                build_improve_prompt(meta, feedback),
                model,
                args.claude_cmd,
                args.timeout,
            )
        )
    except RuntimeError as exc:
        _eprint("error: improvement proposal failed: {}".format(exc))
        return 2

    if read_version(improved) is None:
        # A candidate without a version line could never be promoted — patch
        # the current version line back in right under the title.
        improved = re.sub(
            r"^(# .*)$",
            r"\1\nversion: {}".format(current_version),
            improved,
            count=1,
            flags=re.MULTILINE,
        )
        if read_version(improved) is None:
            _eprint("error: candidate lost its 'version:' line; not writing.")
            return 1

    with open(candidate_path, "w", encoding="utf-8") as fh:
        fh.write(improved if improved.endswith("\n") else improved + "\n")

    append_run(
        {
            "kind": "improve-propose",
            "current_version": current_version,
            "with_auto_feedback": bool(auto_fb),
        }
    )
    summary = {
        "action": "propose",
        "candidate": candidate_path,
        "current_version": current_version,
        "next_version_on_promote": current_version + 1,
        "auto_feedback_used": bool(auto_fb),
        "hint": "run tools/v9_eval.py for evidence, then --approve to promote",
    }
    _eprint("[done] candidate written: {}".format(candidate_path))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def check_eval_evidence(candidate_path, force):
    """Gate promotion on the latest eval verdict.

    Returns (ok, note). A verdict counts as evidence only when its
    challenger hash matches the CURRENT candidate (stale verdicts are noise).
    """
    verdict_path = default_verdict_path()
    if not os.path.isfile(verdict_path):
        return True, "no eval verdict found — promoting on human authority alone " \
            "(run tools/v9_eval.py first for evidence)"
    try:
        with open(verdict_path, "r", encoding="utf-8") as fh:
            verdict = json.load(fh)
    except (OSError, ValueError):
        return True, "eval verdict unreadable — treating as no evidence"
    if verdict.get("challenger_sha256") != sha256_file(candidate_path):
        return True, "eval verdict is STALE (candidate changed since) — " \
            "treating as no evidence; re-run tools/v9_eval.py"
    if verdict.get("winner") == "challenger":
        return True, "eval evidence: challenger won ({}/{} valid vs {}/{})".format(
            verdict["challenger"].get("valid"), verdict.get("goals"),
            verdict["champion"].get("valid"), verdict.get("goals"),
        )
    if force:
        return True, "eval says champion won — OVERRIDDEN by --force"
    return False, "eval says champion won — refusing to promote a losing " \
        "candidate (re-propose, re-eval, or use --force)"


def promote(force):
    """Human-approved promotion: verify evidence, archive live, bump, install."""
    meta_path, candidate_path, archive_dir = _paths()
    if not os.path.isfile(candidate_path):
        _eprint(
            "error: no candidate at {} — run propose first.".format(candidate_path)
        )
        return 2
    with open(meta_path, "r", encoding="utf-8") as fh:
        live = fh.read()
    with open(candidate_path, "r", encoding="utf-8") as fh:
        candidate = fh.read()

    live_version = read_version(live)
    if live_version is None:
        _eprint("error: live meta prompt has no 'version: N' line — refusing.")
        return 2
    if read_version(candidate) is None:
        _eprint("error: candidate has no 'version: N' line — refusing.")
        return 2

    ok, note = check_eval_evidence(candidate_path, force)
    _eprint("[evidence] {}".format(note))
    if not ok:
        return 1

    os.makedirs(archive_dir, exist_ok=True)
    archive_path = os.path.join(
        archive_dir, "meta_prompt.v{}.md".format(live_version)
    )
    if os.path.exists(archive_path):
        _eprint(
            "error: archive already exists: {} — resolve manually.".format(
                archive_path
            )
        )
        return 2

    new_version = live_version + 1
    promoted = VERSION_RE.sub("version: {}".format(new_version), candidate, count=1)

    with open(archive_path, "w", encoding="utf-8") as fh:
        fh.write(live)
    with open(meta_path, "w", encoding="utf-8") as fh:
        fh.write(promoted)
    os.unlink(candidate_path)

    append_run(
        {
            "kind": "promote",
            "old_version": live_version,
            "new_version": new_version,
            "evidence": note,
        }
    )
    summary = {
        "action": "promote",
        "archived": archive_path,
        "installed": meta_path,
        "old_version": live_version,
        "new_version": new_version,
        "evidence": note,
    }
    _eprint(
        "[done] v{} archived; v{} is now live.".format(live_version, new_version)
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="v9_improve.py",
        description="HES Layer 2 auto-improvement lane: propose an improved "
        "v9 meta-prompt (model + runs-log feedback), promote it only with "
        "--approve backed by eval evidence (human gate).",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="promote the existing candidate (deterministic; no model call)",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="with --approve: promote even if the eval verdict says the "
        "challenger lost",
    )
    parser.add_argument(
        "--feedback", default=None, help="path to an operator feedback file"
    )
    parser.add_argument("--model", default=None, help="model id override")
    parser.add_argument(
        "--claude-cmd",
        default=os.environ.get("HES_CLAUDE_CMD", "claude"),
        help="model CLI to invoke (default: claude; env HES_CLAUDE_CMD overrides)",
    )
    parser.add_argument(
        "--timeout", type=int, default=240, help="model call timeout in seconds"
    )
    args = parser.parse_args(argv)

    meta_path, _, _ = _paths()
    if not os.path.isfile(meta_path):
        _eprint("error: live meta prompt not found at {}".format(meta_path))
        return 2

    if args.approve:
        return promote(args.force)
    return propose(args)


if __name__ == "__main__":
    sys.exit(main())
