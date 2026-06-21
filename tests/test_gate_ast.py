"""⑨ AST tier (strict mode): FP-free + multiline + alias detection.

In strict_whole_file mode, the no-print rule (match: ast) is evaluated by
gate1-ast.py on the whole file: print() inside comments/strings is NOT flagged
(regex would), while real calls — including multiline and simple aliases — are.
Driven through the real router against a throwaway mini-root.
"""

import json
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
ROUTER = os.path.join(ROOT, ".claude", "hooks", "router.sh")

_RULES = {
    "version": 1,  # no source_sha256 -> staleness skipped
    "rules": [
        {
            "id": "no-print",
            "severity": "error",
            "applies": ["*.py"],
            "type": "forbid_pattern",
            "pattern": r"(^|[^a-zA-Z_.])print[[:space:]]*\(",
            "match": "ast",
            "name": "print",
            "message": "no print",
        }
    ],
}


def _mini_root(tmp_path, strict):
    cache = tmp_path / ".claude" / "cache"
    cache.mkdir(parents=True)
    (tmp_path / ".claude" / "config.json").write_text(
        json.dumps(
            {
                "mode": "enforce",
                "strict_whole_file": strict,
                "source_globs": ["*.py"],
                "ignore_path_substrings": [],
                "ignore_basename_globs": [],
                "gates": {"gate1": {"enabled": True}},
            }
        )
    )
    (cache / "rules.json").write_text(json.dumps(_RULES))
    return tmp_path


def _write(root, content, rel="src/m.py"):
    payload = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(root / rel), "content": content},
    }
    proc = subprocess.run(
        ["bash", ROUTER],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        env=dict(os.environ, CLAUDE_PROJECT_DIR=str(root)),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout.strip()
    if not out:
        return "allow", ""
    try:
        hs = json.loads(out)["hookSpecificOutput"]
        return hs["permissionDecision"], hs["permissionDecisionReason"]
    except (ValueError, KeyError):
        return "inform", out


def test_strict_ast_ignores_print_in_comment_and_string(tmp_path):
    root = _mini_root(tmp_path, True)
    src = '"""m."""\n# print("not a call")\nmsg = "use print(x) to debug"\nx = 1\n'
    dec, reason = _write(root, src)
    assert dec != "deny", reason  # AST sees no real call -> no false positive


def test_strict_ast_flags_real_call(tmp_path):
    root = _mini_root(tmp_path, True)
    dec, reason = _write(root, '"""m."""\nprint("x")\n')
    assert dec == "deny"
    assert "no-print" in reason


def test_strict_ast_flags_multiline_call(tmp_path):
    # Regex is single-line and misses this; AST does not.
    root = _mini_root(tmp_path, True)
    dec, reason = _write(root, '"""m."""\nprint(\n    "x",\n)\n')
    assert dec == "deny"
    assert "no-print" in reason


def test_strict_ast_flags_alias(tmp_path):
    root = _mini_root(tmp_path, True)
    dec, reason = _write(root, '"""m."""\np = print\np("x")\n')
    assert dec == "deny"
    assert "no-print" in reason


def test_nonstrict_uses_regex_on_real_call(tmp_path):
    # Default mode still catches a real print via the regex fallback (no regression).
    root = _mini_root(tmp_path, False)
    dec, reason = _write(root, '"""m."""\nprint("x")\n')
    assert dec == "deny"
    assert "no-print" in reason
