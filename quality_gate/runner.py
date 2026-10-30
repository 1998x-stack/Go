"""Run fixed QA lanes in per-lane disposable workspaces (or Docker containers).

The process backend is isolation for reliability, NOT a hostile-code sandbox.
For untrusted submitted code use the docker backend on a locked-down host.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SCHEMA = "go-runner-v1"
STAGES = ("pytest", "e2e", "lint", "type_check")
IGNORED = {".git", ".venv", "venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "results", "build", "dist", "node_modules", ".tox"}
MAX_SOURCE_FILES = 15000
MAX_SOURCE_BYTES = 200 * 1024 * 1024
LOG_LIMIT_BYTES = 128 * 1024


@dataclass(frozen=True)
class StageResult:
    name: str
    status: str
    exit_code: int | None
    seconds: float
    command: list[str]
    stdout: str
    stderr: str
    reason: str | None = None


def _stage_args(name: str, root: Path | None = None) -> list[str]:
    if name == "pytest":
        # Works both on the extracted core audit bundle and on the full upstream checkout.
        targets = ["tests_quality/unit"]
        if root is None or (root / "audit_tests.py").exists():
            targets.append("audit_tests.py")
        elif (root / "tests").exists():
            targets += ["tests", *sorted(p.name for p in root.glob("test_*.py"))]
        else:
            targets += sorted(p.name for p in root.glob("test_*.py"))
        return ["-m", "pytest", "-q", "-p", "no:cacheprovider", *targets]
    if name == "e2e":
        return ["-m", "pytest", "-q", "-p", "no:cacheprovider", "tests_quality/e2e"]
    if name == "lint":
        return ["-m", "ruff", "check", "--config", "quality_gate/ruff.toml", "quality_gate", "tests_quality"]
    if name == "type_check":
        return ["-m", "mypy", "--config-file", "mypy.ini", "quality_gate"]
    raise ValueError("Unknown stage: " + name)


def _source_manifest(root: Path) -> dict[str, str]:
    """Hash inputs without relying on untrusted repo-provided git metadata."""
    files: dict[str, str] = {}
    for path in sorted(root.rglob("*")):
        if set(path.relative_to(root).parts) & IGNORED:
            continue
        if path.is_symlink():
            raise ValueError("Symlink inside source is not supported: " + str(path))
        if not path.is_file():
            continue
        if path.suffix not in {".py", ".toml", ".ini", ".json", ".yml", ".yaml", ".md"}:
            continue
        if path.stat().st_size > 2 * 1024 * 1024:
            raise ValueError("Source file too large: " + str(path))
        files[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    return files


def _copy_source(root: Path, target: Path) -> None:
    total, count = 0, 0
    for path in root.rglob("*"):
        rel = path.relative_to(root)
        if set(rel.parts) & IGNORED:
            continue
        if path.is_symlink():
            raise ValueError("Symlink not allowed: " + str(path))
        if not path.is_file():
            continue
        count += 1
        total += path.stat().st_size
        if count > MAX_SOURCE_FILES or total > MAX_SOURCE_BYTES:
            raise ValueError("Source workspace size budget exceeded")
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, dest)


def _stage_available(name: str) -> bool:
    if name in {"pytest", "e2e"}:
        name = "pytest"
    else:
        name = "ruff" if name == "lint" else "mypy"
    import importlib.util
    return importlib.util.find_spec(name) is not None


def _bounded_log(path: Path) -> str:
    size = path.stat().st_size
    with path.open("rb") as stream:
        data = stream.read(LOG_LIMIT_BYTES)
    result = data.decode("utf-8", "replace")
    if size > LOG_LIMIT_BYTES:
        result += "\n[TRUNCATED: full output exceeded 128 KiB]"
    return result


def _resource_limits() -> None:
    # POSIX only; CPU and file-size caps mitigate hung or noisy child processes.
    import resource
    resource.setrlimit(resource.RLIMIT_CPU, (100, 110))
    resource.setrlimit(resource.RLIMIT_FSIZE, (16 * 1024 * 1024, 16 * 1024 * 1024))


def _run_stage(name: str, root: Path, backend: str, timeout: int, image: str) -> StageResult:
    start = time.monotonic()
    args = _stage_args(name, root)
    if backend == "process" and not _stage_available(name):
        return StageResult(name, "SKIP", None, 0.0, [sys.executable, *args], "", "",
                           "Dependency missing in host interpreter; not treated as PASS")
    if backend == "docker" and not shutil.which("docker"):
        return StageResult(name, "ERROR", None, 0.0, ["docker", "run"], "", "",
                           "Docker executable not installed")
    with tempfile.TemporaryDirectory(prefix="go-qa-") as work:
        tmp = Path(work)
        checkout = tmp / "checkout"
        checkout.mkdir()
        try:
            _copy_source(root, checkout)
        except (OSError, ValueError) as exc:
            return StageResult(name, "ERROR", None, 0.0, [], "", "", str(exc))
        out = tmp / "stdout.txt"
        err = tmp / "stderr.txt"
        if backend == "process":
            cmd = [sys.executable, *args]
            env = {
                "PATH": os.environ.get("PATH", ""),
                "PYTHONPATH": str(checkout),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONNOUSERSITE": "1",
                "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
                "HOME": str(tmp),
                "TMPDIR": str(tmp),
                "LANG": "C.UTF-8",
            }
        else:
            # Run a prebuilt, pinned-in-CI image with pytest/ruff/mypy preinstalled.
            cmd = [
                "docker", "run", "--rm", "--network", "none", "--read-only",
                "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
                "--pids-limit", "128", "--memory", "1g", "--cpus", "1",
                "--user", f"{os.getuid()}:{os.getgid()}",
                "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--workdir", "/work",
                "--mount", f"type=bind,src={checkout},dst=/work,readonly",
                "--env", "HOME=/tmp", "--env", "PYTHONPATH=/work",
                "--env", "PYTEST_DISABLE_PLUGIN_AUTOLOAD=1",
                "--env", "PYTHONDONTWRITEBYTECODE=1",
                image, "python", *args,
            ]
            env = {"PATH": os.environ.get("PATH", ""), "HOME": str(tmp), "LANG": "C.UTF-8"}
        try:
            with out.open("wb") as stdout, err.open("wb") as stderr:
                proc = subprocess.Popen(
                    cmd, cwd=checkout, env=env, stdout=stdout, stderr=stderr,
                    start_new_session=(os.name == "posix"),
                    preexec_fn=_resource_limits if os.name == "posix" and backend == "process" else None,
                )
                try:
                    code = proc.wait(timeout=timeout)
                    status = "PASS" if code == 0 else "FAIL"
                    reason = None if code == 0 else f"Exit status {code}"
                except subprocess.TimeoutExpired:
                    if os.name == "posix":
                        os.killpg(proc.pid, signal.SIGKILL)
                    else:
                        proc.kill()
                    proc.wait()
                    code, status, reason = None, "TIMEOUT", f"Exceeded {timeout}s wall clock"
        except OSError as exc:
            return StageResult(name, "ERROR", None, time.monotonic() - start, cmd,
                               "", "", f"Could not launch: {type(exc).__name__}")
        return StageResult(name, status, code, round(time.monotonic() - start, 4),
                           cmd, _bounded_log(out), _bounded_log(err), reason)


def run(root: Path, output: Path, backend: str = "process", timeout: int = 120,
        image: str = "go-quality-runner:py311", stages: tuple[str, ...] = STAGES) -> dict[str, Any]:
    root = root.resolve()
    output = output.resolve()
    if not (root / "go_game" / "core" / "engine.py").is_file():
        raise ValueError("Not a Go core workspace")
    if output == root:
        raise ValueError("Output directory must not equal source root")
    if timeout < 1:
        raise ValueError("timeout must be positive")
    if backend not in {"process", "docker"}:
        raise ValueError("Unknown backend")
    if not stages or len(set(stages)) != len(stages) or any(s not in STAGES for s in stages):
        raise ValueError("Invalid stage selection")
    manifest = _source_manifest(root)
    digest = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
    results = [asdict(_run_stage(s, root, backend, timeout, image)) for s in stages]
    data: dict[str, Any] = {
        "schema": SCHEMA, "source_manifest_sha256": digest,
        "backend": backend, "isolation_level": ("os_container" if backend == "docker" else "subprocess_only"),
        "python": platform.python_version(), "platform": platform.platform(),
        "stages": results,
        "e2e_scope": ("headless_plus_desktop_smoke" if (root / "go_game" / "app.py").exists()
                      else "headless_only"),
        "all_required_pass": all(x["status"] == "PASS" for x in results)
        and set(stages) == set(STAGES),
    }
    output.mkdir(parents=True, exist_ok=True)
    (output / "runner_report.json").write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--root", type=Path, default=Path.cwd())
    p.add_argument("--out", type=Path, default=Path("results"))
    p.add_argument("--backend", choices=["process", "docker"], default="process")
    p.add_argument("--image", default="go-quality-runner:py311")
    p.add_argument("--timeout", type=int, default=120)
    p.add_argument("--stages", default=",".join(STAGES))
    args = p.parse_args()
    report = run(args.root, args.out, args.backend, args.timeout, args.image, tuple(args.stages.split(",")))
    for stage in report["stages"]:
        print(f"{stage['name']:12} {stage['status']:8} {stage['seconds']:8.3f}s {stage['reason'] or ''}")
    print("runner_report.json:", args.out / "runner_report.json")
    raise SystemExit(0 if report["all_required_pass"] else 2)


if __name__ == "__main__":
    main()
