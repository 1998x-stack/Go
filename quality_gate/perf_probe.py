"""Optional same-host benchmark for trend regression; never benchmark as a rule oracle."""
from __future__ import annotations

import argparse
import json
import os
import platform
import statistics
import time
from pathlib import Path
from typing import Any

from go_game.core import RuleSpec, RulesEngine

PERF_SCHEMA = "go-perf-v1"


def measure(repeats: int = 15) -> dict[str, Any]:
    if type(repeats) is not int or repeats < 5:
        raise ValueError("repeats must be >= 5")
    engine = RulesEngine()
    stats = {}
    for size in (5, 9, 19):
        state = engine.new_game(RuleSpec(board_size=size))
        for _ in range(3):
            engine.legal_actions(state)
        samples = []
        for _ in range(repeats):
            start = time.perf_counter_ns()
            engine.legal_actions(state)
            samples.append((time.perf_counter_ns() - start) / 1_000_000)
        stats[f"empty_{size}_legal_ms_p50"] = round(statistics.median(samples), 6)
    return {"schema": PERF_SCHEMA,
            "environment": {"host_id": os.environ.get("GO_BENCH_HOST_ID", "UNSPECIFIED"),
                            "python": platform.python_version(), "machine": platform.machine(),
                            "processor": platform.processor(), "platform": platform.platform()},
            "repeat": repeats, "metrics": stats}


def compare_perf(current: dict[str, Any], baseline: dict[str, Any],
                 max_ratio: float = 1.25, min_absolute_ms: float = 0.15) -> dict[str, Any]:
    if current.get("schema") != PERF_SCHEMA or baseline.get("schema") != PERF_SCHEMA:
        raise ValueError("Incompatible benchmark schema")
    if (current.get("environment") != baseline.get("environment")
            or current.get("environment", {}).get("host_id") in (None, "UNSPECIFIED")):
        return {"status": "NOT_COMPARABLE", "reason": "Trusted host ID, platform and Python must match", "regressions": []}
    current_metrics, base_metrics = current["metrics"], baseline["metrics"]
    regressions = []
    for name in sorted(set(current_metrics) & set(base_metrics)):
        new, old = current_metrics[name], base_metrics[name]
        if type(new) not in (int, float) or type(old) not in (int, float) or old <= 0 or new < 0:
            raise ValueError("Invalid benchmark value")
        if new > old * max_ratio and new - old > min_absolute_ms:
            regressions.append({"id": name, "previous_ms": old, "current_ms": new,
                                "ratio": round(new / old, 3)})
    if set(current_metrics) != set(base_metrics):
        return {"status": "INCOMPLETE", "reason": "Metric names differ", "regressions": regressions}
    return {"status": "REGRESSION" if regressions else "PASS", "regressions": regressions,
            "thresholds": {"max_ratio": max_ratio, "min_absolute_ms": min_absolute_ms}}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("results/perf_current.json"))
    p.add_argument("--repeat", type=int, default=15)
    args = p.parse_args()
    values = measure(args.repeat)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(values, indent=2), encoding="utf-8")
    print(json.dumps(values, indent=2))


if __name__ == "__main__":
    main()
