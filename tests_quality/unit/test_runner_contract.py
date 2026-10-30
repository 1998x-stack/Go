"""Fault injection / contract tests for the sandbox controller."""
from pathlib import Path

import pytest

from quality_gate.runner import _bounded_log, _source_manifest, _stage_args
from quality_gate.evaluator import _stage_verdict, compare_regressions, validate_judge_payload


def test_lanes_are_fixed_and_shell_free():
    for stage in ("pytest", "e2e", "lint", "type_check"):
        cmd = _stage_args(stage)
        assert cmd[0] == "-m"
        assert not any(x in ("sh", "bash", "-c") for x in cmd)
    with pytest.raises(ValueError):
        _stage_args("$(curl secrets)")


def test_missing_tool_is_not_a_green_gate():
    cases = [{"name": "pytest", "status": "PASS"}, {"name": "e2e", "status": "PASS"},
             {"name": "lint", "status": "SKIP"}, {"name": "type_check", "status": "PASS"}]
    results, outcome = _stage_verdict({"schema": "go-runner-v1", "stages": cases})
    assert outcome == "INCOMPLETE"
    assert any(x["status"] == "SKIP" for x in results)


def test_failure_overrides_skips():
    _, outcome = _stage_verdict({"schema": "go-runner-v1", "stages": [
        {"name": "pytest", "status": "FAIL"}, {"name": "type_check", "status": "SKIP"}]})
    assert outcome == "FAIL"


def test_judge_cannot_fabricate_evidence_or_pass_missing_ids():
    good = {"score": 3, "verdict": "concern", "evidence_ids": ["golden:a"], "notes": "A"}
    assert validate_judge_payload(good, {"golden:a"})["score"] == 3
    with pytest.raises(ValueError):
        validate_judge_payload({**good, "evidence_ids": ["golden:invented"]}, {"golden:a"})
    with pytest.raises(ValueError):
        validate_judge_payload({**good, "score": True}, {"golden:a"})


def test_regressions_detect_missing_and_new_failures():
    old = {"schema": "go-evaluation-v1", "golden": [
        {"id": "stable", "status": "PASS"}, {"id": "lost", "status": "PASS"}]}
    new = {"golden": [{"id": "stable", "status": "FAIL"}]}
    assert {r["id"] for r in compare_regressions(old, new)} == {"stable", "lost"}


def test_bounded_log(tmp_path):
    path = tmp_path / "output.log"
    path.write_bytes(b"a" * 200_000)
    assert "TRUNCATED" in _bounded_log(path)
    assert len(_bounded_log(path)) < 140_000


def test_source_manifest_sees_real_rules(tmp_path):
    root = Path(__file__).resolve().parents[2]
    files = _source_manifest(root)
    assert "game.py" in files and "go_game/core/engine.py" in files
    assert len(files["game.py"]) == 64


def test_source_snapshot_detects_post_test_edits(tmp_path):
    import hashlib
    import json
    from quality_gate.runner import _source_manifest
    from quality_gate.evaluator import _verify_source_snapshot
    (tmp_path / "go_game").mkdir()
    file = tmp_path / "go_game" / "one.py"
    file.write_text("x=1\n")
    manifest = _source_manifest(tmp_path)
    checksum = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    assert _verify_source_snapshot(tmp_path, checksum)
    file.write_text("x=2\n")
    assert not _verify_source_snapshot(tmp_path, checksum)


def test_process_timeout_is_fail_closed(monkeypatch):
    import sys
    from quality_gate import runner
    root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(runner, "_stage_args", lambda stage, source: ["-c", "import time;time.sleep(5)"])
    outcome = runner._run_stage("pytest", root, backend="process", timeout=1, image="ignored")
    assert outcome.status == "TIMEOUT"
    assert outcome.exit_code is None
