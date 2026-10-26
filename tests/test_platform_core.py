"""Plan C stdlib tests: real SQLite transactions, replay, CAS, leases, artifacts."""
import copy
import json
import os
import tempfile
import threading
import unittest
from pathlib import Path

from go_game.core import RuleSpec
from go_game.records import replay_and_verify
from go_game.platform import GameService, JobService, PlatformStore
from go_game.platform.analysis import AnalysisService
from go_game.platform.artifacts import ArtifactStore
from go_game.platform.errors import PlatformError


def make_spec(board_size=5):
    return RuleSpec(board_size=board_size, komi_half_points=11)


def job_spec():
    return {"experiment_id": "exp-1", "run_id": "run-1",
            "inputs": {"rule_id": "research-psk-v1"},
            "budget": {"cpu_seconds": 60, "gpu_seconds": 0, "storage_mb": 20}}


class BaseDb(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.file = Path(self.tmp.name) / "platform.sqlite3"
        self.store = PlatformStore(self.file)
        self.games = GameService(self.store)

    def create(self):
        return self.games.create(make_spec(), "alice", "bob")


class TestGames(BaseDb):
    def test_command_idempotency_and_stale_no_mutation(self):
        game = self.create()
        gid = game["game_id"]
        self.assertEqual(game["seq"], 0)
        first = self.games.command(gid, "cmd-1", 0, "alice",
                                   {"kind": "place", "row": 1, "col": 3})
        self.assertEqual(first, self.games.command(
            gid, "cmd-1", 0, "alice", {"kind": "place", "row": 1, "col": 3}))
        self.assertEqual(first["seq"], 1)
        self.assertEqual(first["board"][1][3], "X")
        self.assertEqual(first["to_play"], "O")
        self.assertEqual(first["accepted_event"]["seq"], 1)
        for command, expected_code in (
                (("cmd-1", 0, "alice", {"kind": "pass"}), "idempotency_conflict"),
                (("cmd-2", 0, "bob", {"kind": "pass"}), "stale_sequence"),
                (("cmd-3", 1, "alice", {"kind": "pass"}), "not_your_turn"),
                (("cmd-4", 1, "bob",
                  {"kind": "place", "row": 1, "col": 3}), "illegal_move")):
            with self.subTest(command=command), self.assertRaises(
                    PlatformError) as cm:
                self.games.command(gid, *command)
            self.assertEqual(cm.exception.code, expected_code)
        self.assertEqual(self.games.snapshot(gid)["seq"], 1)
        self.assertEqual(len(self.games.events(gid)["events"]), 1)

    def test_replay_and_restart_sgf_and_terminal(self):
        gid = self.create()["game_id"]
        for cmd, actor, seq in (("a", "alice", 0), ("b", "bob", 1)):
            self.games.command(gid, cmd, seq, actor, {"kind": "pass"})
        head = self.games.snapshot(gid)
        self.assertTrue(head["terminated"])
        self.assertEqual(head["score"]["winner"], "O")
        with self.assertRaises(PlatformError) as cm:
            self.games.command(gid, "c", 2, "alice", {"kind": "pass"})
        self.assertEqual(cm.exception.code, "game_terminated")
        resumed = GameService(PlatformStore(self.file))
        self.assertEqual(head, resumed.snapshot(gid))
        self.assertEqual(resumed.events(gid, after_seq=1)["events"][0]["seq"], 2)
        record = resumed.record(gid)
        self.assertTrue(replay_and_verify(record).state.terminated)
        self.assertIn(";B[];W[]", resumed.sgf(gid))

    def test_corrupted_storage_detected_not_silently_repaired(self):
        gid = self.create()["game_id"]
        self.games.command(gid, "a", 0, "alice", {"kind": "pass"})
        with self.store.write() as conn:
            conn.execute("UPDATE game_events SET event=? WHERE game_id=? AND seq=1",
                         (json.dumps({"seq": 1, "state_before": "forged"}), gid))
        with self.assertRaises(PlatformError) as cm:
            self.games.snapshot(gid)
        self.assertEqual(cm.exception.code, "corrupt_ledger")

    def test_50_conflicting_threads_exactly_one_winner(self):
        gid = self.create()["game_id"]
        barrier = threading.Barrier(12)
        successful, failed = [], []
        lock = threading.Lock()

        def writer(i):
            barrier.wait()
            try:
                out = self.games.command(
                    gid, "cmd-" + str(i), 0, "alice", {"kind": "pass"})
                with lock:
                    successful.append(out["seq"])
            except PlatformError as error:
                with lock:
                    failed.append(error.code)

        workers = [threading.Thread(target=writer, args=(i,)) for i in range(12)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(timeout=15)
            self.assertFalse(worker.is_alive(), "Concurrent writer hung")
        self.assertEqual(successful, [1])
        self.assertEqual(failed, ["stale_sequence"] * 11)
        self.assertEqual(len(self.games.events(gid)["events"]), 1)

    def test_action_rejection_and_observation_unchanged(self):
        gid = self.create()["game_id"]
        before = self.games.snapshot(gid)
        for action in ({"kind": "place", "row": True, "col": 0},
                       {"kind": "place", "row": 6, "col": 1},
                       {"kind": "pass", "row": 0},
                       {"kind": "place", "row": 0}):
            with self.assertRaises(PlatformError):
                self.games.command(gid, "bad", 0, "alice", action)
            self.assertEqual(self.games.snapshot(gid), before)

    def test_pinned_revision_analysis_returns_legality(self):
        gid = self.create()["game_id"]
        service = AnalysisService(self.games)
        report = service.analyze(gid, expected_seq=0, simulations=2)
        self.assertEqual(report["source_seq"], 0)
        self.assertEqual(report["simulation_count"], 2)
        self.assertEqual(sum(report["visits"]), 2)
        self.games.command(gid, "a", 0, "alice", {"kind": "pass"})
        with self.assertRaises(PlatformError) as cm:
            service.analyze(gid, 0, simulations=2)
        self.assertEqual(cm.exception.code, "stale_sequence")
        with self.assertRaises(PlatformError) as cm:
            service.analyze(gid, 1, model_id="other")
        self.assertEqual(cm.exception.code, "model_mismatch")


class TestJobs(BaseDb):
    def setUp(self):
        super().setUp()
        self.clock = [100.0]
        self.jobs = JobService(self.store, clock=lambda: self.clock[0])

    def test_idempotency_fencing_expiration_and_restart(self):
        created = self.jobs.submit("alice", "req-1", "selfplay", job_spec())
        self.assertEqual(self.jobs.submit("alice", "req-1", "selfplay", job_spec()),
                         created)
        with self.assertRaises(PlatformError) as cm:
            self.jobs.submit("alice", "req-1", "learn", job_spec())
        self.assertEqual(cm.exception.code, "idempotency_conflict")
        lease1 = self.jobs.claim("worker-A", lease_seconds=5)
        self.assertEqual(lease1["attempt"], 1)
        self.assertIsNone(self.jobs.claim("worker-Z", lease_seconds=5))
        self.clock[0] += 6
        lease2 = JobService(self.store, clock=lambda: self.clock[0]).claim(
            "worker-B", lease_seconds=5)
        self.assertEqual(lease2["attempt"], 2)
        for operation in (
                lambda: self.jobs.heartbeat(created["job_id"], "worker-A", 1),
                lambda: self.jobs.finish(created["job_id"], "worker-A", 1,
                                         "sha256:" + "0" * 64)):
            with self.assertRaises(PlatformError) as cm:
                operation()
            self.assertEqual(cm.exception.code, "stale_lease")
        result = self.jobs.finish(created["job_id"], "worker-B", 2,
                                  "sha256:" + "a" * 64)
        self.assertEqual(result["status"], "succeeded")
        self.assertIsNone(self.jobs.claim("worker-C"))
        with self.assertRaises(PlatformError):
            self.jobs.finish(created["job_id"], "worker-B", 2,
                             "sha256:" + "a" * 64)

    def test_cancel_and_role_guard(self):
        created = self.jobs.submit("alice", "req-2", "evaluate", job_spec())
        with self.assertRaises(PlatformError) as cm:
            self.jobs.cancel(created["job_id"], "bob")
        self.assertEqual(cm.exception.code, "forbidden")
        cancelled = self.jobs.cancel(created["job_id"], "alice")
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertIsNone(self.jobs.claim("operator"))
        with self.assertRaises(PlatformError):
            self.jobs.cancel(created["job_id"], "alice")

    def test_spec_resource_budget_rejects_invalid_inputs(self):
        bad = job_spec()
        bad["budget"]["gpu_seconds"] = float("inf")
        with self.assertRaises(PlatformError):
            self.jobs.submit("alice", "bad", "learn", bad)
        self.assertIsNone(self.jobs.claim("operator"))


    def test_local_worker_executes_only_builtin_jobs_and_persists_valid_data(self):
        from go_game.platform.worker import LocalWorker
        from go_game.platform.artifacts import ArtifactStore
        from go_game.training.dataset import validate_shard

        jobs = JobService(self.store)
        objects = ArtifactStore(Path(self.tmp.name) / "worker-objects")
        worker = LocalWorker(self.store, objects, "trusted-operator")
        config = {
            "experiment_id": "worker-exp", "run_id": "trial-1",
            "inputs": {
                "rules": make_spec(2).to_dict(), "seed": 21,
                "simulations": 2, "max_moves": 200,
            },
            "budget": {"cpu_seconds": 60, "gpu_seconds": 0, "storage_mb": 10},
        }
        created = jobs.submit("researcher", "do-selfplay", "selfplay", config)
        result = worker.run_once()
        self.assertEqual(result["job_id"], created["job_id"])
        self.assertEqual(result["status"], "succeeded")
        shard = json.loads(objects.get(result["artifact_digest"]))
        self.assertTrue(validate_shard(shard))
        validate = dict(config, inputs={"shard_digest": result["artifact_digest"]})
        jobs.submit("researcher", "check-shard", "validate_shard", validate)
        verified = worker.run_once()
        self.assertEqual(verified["status"], "succeeded")
        record = json.loads(objects.get(verified["artifact_digest"]))
        self.assertEqual(record["schema"], "verified-shard-v1")
        self.assertIsNone(worker.run_once())


class TestArtifacts(BaseDb):

    def test_put_idempotent_integrity_and_traversal(self):
        store = ArtifactStore(Path(self.tmp.name) / "objects", max_bytes=100)
        digest = store.put(b"hello\n")
        self.assertEqual(store.put(b"hello\n"), digest)
        self.assertEqual(store.get(digest), b"hello\n")
        with self.assertRaises(PlatformError):
            store.get("../invalid")
        with self.assertRaises(PlatformError):
            store.put(b"x" * 101)
        (Path(self.tmp.name) / "objects" / digest.split(":")[1]).write_bytes(b"tamper")
        with self.assertRaises(PlatformError) as cm:
            store.get(digest)
        self.assertEqual(cm.exception.code, "artifact_integrity")


if __name__ == "__main__":
    unittest.main()
