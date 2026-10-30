# Go Quality Factory: Isolated Test Runner + Independent Evaluator

**Status:** locally executed prototype against a verified subset of `1998x-stack/Go`, HEAD `1758a8c205ea71cfea85cb4260bb480692444128` (2026-10-26). The source bundle is **not** a complete clone; UI and RL adapter integration were not run in this local environment.

## 1. Architecture and trust boundaries

```text
Developer / Coding Agent / PR
         │ submitted source snapshot
         ▼
 ┌──────────────────────────────┐
 │ Isolated Runner              │  quality_gate.runner
 │  pytest / headless E2E       │
 │  Ruff / Mypy                 │
 │  wall-clock limits           │
 │  process or Docker backend   │
 └─────────────┬────────────────┘
               │ runner_report.json (commands, exit codes, outputs, source digest)
               ▼
 ┌──────────────────────────────┐
 │ Independent Evaluator        │  quality_gate.evaluator
 │  golden expected outcomes    │
 │  replay verification         │
 │  source snapshot validation  │
 │  baseline regression diff    │
 │  optional perf comparison    │
 │  optional advisory LLM judge │
 └─────────────┬────────────────┘
               │ evaluation_report.json + evaluation_report.md
               ▼
        PASS / FAIL / INCOMPLETE
```

- **Do not give the coding Agent authority over the evaluator, golden fixtures or release gate.** In this prototype the evaluator is in the same repository to make reuse easy. For genuine independence, deploy it from a protected revision / independent CI job, pin the fixture digest, and give the implementation agent no write access.
- **Process backend is not a security sandbox**. It isolates environment variables, files per stage, process groups, wall time, and POSIX resources; it does not prevent all malicious system calls or network access.
- **Docker backend** uses network disabled, read-only root and source mount, dropped capabilities, no new privileges, process/memory/CPU caps, isolated tmpfs. Run it on a dedicated runner/VM for untrusted PRs. Docker itself is not a perfect hostile-code boundary; consider a stronger VM/microVM sandbox for truly adversarial contributions. See Docker's `docker run` security reference.
- The LLM Judge is **not a Go rules oracle**. It can rate audit-report clarity and missing justification, but cannot change any rule test result or override the deterministic verdict.

## 2. Local commands

From the supplied project root:

```bash
# Standard library and pytest must be preinstalled.
python -m pytest -q tests_quality audit_tests.py

# Run every lane in its own temporary copy; always save the report.
python -m quality_gate.runner --root . --out results --backend process || true

# Evaluator operates in a separate process; returns nonzero while known defects remain.
python -m quality_gate.evaluator --root . --report results/runner_report.json --out results

# Optional same-host performance baseline and comparison.
GO_BENCH_HOST_ID=ci-fixed-host-01 python -m quality_gate.perf_probe --out results/perf_current.json --repeat 15
python -m quality_gate.evaluator --root . --report results/runner_report.json --out results \
  --perf-current results/perf_current.json --perf-baseline quality_gate/fixtures/my-trusted-perf-baseline.json
```

For an upstream full checkout, place the `quality_gate/`, `tests_quality/`, `mypy.ini`, and `.github/workflows/quality-gate.yml` (manual-only until the known golden failures are fixed) into the repository. The runner will select original root `test_*.py` and `tests/` rather than `audit_tests.py` where appropriate.

### Docker process isolation backend

```bash
# Must be built in a trusted preparation step, before isolated execution.
docker build -t go-quality-runner:py311 -f quality_gate/Dockerfile .
python -m quality_gate.runner --root . --out results --backend docker
python -m quality_gate.evaluator --root . --report results/runner_report.json --out results
```

The image needs pytest/ruff/mypy and any UI/RL test extras **preinstalled** because the test phase has `--network none`. Pin the image digest in CI, and install from hashed/locked dependencies before release. Do not forward LLM API credentials to isolated test containers.

Optional LLM Judge: explicitly export `JUDGE_BASE_URL`, `JUDGE_API_KEY`, `JUDGE_MODEL` based on `.env.example`, then add `--judge` to the **evaluator only**. The endpoint must use HTTPS. Never supply actual secrets in committed source or test artifacts. `ERROR` and `NOT_CONFIGURED` are reported, never silently treated as an LLM endorsement.

## 3. Machine-readable contracts

**Runner** (`go-runner-v1`): source manifest SHA-256, backend/isolation level, Python/platform, four lane results; each stage includes exact argv, exit_code, wall_seconds, stdout/stderr (bounded), status, reason.

**Evaluator** (`go-evaluation-v1`): independent runner digest, golden fixture SHA-256, source snapshot verification, lane statuses, each deterministic case with expected/actual mismatches, regression comparison status, optional performance decision, optional advisory LLM evidence, final verdict.

Stage statuses: `PASS`, `FAIL`, `SKIP`, `TIMEOUT`, `ERROR`, `MISSING`. Failure in any required stage => FAIL. Missing/skipped stages => INCOMPLETE, never PASS. Golden mismatch or independently verified regression => FAIL even if all test lanes pass. Missing baseline => `NOT_ASSESSED`, not `PASS` or `no regressions`.

## 4. Phase-by-phase expansion

| Release | Runner E2E and static analysis | Independent oracle and regression | Promotion gate |
| --- | --- | --- | --- |
| **V0.2** Rules repair | capture/liberty/ko/pass/undo/SGF, property tests, CLI replay, type contract | hand-authored golden positions, SGF roundtrip, reference rule fixtures, illegal-action no-mutation | 100% trusted golden rules pass; lint and typing non-skipped |
| **V0.3** Fast engine | differential slow/fast engine E2E, move-delta reversibility, clone consistency, stress/leak tests | compare every move/mask/score to trusted oracle on fixed seeds, p50/p95 same-host latency | no semantic change; specified throughput target and performance regression budget |
| **V0.4** AlphaZero | policy/value shape/normalization, MCTS mask, tree visit accounting, checkpoint load, self-play replay | paired seeds with swapped colors, outcome invariants, frozen baseline arena, curriculum regression | deterministic/replay consistency, statistical confidence, reproducible model artifacts |

Additional full-repo E2E to add: **pygame virtual-display UI smoke**, **browser pygbag Playwright smoke**, Gymnasium `check_env`, PettingZoo `api_test`, 9×9/19×19 full games, and packaging. The included three E2E tests are headless pipeline tests; do not call them browser E2E.

## 5. Current measured result

- `python -m pytest -q -p no:cacheprovider tests_quality audit_tests.py`: **29 tests passed** (independent audit and QA tests; includes tests asserting known bugs are still present).
- Process runner: pytest PASS, headless E2E PASS, Ruff SKIP, Mypy SKIP (the installed Python environment lacks both).
- Evaluator: four hand-authored rule cases PASS, `manual_finish_sgf` FAIL, `terminal_recompute` FAIL; **overall FAIL**.
- LLM Judge disabled by default and **no actual model request** has been made.
- Docker was not installed here; container backend remains specified and unexecuted. A local attempt to install Ruff/Mypy was unsuccessful, so the related lanes cannot be marked PASS.

## 6. Hardening before enforcing in CI

1. Move the independent evaluator into a protected image/repository and pin golden fixture hashes as a required CI policy. Run from a separate trust domain; never load evaluator code from an untrusted PR.
2. Use a dedicated container host/VM and verify Docker image digest, system calls, writable mount permissions, CPU/memory/time limits and outbound connectivity under fault injection.
3. Separate E2E targets into core/game/UI/adapter/learner, use test collection expectations to detect silent skips, and run the complete stack across supported Python versions.
4. Add external rules oracle fixtures (including multi-ko, dead stone adjudication rules, handicap edge cases) and stronger cross-engine differential/property fuzzing. Current golden tests do not prove tournament-grade rules correctness.
5. Lock dependencies and sign/pin baseline artifacts; capture full stdout/stderr, coverage, JUnit XML, SBOM and test IDs in immutable CI artifact storage. This prototype stores bounded logs and JSON summary only.
6. Require evaluator source snapshot checks and load baseline reports from a protected branch. Performance comparisons require `GO_BENCH_HOST_ID` set by trusted CI on a calibrated host, alongside matching OS and Python; noisy microbenchmarks alone are not sufficient for releases.

