#!/usr/bin/env python3
"""HES Layer-1 Automation Controller.

Runs the existing HES Layer-0 gates over a BATCH of files and produces a single
verdict (APPROVED / REVIEW / REJECTED). It does NOT reimplement any rule logic:
it INVOKES ``.claude/hooks/gate1-shell.sh`` (and gate2/gate3 when enabled) via
subprocess using the documented HES_* environment contract and parses the
pipe-delimited violation lines ("<severity>|<gate>|<message>") they print.

Source/ignore semantics (a file is a GATED SOURCE file iff):
  - basename matches ANY config.source_globs, AND
  - the repo-relative path contains NONE of config.ignore_path_substrings, AND
  - basename matches NONE of config.ignore_basename_globs.

Paths are resolved relative to this script's own location (tools/ is a child of
the project root) so the controller works from any working directory.

Usage:
    python3 tools/hes_controller.py [--files F [F ...]] [--staged]
        [--range A..B] [--json] [--ai-review] [--quiet]

Input modes (mutually exclusive; default is --staged):
    --files F...   Check given paths using their CURRENT working-tree content.
    --staged       Files from 'git diff --cached --name-only --diff-filter=ACM';
                   content from the STAGED blob ('git show :<path>').
    --range A..B   Files from 'git diff --name-only --diff-filter=ACM A..B';
                   content from the working tree.

Exit codes:
    0  APPROVED or REVIEW
    1  REJECTED
    2  usage / internal error
"""

import argparse
import fnmatch
import json
import os
import subprocess
import sys
import tempfile

# --- Path resolution ---------------------------------------------------------
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(SCRIPT_DIR)
CONFIG_PATH = os.path.join(ROOT, ".claude", "config.json")
HOOKS_DIR = os.path.join(ROOT, ".claude", "hooks")
GATE1 = os.path.join(HOOKS_DIR, "gate1-shell.sh")
GATE2 = os.path.join(HOOKS_DIR, "gate2-semantic.sh")
GATE3 = os.path.join(HOOKS_DIR, "gate3-architect.sh")
AI_REVIEW = os.path.join(SCRIPT_DIR, "ai_review.sh")


def _eprint(msg):
    """Write a diagnostic line to stderr."""
    sys.stderr.write("{}\n".format(msg))


# --- Config ------------------------------------------------------------------
def load_config():
    """Load .claude/config.json, falling back to safe defaults on any problem."""
    defaults = {
        "mode": "enforce",
        "source_globs": [],
        "ignore_path_substrings": [],
        "ignore_basename_globs": [],
        "thresholds": {"gate2_min_lines": 50, "gate3_min_lines": 200},
        "gates": {
            "gate1": {"enabled": True},
            "gate2": {"enabled": False, "model": ""},
            "gate3": {"enabled": False, "model": ""},
        },
    }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            cfg = json.load(fh)
    except (OSError, ValueError) as exc:
        _eprint("warning: could not load config.json ({}); using defaults".format(exc))
        return defaults
    # Merge shallow defaults so missing keys never KeyError downstream.
    merged = dict(defaults)
    merged.update(cfg)
    th = dict(defaults["thresholds"])
    th.update(cfg.get("thresholds") or {})
    merged["thresholds"] = th
    gates = dict(defaults["gates"])
    for name, gdef in (cfg.get("gates") or {}).items():
        base = dict(gates.get(name, {}))
        base.update(gdef or {})
        gates[name] = base
    merged["gates"] = gates
    return merged


def _int_threshold(cfg, key, fallback):
    """Read thresholds.<key> as a non-negative int, falling back if malformed."""
    raw = (cfg.get("thresholds") or {}).get(key, fallback)
    try:
        val = int(raw)
        if val < 0:
            return fallback
        return val
    except (TypeError, ValueError):
        return fallback


# --- Source-file classification ----------------------------------------------
def is_source_file(rel_path, cfg):
    """Decide whether a repo-relative path is a GATED SOURCE file.

    Mirrors the router.sh / config.json semantics exactly:
      basename matches ANY source_globs AND path contains NONE of the ignore
      substrings AND basename matches NONE of the ignore basename globs.
    """
    base = os.path.basename(rel_path)

    source_globs = cfg.get("source_globs") or []
    if not any(fnmatch.fnmatch(base, glob) for glob in source_globs):
        return False

    for sub in cfg.get("ignore_path_substrings") or []:
        if sub and sub in rel_path:
            return False

    for glob in cfg.get("ignore_basename_globs") or []:
        if fnmatch.fnmatch(base, glob):
            return False

    return True


# --- Git helpers -------------------------------------------------------------
def _git(args):
    """Run a git command at ROOT; return (rc, stdout, stderr)."""
    proc = subprocess.run(
        ["git"] + args,
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _to_rel(path):
    """Normalize a path to repo-relative (POSIX-style) form."""
    abs_path = path if os.path.isabs(path) else os.path.join(os.getcwd(), path)
    abs_path = os.path.normpath(abs_path)
    root_norm = os.path.normpath(ROOT)
    if abs_path == root_norm:
        return ""
    prefix = root_norm + os.sep
    if abs_path.startswith(prefix):
        rel = abs_path[len(prefix):]
    else:
        # Outside the repo tree (or already relative): keep as given.
        rel = path
    return rel.replace(os.sep, "/")


# --- Content acquisition -----------------------------------------------------
# Each function returns (content_str, error_or_None). error indicates the file
# could not be read for that mode -> treated as an error-class problem, not a
# crash.
def content_from_worktree(rel):
    """Read working-tree content for a repo-relative path."""
    abs_path = os.path.join(ROOT, rel)
    try:
        with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read(), None
    except OSError as exc:
        return None, "could not read working-tree file: {}".format(exc)


def content_from_staged(rel):
    """Read the STAGED blob ('git show :<path>') for a repo-relative path."""
    rc, out, err = _git(["show", ":{}".format(rel)])
    if rc != 0:
        return None, "could not read staged blob: {}".format((err or "").strip())
    return out, None


def content_from_range(rel, ref_b):
    """Read content for --range. Prefer 'git show B:<path>', else working tree."""
    if ref_b:
        rc, out, err = _git(["show", "{}:{}".format(ref_b, rel)])
        if rc == 0:
            return out, None
    # Fall back to the working tree (allowed by the spec).
    return content_from_worktree(rel)


# --- File list resolution ----------------------------------------------------
def resolve_files(args):
    """Return (list_of_rel_paths, content_loader, mode_label).

    content_loader(rel) -> (content_str_or_None, error_or_None).
    Deleted files are skipped at this stage where possible.
    """
    if args.files:
        rels = []
        for f in args.files:
            rel = _to_rel(f)
            abs_path = os.path.join(ROOT, rel)
            if not os.path.isfile(abs_path):
                # Skip deleted / missing files.
                _eprint("note: skipping non-existent file: {}".format(f))
                continue
            rels.append(rel)
        return rels, content_from_worktree, "files"

    if args.range:
        rc, out, err = _git(
            ["diff", "--name-only", "--diff-filter=ACM", args.range]
        )
        if rc != 0:
            raise RuntimeError(
                "git diff --range failed: {}".format((err or "").strip())
            )
        rels = [line for line in out.splitlines() if line.strip()]
        ref_b = args.range.split("..", 1)[1] if ".." in args.range else ""

        def loader(rel, _ref=ref_b):
            return content_from_range(rel, _ref)

        return rels, loader, "range"

    # default + --staged
    rc, out, err = _git(
        ["diff", "--cached", "--name-only", "--diff-filter=ACM"]
    )
    if rc != 0:
        raise RuntimeError(
            "git diff --cached failed: {}".format((err or "").strip())
        )
    rels = [line for line in out.splitlines() if line.strip()]
    return rels, content_from_staged, "staged"


# --- Gate invocation ---------------------------------------------------------
def run_gate(gate_path, env):
    """Run a gate script via bash; return (violation_lines, error_or_None).

    A gate's stdout is parsed as pipe-delimited violation lines. Gate1 is the
    hard gate; gate2/gate3 are fail-open by design (they print nothing on any
    internal problem), so a non-zero rc here is recorded but never crashes.
    """
    try:
        proc = subprocess.run(
            ["bash", gate_path],
            cwd=ROOT,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except OSError as exc:
        return [], "failed to launch {}: {}".format(os.path.basename(gate_path), exc)
    lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    err = None
    if proc.returncode != 0:
        err = "{} exited {}".format(os.path.basename(gate_path), proc.returncode)
    return lines, err


def parse_violation(line):
    """Parse '<severity>|<gate>|<message>' into a dict. Tolerant of extra pipes."""
    parts = line.split("|", 2)
    if len(parts) == 3:
        severity, gate, message = parts
    elif len(parts) == 2:
        severity, gate, message = parts[0], parts[1], ""
    else:
        # Malformed line — surface it as a warn so it is not silently lost.
        severity, gate, message = "warn", "?", line
    severity = severity.strip().lower()
    if severity not in ("error", "warn"):
        severity = "warn"
    return {"severity": severity, "gate": gate.strip(), "message": message.strip()}


def _error_count(result):
    """Number of error-severity rule violations recorded so far for a file."""
    return sum(1 for v in result["violations"] if v["severity"] == "error")


def gate_file(rel, content, cfg, gate2_min, gate3_min):
    """Run the enabled gates on one file's content. Returns a per-file result."""
    gates = cfg.get("gates") or {}
    mode = cfg.get("mode") or "enforce"
    result = {
        "file": rel,
        "violations": [],
        "errors": [],  # infrastructure-class problems (not rule violations)
    }

    tmp = tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", suffix=".hescontent", delete=False
    )
    try:
        tmp.write(content)
        tmp.close()
        change_lines = content.count("\n")
        if content and not content.endswith("\n"):
            change_lines += 1

        env = dict(os.environ)
        env["HES_ROOT"] = ROOT
        env["HES_FILE_PATH"] = rel
        env["HES_BASENAME"] = os.path.basename(rel)
        env["HES_CONTENT_FILE"] = tmp.name
        env["HES_CHANGE_LINES"] = str(change_lines)

        # Gate 1 — the only hard gate; always run.
        g1_lines, g1_err = run_gate(GATE1, env)
        if g1_err:
            result["errors"].append(g1_err)
        for ln in g1_lines:
            result["violations"].append(parse_violation(ln))

        # Token-saving short-circuit (mirrors router.sh): in enforce mode an
        # error from a cheaper gate already decides REJECTED, so the LLM
        # gates are skipped. Warn mode still runs them for a full report.
        def _short_circuit():
            return mode == "enforce" and _error_count(result) > 0

        # Gate 2 — enabled + size threshold.
        g2 = gates.get("gate2") or {}
        if not _short_circuit() and g2.get("enabled") and change_lines >= gate2_min:
            env2 = dict(env)
            env2["HES_GATE2_MODEL"] = str(g2.get("model") or "")
            g2_lines, g2_err = run_gate(GATE2, env2)
            if g2_err:
                result["errors"].append(g2_err)
            for ln in g2_lines:
                result["violations"].append(parse_violation(ln))

        # Gate 3 — enabled + size threshold.
        g3 = gates.get("gate3") or {}
        if not _short_circuit() and g3.get("enabled") and change_lines >= gate3_min:
            env3 = dict(env)
            env3["HES_GATE3_MODEL"] = str(g3.get("model") or "")
            g3_lines, g3_err = run_gate(GATE3, env3)
            if g3_err:
                result["errors"].append(g3_err)
            for ln in g3_lines:
                result["violations"].append(parse_violation(ln))
    finally:
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

    return result


# --- AI review (optional, fail-open) -----------------------------------------
def _build_ai_payload(results):
    """Compose the STDIN payload for ai_review.sh: gate findings + file content.

    ai_review.sh reads its payload from STDIN (it does `cat`), so we MUST feed
    it a payload and close stdin; otherwise its `cat` blocks on the terminal.
    """
    parts = ["=== GATE FINDINGS ==="]
    any_finding = False
    for res in results:
        for v in res["violations"]:
            any_finding = True
            parts.append(
                "{}|{}|{}: {}".format(
                    v["severity"], v["gate"], res["file"], v["message"]
                )
            )
        for e in res["errors"]:
            any_finding = True
            parts.append("error|infra|{}: {}".format(res["file"], e))
    if not any_finding:
        parts.append("(none)")

    parts.append("")
    parts.append("=== FILES ===")
    for res in results:
        abs_path = os.path.join(ROOT, res["file"])
        parts.append("--- {} ---".format(res["file"]))
        try:
            with open(abs_path, "r", encoding="utf-8", errors="replace") as fh:
                parts.append(fh.read())
        except OSError:
            parts.append("(content unavailable)")
    return "\n".join(parts)


def run_ai_review(results):
    """Invoke tools/ai_review.sh if present. Returns (verdict, reason, note).

    verdict is "REJECT" / "APPROVE" / None (skipped). Any error -> skip
    gracefully with a note. Never raises and never blocks on the terminal:
    the payload is fed on stdin (ai_review.sh reads it via `cat`).
    """
    if not os.path.isfile(AI_REVIEW):
        return None, "", "ai-review skipped: tools/ai_review.sh not found"

    payload = _build_ai_payload(results)
    try:
        proc = subprocess.run(
            ["bash", AI_REVIEW],
            cwd=ROOT,
            input=payload,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return None, "", "ai-review skipped: timed out"
    except (OSError, subprocess.SubprocessError) as exc:
        return None, "", "ai-review skipped: failed to run ({})".format(exc)

    out = (proc.stdout or "").strip()
    if proc.returncode not in (0, 1):
        return None, out, "ai-review skipped: exited {}".format(proc.returncode)
    if not out:
        return None, "", "ai-review skipped: empty response"

    # Decision is the FIRST token of the first line: APPROVE or REJECT.
    first_line = out.splitlines()[0].strip()
    first_token = first_line.split(None, 1)[0].upper() if first_line else ""
    if first_token == "REJECT":
        return "REJECT", first_line, "ai-review: REJECT"
    return "APPROVE", first_line, "ai-review: APPROVE"


# --- Reporting ---------------------------------------------------------------
def build_report(results, skipped, verdict, ai_note, error_count, warn_count):
    """Build the human-readable report as a list of lines."""
    lines = []
    for res in results:
        rel = res["file"]
        vios = res["violations"]
        errs = res["errors"]
        if not vios and not errs:
            lines.append("OK   {}".format(rel))
            continue
        lines.append("---- {}".format(rel))
        for v in vios:
            lines.append(
                "  {:<5} {:<6} {}".format(v["severity"], v["gate"], v["message"])
            )
        for e in errs:
            lines.append("  {:<5} {:<6} {}".format("error", "infra", e))
    for rel in skipped:
        lines.append("skip {}".format(rel))

    total_checked = len(results) + len(skipped)
    lines.append("")
    lines.append(
        "{} files checked ({} source), {} errors, {} warnings".format(
            total_checked, len(results), error_count, warn_count
        )
    )
    if ai_note:
        lines.append(ai_note)
    return lines


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="hes_controller.py",
        description="HES Layer-1 batch gate controller. Invokes the Layer-0 "
        "gate scripts over a set of files and produces a single verdict.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--files",
        nargs="+",
        metavar="F",
        help="check the given paths using their current working-tree content",
    )
    group.add_argument(
        "--staged",
        action="store_true",
        help="check staged files (default if no input flag is given)",
    )
    group.add_argument(
        "--range",
        metavar="A..B",
        help="check files changed between two git refs (A..B)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="also print a machine-readable JSON object to stdout",
    )
    parser.add_argument(
        "--ai-review",
        action="store_true",
        dest="ai_review",
        help="run tools/ai_review.sh after gating (skips gracefully if absent)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="suppress the per-file report; keep only the final VERDICT line",
    )
    args = parser.parse_args(argv)

    cfg = load_config()
    mode = cfg.get("mode") or "enforce"
    gate2_min = _int_threshold(cfg, "gate2_min_lines", 50)
    gate3_min = _int_threshold(cfg, "gate3_min_lines", 200)

    # 1. Resolve the file list + content loader.
    try:
        rels, loader, mode_label = resolve_files(args)
    except RuntimeError as exc:
        _eprint("error: {}".format(exc))
        if args.json:
            print(json.dumps({"verdict": "ERROR", "error": str(exc)}))
        return 2

    # 2. Classify + gate each file.
    results = []
    skipped = []
    error_count = 0
    warn_count = 0

    for rel in rels:
        if not is_source_file(rel, cfg):
            skipped.append(rel)
            continue
        content, load_err = loader(rel)
        if load_err is not None:
            # A file we cannot read is an error-class problem, not a crash.
            results.append(
                {"file": rel, "violations": [], "errors": [load_err]}
            )
            error_count += 1
            continue
        res = gate_file(rel, content, cfg, gate2_min, gate3_min)
        for v in res["violations"]:
            if v["severity"] == "error":
                error_count += 1
            else:
                warn_count += 1
        # Infrastructure errors count toward the error class for the verdict.
        error_count += len(res["errors"])
        results.append(res)

    # 3. Base verdict from gate violations.
    if error_count > 0:
        if mode == "enforce":
            verdict = "REJECTED"
        else:
            verdict = "REVIEW"
    elif warn_count > 0:
        verdict = "REVIEW"
    else:
        verdict = "APPROVED"

    # 4. Optional AI review — can only downgrade (toward REJECTED).
    ai_note = ""
    ai_reason = ""
    if args.ai_review:
        ai_verdict, ai_reason, ai_note = run_ai_review(results)
        if ai_verdict == "REJECT":
            verdict = "REJECTED"

    # 5. Exit code from the final verdict.
    exit_code = 1 if verdict == "REJECTED" else 0

    # 6. Human report. With --json, route the human-readable parts to stderr so
    #    stdout stays pure JSON (pipeable to `jq`).
    emit = _eprint if args.json else print
    if not args.quiet:
        report_lines = build_report(
            results, skipped, verdict, ai_note, error_count, warn_count
        )
        for line in report_lines:
            emit(line)
    verdict_line = "VERDICT: {}".format(verdict)
    if verdict == "REJECTED" and args.ai_review and ai_reason and ai_note == "ai-review: REJECT":
        verdict_line += " (ai-review: {})".format(ai_reason)
    emit(verdict_line)

    # 7. JSON output.
    if args.json:
        payload = {
            "verdict": verdict,
            "mode": mode,
            "input_mode": mode_label,
            "counts": {
                "checked": len(results) + len(skipped),
                "source": len(results),
                "skipped": len(skipped),
                "errors": error_count,
                "warnings": warn_count,
            },
            "files": [
                {
                    "file": r["file"],
                    "violations": r["violations"],
                    "errors": r["errors"],
                }
                for r in results
            ],
            "skipped": skipped,
            "exit_code": exit_code,
        }
        if args.ai_review:
            payload["ai_review"] = {
                "note": ai_note,
                "reason": ai_reason,
            }
        print(json.dumps(payload, ensure_ascii=False, indent=2))

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
