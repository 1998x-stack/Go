import json

from quality_gate.evaluator import llm_judge_advisory
from quality_gate.perf_probe import compare_perf, measure


def test_perf_detects_large_regression_only_on_matched_host():
    baseline = {"schema": "go-perf-v1", "environment": {"host": "a", "host_id": "trusted"},
                "metrics": {"m": 1.0}}
    new = {"schema": "go-perf-v1", "environment": {"host": "a", "host_id": "trusted"},
           "metrics": {"m": 2.0}}
    assert compare_perf(new, baseline)["status"] == "REGRESSION"
    new["environment"] = {"host": "b", "host_id": "trusted"}
    assert compare_perf(new, baseline)["status"] == "NOT_COMPARABLE"


def test_perf_smoke():
    r = measure(5)
    assert set(r["metrics"]) == {"empty_5_legal_ms_p50", "empty_9_legal_ms_p50", "empty_19_legal_ms_p50"}
    assert all(x > 0 for x in r["metrics"].values())


def test_advisory_judge_invalid_response_fails_closed(monkeypatch):
    monkeypatch.setenv("JUDGE_BASE_URL", "https://judge.example/v1")
    monkeypatch.setenv("JUDGE_API_KEY", "placeholder")
    monkeypatch.setenv("JUDGE_MODEL", "model")

    class Fake:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self, maximum):
            content = json.dumps({"score": 5, "verdict": "pass",
                                  "evidence_ids": ["made-up"], "notes": "Looks good"})
            return json.dumps({"choices": [{"message": {"content": content}}]}).encode()

    monkeypatch.setattr("quality_gate.evaluator.urllib.request.urlopen", lambda *a, **k: Fake())
    summary = {"stages": [{"id": "stage:pytest", "status": "FAIL"}], "golden": []}
    result = llm_judge_advisory(summary)
    assert result["status"] == "ERROR"


def test_judge_no_keys_cannot_run(monkeypatch):
    monkeypatch.delenv("JUDGE_API_KEY", raising=False)
    assert llm_judge_advisory({"stages": [], "golden": []})["status"] == "NOT_CONFIGURED"
