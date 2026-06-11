"""Shared test fixtures — isolate every test from the repo's live HES state."""

import pytest


@pytest.fixture(autouse=True)
def _isolate_hes_env(tmp_path, monkeypatch):
    """Route telemetry and eval verdicts into the test's tmp dir so tests
    never pollute (or read) the repo's own runs log / verdict."""
    monkeypatch.setenv("HES_RUNS_FILE", str(tmp_path / "runs.jsonl"))
    monkeypatch.setenv("HES_EVAL_VERDICT", str(tmp_path / "verdict.json"))
