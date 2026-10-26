"""End-to-end trusted Plan C worker chain: shard -> train -> arena -> export."""
import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

HAS_TORCH = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(HAS_TORCH, "PyTorch worker integration requires CPU torch")
class TestLocalTrainingWorker(unittest.TestCase):
    def test_worker_selfplay_learn_evaluate_export_and_provenance_guard(self):
        from go_game.core import RuleSpec
        from go_game.platform.storage import PlatformStore
        from go_game.platform.artifacts import ArtifactStore
        from go_game.platform.jobs import JobService
        from go_game.platform.worker import LocalWorker
        from go_game.training.dataset import validate_shard

        with tempfile.TemporaryDirectory() as root:
            store = PlatformStore(Path(root) / "db.sqlite3")
            objects = ArtifactStore(Path(root) / "artifacts")
            jobs = JobService(store)
            worker = LocalWorker(store, objects, "safe-ci-worker")

            def submit(kind, inputs, index):
                return jobs.submit(
                    "research-team", "operation-{}".format(index), kind, {
                        "experiment_id": "exp-1", "run_id": "run-1",
                        "inputs": inputs,
                        "budget": {"cpu_seconds": 120, "gpu_seconds": 0,
                                   "storage_mb": 16},
                    })

            submit("selfplay", {
                "rules": RuleSpec(board_size=2).to_dict(), "seed": 33,
                "simulations": 2, "max_moves": 200,
            }, 0)
            selfplay = worker.run_once()
            self.assertEqual(selfplay["status"], "succeeded")
            shard = json.loads(objects.get(selfplay["artifact_digest"]))
            self.assertTrue(validate_shard(shard))
            submit("learn", {
                "shard_digests": [selfplay["artifact_digest"]],
                "seed": 4, "steps": 1, "batch_size": 2, "channels": 8,
            }, 1)
            train = worker.run_once()
            self.assertEqual(train["status"], "succeeded")
            model = json.loads(objects.get(train["artifact_digest"]))
            self.assertEqual(model["schema"], "trained-model-bundle-v1")
            self.assertEqual(
                model["manifest"]["checkpoint_sha256"],
                model["checkpoint_artifact"])
            submit("evaluate", {
                "candidate_bundle": train["artifact_digest"],
                "champion_bundle": train["artifact_digest"],
                "simulations": 1, "pairs": 1, "max_moves": 200, "seed": 1,
            }, 2)
            eval_job = worker.run_once()
            self.assertEqual(eval_job["status"], "succeeded")
            arena = json.loads(objects.get(eval_job["artifact_digest"]))
            self.assertEqual(arena["schema"], "model-arena-v1")
            self.assertEqual(len(arena["games"]), 2)

            submit("export_model", {
                "model_bundle": train["artifact_digest"],
            }, 3)
            export = worker.run_once()
            self.assertEqual(export["status"], "succeeded")
            published = json.loads(objects.get(export["artifact_digest"]))
            self.assertFalse(published["published_as_champion"])
            self.assertEqual(published["model_id"], model["manifest"]["model_id"])

            fake = objects.put_json({"schema": "trained-model-bundle-v1"})
            submit("export_model", {"model_bundle": fake}, 4)
            denied = worker.run_once()
            self.assertEqual(denied["status"], "failed")
            failure = json.loads(objects.get(denied["artifact_digest"]))
            self.assertEqual(failure["schema"], "job-failure-v1")


if __name__ == "__main__":
    unittest.main()
