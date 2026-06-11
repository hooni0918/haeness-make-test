#!/usr/bin/env python3
"""HES Layer 2 — v9 Skill Generator + first-pass quality lane.

Generates a *skill candidate* markdown from a GOAL using the v9 meta-prompt
(``tools/v9/meta_prompt.md``), then runs the Layer-2 quality loop on it:

    GENERATE -> [ validate (deterministic) + critique (LLM) -> REVISE ] x N

Two different reliability contracts on purpose (mirrors the gate runtime):
  * GENERATE / REVISE are **fail-loud** — without model output there is
    nothing to ship, so a missing ``claude`` CLI or an empty response aborts
    with a clear error (exit 2).
  * CRITIQUE is **fail-open** — if the critic dies, the deterministic
    structural validation (skill_adapter) still gates the result, and the
    downstream HES pipeline (adapter -> integrate -> ai-review -> human)
    re-checks everything anyway.

The final candidate MUST pass the Layer-3 structural validation
(``skill_adapter.validate_and_normalize``) or this tool exits 1.

Output: progress lines go to **stderr**; a single JSON summary goes to
**stdout** (pipeable), e.g.::

    {"valid": true, "name": "...", "out": "...", "rounds_used": 1, ...}

Usage:
    python3 tools/v9_generate.py "<goal>" [--out PATH] [--rounds N]
        [--model MODEL] [--claude-cmd CMD] [--timeout SECONDS]

Prompt kinds carry a sentinel header ("### V9:GENERATE ###" etc.) so tests
can stub the model CLI deterministically and operators can grep transcripts.
"""

import argparse
import json
import os
import shutil
import subprocess
import sys

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
META_PROMPT_PATH = os.path.join(SCRIPT_DIR, "v9", "meta_prompt.md")
CONFIG_PATH = os.path.join(ROOT, ".claude", "config.json")
DEFAULT_OUT_DIR = os.path.join(ROOT, "build", "candidates")
DEFAULT_MODEL = "claude-sonnet-4-6"
DEFAULT_TIMEOUT = 240

sys.path.insert(0, SCRIPT_DIR)
from skill_adapter import validate_and_normalize  # noqa: E402  (Layer 3 reuse)

GENERATE_SENTINEL = "### V9:GENERATE ###"
CRITIQUE_SENTINEL = "### V9:CRITIQUE ###"
REVISE_SENTINEL = "### V9:REVISE ###"


def _eprint(msg):
    """Progress/diagnostics to stderr (stdout is reserved for the JSON summary)."""
    sys.stderr.write("{}\n".format(msg))


def resolve_model(cli_model):
    """Pick the generation model: --model > $HES_V9_MODEL > config gate3 > default.

    Generation is an authoring task, so the architect-tier model (gate3) is a
    better config fallback than the cheap semantic gate (gate2).
    """
    if cli_model:
        return cli_model
    env_model = os.environ.get("HES_V9_MODEL", "").strip()
    if env_model:
        return env_model
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
        model = ((cfg.get("gates") or {}).get("gate3") or {}).get("model")
        if model:
            return model
    except (OSError, ValueError):
        pass
    return DEFAULT_MODEL


def call_model(prompt, model, claude_cmd, timeout):
    """Run ``claude -p`` with *prompt* on stdin; return its text output.

    Raises RuntimeError on any failure (caller decides loud vs open).
    """
    try:
        proc = subprocess.run(
            [claude_cmd, "-p", "--model", model, "--output-format", "text"],
            input=prompt,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        raise RuntimeError("model call timed out after {}s".format(timeout))
    except OSError as exc:
        raise RuntimeError("failed to launch {}: {}".format(claude_cmd, exc))
    if proc.returncode != 0:
        raise RuntimeError(
            "{} exited {}: {}".format(
                claude_cmd, proc.returncode, (proc.stderr or "").strip()[:300]
            )
        )
    out = (proc.stdout or "").strip()
    if not out:
        raise RuntimeError("empty model response")
    return out


def strip_outer_fence(text):
    """Drop ONE surrounding markdown code fence, if the model added it."""
    lines = text.strip().splitlines()
    if len(lines) >= 2 and lines[0].startswith("```") and lines[-1].strip() == "```":
        return "\n".join(lines[1:-1]).strip()
    return text.strip()


def build_generate_prompt(meta, goal):
    return (
        "{}\n{}\n\nGOAL:\n{}\n\n"
        "Reply with ONLY the skill markdown (frontmatter + body). "
        "No explanations, no surrounding code fences.".format(
            GENERATE_SENTINEL, meta, goal
        )
    )


def build_critique_prompt(meta, candidate):
    return (
        "{}\nYou are the v9 first-pass quality reviewer. Below are the v9 "
        "meta-prompt (with its Quality checklist) and a skill candidate.\n\n"
        "=== META PROMPT ===\n{}\n\n=== CANDIDATE ===\n{}\n\n"
        "Check the candidate against the Quality checklist (C1..C5). If ALL "
        "checks pass reply with exactly the single word: PASS\n"
        "Otherwise reply ONLY with one problem per line, each starting with "
        "'problem: '.".format(CRITIQUE_SENTINEL, meta, candidate)
    )


def build_revise_prompt(meta, candidate, problems):
    return (
        "{}\n{}\n\n=== CURRENT CANDIDATE ===\n{}\n\n=== PROBLEMS TO FIX ===\n{}\n\n"
        "Rewrite the FULL skill candidate fixing every problem. Reply with "
        "ONLY the corrected skill markdown — no explanations, no "
        "surrounding code fences.".format(
            REVISE_SENTINEL, meta, candidate, "\n".join(problems)
        )
    )


def critique(meta, candidate, model, claude_cmd, timeout):
    """Run the LLM critic. Returns (problems, note). FAIL-OPEN: on any model
    problem returns ([], note) so the deterministic validation still decides."""
    try:
        out = call_model(
            build_critique_prompt(meta, candidate), model, claude_cmd, timeout
        )
    except RuntimeError as exc:
        return [], "critique skipped (fail-open): {}".format(exc)
    if out.strip().upper() == "PASS":
        return [], None
    problems = []
    for line in out.splitlines():
        line = line.strip()
        if not line or line.upper() == "PASS":
            continue
        if line.lower().startswith("problem:"):
            line = line[len("problem:"):].strip()
        problems.append(line)
    return problems, None


def structural_problems(candidate):
    """Layer-3 deterministic validation. Returns (problems, result_dict)."""
    result, _ = validate_and_normalize(candidate)
    if result["valid"]:
        return [], result
    return list(result["problems"]), result


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="v9_generate.py",
        description="HES Layer 2: generate a skill candidate from a goal via "
        "the v9 meta-prompt, then run the first-pass quality loop on it.",
    )
    parser.add_argument("goal", help="what the skill should accomplish")
    parser.add_argument(
        "--out",
        default=None,
        help="output path for the candidate (default: build/candidates/<name>.md)",
    )
    parser.add_argument(
        "--rounds",
        type=int,
        default=2,
        help="max critique->revise rounds after the initial generation (default 2)",
    )
    parser.add_argument("--model", default=None, help="model id override")
    parser.add_argument(
        "--claude-cmd",
        default=os.environ.get("HES_CLAUDE_CMD", "claude"),
        help="model CLI to invoke (default: claude; env HES_CLAUDE_CMD overrides)",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help="per-model-call timeout in seconds (default {})".format(DEFAULT_TIMEOUT),
    )
    args = parser.parse_args(argv)

    # --- preflight: generation is FAIL-LOUD ----------------------------------
    if shutil.which(args.claude_cmd) is None:
        _eprint(
            "error: model CLI not found: {!r} — Layer 2 cannot generate "
            "without a model (install the claude CLI or pass --claude-cmd).".format(
                args.claude_cmd
            )
        )
        return 2
    if not os.path.isfile(META_PROMPT_PATH):
        _eprint("error: meta prompt not found at {}".format(META_PROMPT_PATH))
        return 2
    with open(META_PROMPT_PATH, "r", encoding="utf-8") as fh:
        meta = fh.read()

    model = resolve_model(args.model)
    notes = []

    # --- GENERATE (fail-loud) -------------------------------------------------
    _eprint("[generate] model={} goal={!r}".format(model, args.goal[:80]))
    try:
        candidate = strip_outer_fence(
            call_model(
                build_generate_prompt(meta, args.goal),
                model,
                args.claude_cmd,
                args.timeout,
            )
        )
    except RuntimeError as exc:
        _eprint("error: generation failed: {}".format(exc))
        return 2

    # --- quality loop: validate + critique -> revise ---------------------------
    rounds_used = 0
    problems = []
    for round_no in range(args.rounds + 1):
        struct_problems, result = structural_problems(candidate)
        sem_problems, note = critique(
            meta, candidate, model, args.claude_cmd, args.timeout
        )
        if note:
            notes.append(note)
            _eprint("[critique] {}".format(note))
        problems = struct_problems + sem_problems
        if not problems:
            break
        if round_no >= args.rounds:
            _eprint(
                "[quality] {} problem(s) remain after {} round(s)".format(
                    len(problems), rounds_used
                )
            )
            break
        _eprint(
            "[revise] round {}: fixing {} problem(s)".format(
                round_no + 1, len(problems)
            )
        )
        try:
            candidate = strip_outer_fence(
                call_model(
                    build_revise_prompt(meta, candidate, problems),
                    model,
                    args.claude_cmd,
                    args.timeout,
                )
            )
        except RuntimeError as exc:
            _eprint("error: revision failed: {}".format(exc))
            return 2
        rounds_used += 1

    # --- final hard gate: Layer-3 structural validity --------------------------
    result, normalized = validate_and_normalize(candidate)
    summary = {
        "valid": result["valid"],
        "name": result["name"],
        "description": result["description"],
        "goal": args.goal,
        "model": model,
        "rounds_used": rounds_used,
        "problems": problems,
        "notes": notes,
        "out": None,
    }
    if not result["valid"]:
        _eprint("error: final candidate is structurally INVALID; not writing.")
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 1

    out_path = args.out or os.path.join(
        DEFAULT_OUT_DIR, "{}.md".format(result["name"])
    )
    out_path = os.path.abspath(os.path.expanduser(out_path))
    out_dir = os.path.dirname(out_path)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as fh:
        fh.write(normalized)
    summary["out"] = out_path
    _eprint("[done] candidate written: {}".format(out_path))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
