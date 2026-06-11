#!/usr/bin/env python3
"""HES Layer 2 — v9 Auto-Improvement Lane (meta-prompt self-improvement).

Improves the v9 meta-prompt ITSELF, with the same human gate the skill bridge
uses: a model may *propose* a new meta-prompt, but only a human *promotes* it.

    propose (default):  current meta_prompt.md [+ --feedback file]
                        -> claude -> tools/v9/meta_prompt.candidate.md
    --approve:          promote the candidate -> archive the live prompt as
                        tools/v9/archive/meta_prompt.v<N>.md, bump the
                        ``version:`` line to <N+1>, install the candidate.
                        (No model call; deterministic.)

The live prompt is NEVER touched without --approve, and --approve never calls
a model — generation and promotion are two separate, auditable steps.

Output: progress to stderr, one JSON summary to stdout.

Usage:
    python3 tools/v9_improve.py [--feedback FILE] [--model MODEL]
        [--claude-cmd CMD] [--timeout SECONDS]
    python3 tools/v9_improve.py --approve
"""

import argparse
import json
import os
import re
import shutil
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
V9_DIR = os.path.join(SCRIPT_DIR, "v9")
META_PATH = os.path.join(V9_DIR, "meta_prompt.md")
CANDIDATE_PATH = os.path.join(V9_DIR, "meta_prompt.candidate.md")
ARCHIVE_DIR = os.path.join(V9_DIR, "archive")

VERSION_RE = re.compile(r"^version:\s*(\d+)\s*$", re.MULTILINE)
IMPROVE_SENTINEL = "### V9:IMPROVE ###"

sys.path.insert(0, SCRIPT_DIR)
from v9_generate import call_model, resolve_model, strip_outer_fence  # noqa: E402


def _eprint(msg):
    sys.stderr.write("{}\n".format(msg))


def read_version(text):
    """Extract the integer after the ``version:`` line, or None."""
    m = VERSION_RE.search(text)
    return int(m.group(1)) if m else None


def build_improve_prompt(meta, feedback):
    feedback_block = ""
    if feedback:
        feedback_block = "\n=== OPERATOR FEEDBACK ===\n{}\n".format(feedback)
    return (
        "{}\nYou maintain the meta-prompt of a skill-authoring pipeline. "
        "Below is the CURRENT meta-prompt{}.\n\n"
        "=== CURRENT META PROMPT ===\n{}\n{}\n"
        "Propose an improved meta-prompt: tighten the output contract, "
        "sharpen the quality checklist, remove ambiguity. KEEP the overall "
        "document structure (title, 'version:' line, Role / Output contract / "
        "Quality checklist sections) and KEEP the 'version:' line value "
        "unchanged (promotion bumps it). Reply with ONLY the full improved "
        "meta-prompt markdown — no explanations, no surrounding code "
        "fences.".format(
            IMPROVE_SENTINEL,
            " and operator feedback" if feedback else "",
            meta,
            feedback_block,
        )
    )


def propose(args):
    """Generate a candidate meta-prompt next to the live one. FAIL-LOUD."""
    if shutil.which(args.claude_cmd) is None:
        _eprint("error: model CLI not found: {!r}".format(args.claude_cmd))
        return 2
    with open(META_PATH, "r", encoding="utf-8") as fh:
        meta = fh.read()
    current_version = read_version(meta)
    if current_version is None:
        _eprint("error: live meta prompt has no 'version: N' line — refusing.")
        return 2

    feedback = None
    if args.feedback:
        try:
            with open(args.feedback, "r", encoding="utf-8") as fh:
                feedback = fh.read()
        except OSError as exc:
            _eprint("error: could not read feedback file: {}".format(exc))
            return 2

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

    with open(CANDIDATE_PATH, "w", encoding="utf-8") as fh:
        fh.write(improved if improved.endswith("\n") else improved + "\n")

    summary = {
        "action": "propose",
        "candidate": CANDIDATE_PATH,
        "current_version": current_version,
        "next_version_on_promote": current_version + 1,
        "hint": "review the candidate, then run with --approve to promote",
    }
    _eprint("[done] candidate written: {}".format(CANDIDATE_PATH))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def promote():
    """Human-approved promotion: archive live, bump version, install candidate."""
    if not os.path.isfile(CANDIDATE_PATH):
        _eprint(
            "error: no candidate at {} — run propose first.".format(CANDIDATE_PATH)
        )
        return 2
    with open(META_PATH, "r", encoding="utf-8") as fh:
        live = fh.read()
    with open(CANDIDATE_PATH, "r", encoding="utf-8") as fh:
        candidate = fh.read()

    live_version = read_version(live)
    if live_version is None:
        _eprint("error: live meta prompt has no 'version: N' line — refusing.")
        return 2
    if read_version(candidate) is None:
        _eprint("error: candidate has no 'version: N' line — refusing.")
        return 2

    os.makedirs(ARCHIVE_DIR, exist_ok=True)
    archive_path = os.path.join(
        ARCHIVE_DIR, "meta_prompt.v{}.md".format(live_version)
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
    with open(META_PATH, "w", encoding="utf-8") as fh:
        fh.write(promoted)
    os.unlink(CANDIDATE_PATH)

    summary = {
        "action": "promote",
        "archived": archive_path,
        "installed": META_PATH,
        "old_version": live_version,
        "new_version": new_version,
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
        "v9 meta-prompt (model), promote it only with --approve (human gate).",
    )
    parser.add_argument(
        "--approve",
        action="store_true",
        help="promote the existing candidate (deterministic; no model call)",
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

    if not os.path.isfile(META_PATH):
        _eprint("error: live meta prompt not found at {}".format(META_PATH))
        return 2

    if args.approve:
        return promote()
    return propose(args)


if __name__ == "__main__":
    sys.exit(main())
