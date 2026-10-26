"""Trusted local worker for a fixed allowlist of Go research jobs.

Runs in a separate operator-owned process. Neither Python source nor a shell
command is accepted from job manifests. Cross-host execution is deliberately
out of scope until a proper sandbox, CAS metadata and remote artifact store.
"""
import argparse
import json
import os
import tempfile
import threading
import time
from pathlib import Path

from go_game.core import RuleSpec
from go_game.training.dataset import validate_shard
from go_game.training.search import SearchConfig, UniformPredictor
from go_game.training.selfplay import selfplay_game

from .artifacts import ArtifactStore
from .errors import PlatformError
from .jobs import JobService
from .storage import PlatformStore


class LocalWorker:
    def __init__(self, store, artifacts, worker_id="go-local-worker", clock=None):
        self.store = store
        self.artifacts = artifacts
        self.jobs = JobService(store, clock=clock)
        self.worker_id = worker_id

    @staticmethod
    def _exact(inputs, required):
        if not isinstance(inputs, dict) or set(inputs) != set(required):
            raise ValueError("Worker job manifest fields do not match expected kind")
        return inputs

    def _provenance(self, digest, kind):
        """A validated hash is not sufficient: output must be from a completed job."""
        with self.store.connection() as conn:
            found = conn.execute(
                "SELECT 1 FROM jobs WHERE kind=? AND status='succeeded' "
                "AND artifact_digest=? LIMIT 1", (kind, digest)).fetchone()
        if found is None:
            raise ValueError("Artifact lacks a completed trusted job producer")

    def _selfplay(self, inp):
        self._exact(inp, ("rules", "seed", "simulations", "max_moves"))
        rules = RuleSpec.from_dict(inp["rules"])
        if rules.board_size > 5 or rules.handicap:
            raise ValueError("Local self-play worker supports board size 2..5 without handicap")
        if (type(inp["seed"]) is not int
                or type(inp["simulations"]) is not int
                or not 1 <= inp["simulations"] <= 16
                or type(inp["max_moves"]) is not int
                or not 2 <= inp["max_moves"] <= 200):
            raise ValueError("Seed/search/move budget invalid")
        cfg = SearchConfig(simulations=inp["simulations"], dirichlet_fraction=0)
        shard = selfplay_game(
            UniformPredictor(), rules, cfg, seed=inp["seed"],
            max_moves=inp["max_moves"], temperature=0, explore=False,
            revision="plan-c-local-worker-v1")
        validate_shard(shard)
        return self.artifacts.put_json(shard)

    def _validate(self, inp):
        self._exact(inp, ("shard_digest",))
        shard = json.loads(self.artifacts.get(inp["shard_digest"]))
        validate_shard(shard)
        return self.artifacts.put_json({
            "schema": "verified-shard-v1", "shard_digest": inp["shard_digest"],
            "record_digest": shard["record"]["digest"],
            "sample_count": len(shard["examples"]),
            "rules": shard["record"]["rules"],
        })

    def _learn(self, inp):
        self._exact(inp, ("shard_digests", "seed", "steps", "batch_size", "channels"))
        hashes = inp["shard_digests"]
        if (not isinstance(hashes, list) or not 1 <= len(hashes) <= 8
                or len(set(hashes)) != len(hashes)
                or any(type(inp[k]) is not int for k in
                       ("seed", "steps", "batch_size", "channels"))
                or not 1 <= inp["steps"] <= 20 or not 1 <= inp["batch_size"] <= 64
                or not 4 <= inp["channels"] <= 64):
            raise ValueError("Unbounded/invalid local training configuration")
        shards = []
        for digest in hashes:
            self._provenance(digest, "selfplay")
            shard = json.loads(self.artifacts.get(digest))
            validate_shard(shard)
            shards.append(shard)
        from go_game.training.network import NetworkConfig, PolicyValueNet
        from go_game.training.learner import Learner
        import torch

        torch.manual_seed(inp["seed"])
        size = shards[0]["record"]["rules"]["board_size"]
        learner = Learner(PolicyValueNet(
            NetworkConfig(size, channels=inp["channels"], blocks=1)),
            seed=inp["seed"])
        metrics = learner.train(shards, steps=inp["steps"],
                                batch_size=inp["batch_size"], augment=False)
        with tempfile.TemporaryDirectory() as folder:
            checkpoint = Path(folder) / "candidate.pt"
            manifest = learner.save(checkpoint)
            blob_digest = self.artifacts.put(checkpoint.read_bytes())
        return self.artifacts.put_json({
            "schema": "trained-model-bundle-v1", "checkpoint_artifact": blob_digest,
            "manifest": manifest, "metrics": metrics,
            "rules": shards[0]["record"]["rules"],
        })

    def _load_bundle(self, digest):
        self._provenance(digest, "learn")
        bundle = json.loads(self.artifacts.get(digest))
        if bundle.get("schema") != "trained-model-bundle-v1":
            raise ValueError("Unsupported model bundle")
        return bundle

    def _evaluate(self, inp):
        self._exact(inp, ("candidate_bundle", "champion_bundle",
                          "simulations", "pairs", "max_moves", "seed"))
        for key, low, high in (("simulations", 1, 8), ("pairs", 1, 4),
                               ("max_moves", 2, 200)):
            if type(inp[key]) is not int or not low <= inp[key] <= high:
                raise ValueError("Evaluation budget exceeds local worker cap")
        if type(inp["seed"]) is not int:
            raise ValueError("Evaluation seed must be integer")
        candidate, champion = (self._load_bundle(inp[k]) for k in
                               ("candidate_bundle", "champion_bundle"))
        if candidate["rules"] != champion["rules"]:
            raise ValueError("Candidate/champion rules differ")
        from go_game.training.learner import Learner
        from go_game.training.network import TorchPredictor
        from go_game.training.arena import evaluate_candidate

        with tempfile.TemporaryDirectory() as folder:
            predictors = []
            for label, bundle in (("candidate", candidate), ("champion", champion)):
                checkpoint = Path(folder) / (label + ".pt")
                checkpoint.write_bytes(
                    self.artifacts.get(bundle["checkpoint_artifact"]))
                model = Learner.load(checkpoint, device="cpu").model
                pred = TorchPredictor(model)
                if pred.model_id != bundle["manifest"]["model_id"]:
                    raise ValueError("Model registry digest mismatch")
                predictors.append(pred)
            report = evaluate_candidate(
                predictors[0], predictors[1],
                RuleSpec.from_dict(candidate["rules"]),
                SearchConfig(simulations=inp["simulations"], dirichlet_fraction=0),
                pairs=inp["pairs"], max_moves=inp["max_moves"],
                seed=inp["seed"])
        return self.artifacts.put_json(report)

    def _export(self, inp):
        self._exact(inp, ("model_bundle",))
        bundle = self._load_bundle(inp["model_bundle"])
        if bundle["manifest"]["checkpoint_sha256"] != bundle["checkpoint_artifact"]:
            raise ValueError("Model manifest does not match checkpoint artifact")
        return self.artifacts.put_json({
            "schema": "model-export-v1", "model_bundle": inp["model_bundle"],
            "model_id": bundle["manifest"]["model_id"],
            "checkpoint_artifact": bundle["checkpoint_artifact"],
            "rules": bundle["rules"], "published_as_champion": False,
        })

    def execute(self, job):
        budget = job["spec"]["budget"]
        if budget["cpu_seconds"] < 1:
            raise ValueError("Local executable job requires >=1 CPU second budget")
        kind = job["kind"]
        handlers = {"selfplay": self._selfplay, "validate_shard": self._validate,
                    "learn": self._learn, "evaluate": self._evaluate,
                    "export_model": self._export}
        return handlers[kind](job["spec"]["inputs"])

    def run_once(self, lease_seconds=120):
        job = self.jobs.claim(self.worker_id, lease_seconds)
        if job is None:
            return None
        done = threading.Event()
        heartbeat_error = []

        def heartbeat():
            while not done.wait(max(1, lease_seconds // 3)):
                try:
                    self.jobs.heartbeat(job["job_id"], self.worker_id,
                                        job["attempt"], lease_seconds)
                except PlatformError as exc:
                    heartbeat_error.append(exc)
                    break

        thread = threading.Thread(target=heartbeat, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            digest = self.execute(job)
            if time.monotonic() - started > job["spec"]["budget"]["cpu_seconds"]:
                raise RuntimeError("Declared CPU time budget exceeded")
            if heartbeat_error:
                raise heartbeat_error[0]
            result = self.jobs.finish(
                job["job_id"], self.worker_id, job["attempt"], digest)
        except Exception as exc:
            report_digest = self.artifacts.put_json({
                "schema": "job-failure-v1",
                "job_id": job["job_id"],
                "error_type": type(exc).__name__,
                "message": str(exc)[:400],
            })
            result = self.jobs.finish(
                job["job_id"], self.worker_id, job["attempt"],
                report_digest, failed=True)
        finally:
            done.set()
            thread.join(timeout=1)
        return result


def main():
    parser = argparse.ArgumentParser(description="Run bounded, trusted Go local worker")
    parser.add_argument("--db", default=os.environ.get("GO_PLATFORM_DB",
                                                      "runs/platform.sqlite3"))
    parser.add_argument("--artifacts", default=os.environ.get(
        "GO_PLATFORM_ARTIFACTS", "runs/artifacts"))
    parser.add_argument("--worker-id", default="go-local-1")
    parser.add_argument("--max-jobs", type=int, default=1)
    args = parser.parse_args()
    if not 1 <= args.max_jobs <= 1000:
        parser.error("--max-jobs must be 1..1000")
    runner = LocalWorker(PlatformStore(args.db), ArtifactStore(args.artifacts),
                         worker_id=args.worker_id)
    for _ in range(args.max_jobs):
        item = runner.run_once()
        if item is None:
            break
        print(json.dumps(item, sort_keys=True))


if __name__ == "__main__":
    main()
