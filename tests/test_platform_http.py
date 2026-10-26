"""Plan C HTTP security, command/reconnect and job worker integration tests."""
import importlib.util
import tempfile
import unittest
from pathlib import Path

HAS_API = (importlib.util.find_spec("fastapi") is not None and
           importlib.util.find_spec("httpx") is not None)


@unittest.skipUnless(HAS_API, "Install optional FastAPI + httpx test dependencies")
class TestHTTP(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from go_game.platform.api import create_app

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.tokens = {
            "long-test-alice-token": {"subject": "alice", "role": "player"},
            "long-test-bob-token": {"subject": "bob", "role": "player"},
            "long-test-viewer-token": {"subject": "spectator", "role": "viewer"},
            "long-test-owner-token": {"subject": "research", "role": "researcher"},
            "long-test-operator-token": {"subject": "ops", "role": "operator"},
        }
        self.app = create_app(
            str(Path(self.tmp.name) / "db.sqlite"), tokens=self.tokens,
            artifact_path=str(Path(self.tmp.name) / "blobs"))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    @staticmethod
    def headers(subject):
        return {"Authorization": "Bearer long-test-" + subject + "-token"}

    @staticmethod
    def rules(n=5):
        from go_game.core import RuleSpec
        return RuleSpec(board_size=n).to_dict()

    def new_game(self):
        r = self.client.post("/v1/games", json={
            "rules": self.rules(), "black_actor": "alice", "white_actor": "bob"},
            headers=self.headers("alice"))
        self.assertEqual(r.status_code, 200, r.text)
        return r.json()["game_id"]

    def test_authentication_read_only_and_no_impersonation(self):
        self.assertEqual(self.client.get("/v1/me").status_code, 401)
        self.assertEqual(
            self.client.get("/v1/me", headers=self.headers("bad")).status_code, 401)
        self.assertEqual(
            self.client.post("/v1/games", json={}, headers=self.headers("viewer")
                             ).status_code, 403)
        gid = self.new_game()
        move = {"command_id": "first", "expected_seq": 0, "actor_id": "bob",
                "action": {"kind": "pass"}}
        self.assertEqual(self.client.post(
            "/v1/games/" + gid + "/commands", json=move,
            headers=self.headers("alice")).status_code, 403)
        self.assertEqual(self.client.post(
            "/v1/games/" + gid + "/commands", json=move,
            headers=self.headers("viewer")).status_code, 403)
        viewer = self.client.get("/v1/games/" + gid,
                                 headers=self.headers("viewer"))
        self.assertEqual(viewer.status_code, 200)
        self.assertEqual(viewer.json()["seq"], 0)

    def test_create_move_stale_reconnect_sgf_analysis(self):
        gid = self.new_game()
        first = {"command_id": "move1", "expected_seq": 0,
                 "actor_id": "alice", "action": {"kind": "pass"}}
        url = "/v1/games/" + gid
        r = self.client.post(url + "/commands", json=first,
                             headers=self.headers("alice"))
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["seq"], 1)
        self.assertEqual(self.client.post(
            url + "/commands", json=first,
            headers=self.headers("alice")).json(), r.json())
        stale = dict(first, command_id="different", expected_seq=0)
        result = self.client.post(url + "/commands", json=stale,
                                  headers=self.headers("alice"))
        self.assertEqual(result.status_code, 409)
        self.assertEqual(result.json()["error"]["code"], "stale_sequence")
        page = self.client.get(url + "/events?after_seq=0",
                               headers=self.headers("viewer"))
        self.assertEqual([x["seq"] for x in page.json()["events"]], [1])
        analysis = self.client.post(
            url + "/analysis", json={"expected_seq": 1, "simulations": 2},
            headers=self.headers("bob"))
        self.assertEqual(analysis.status_code, 200, analysis.text)
        self.assertEqual(analysis.json()["source_seq"], 1)
        self.assertEqual(analysis.json()["model_id"], "uniform-baseline-v1")
        second = self.client.post(url + "/commands", json={
            "command_id": "move2", "expected_seq": 1, "actor_id": "bob",
            "action": {"kind": "pass"}}, headers=self.headers("bob"))
        self.assertEqual(second.status_code, 200, second.text)
        self.assertTrue(second.json()["terminated"])
        record = self.client.get(url + "/record", headers=self.headers("viewer"))
        from go_game.records import replay_and_verify
        self.assertTrue(replay_and_verify(record.json()).state.terminated)
        sgf = self.client.get(url + "/sgf", headers=self.headers("viewer"))
        self.assertEqual(sgf.status_code, 200)
        self.assertIn(";B[];W[]", sgf.text)
        new_client = type(self.client)(self.app)
        try:
            resumed = new_client.get(url + "/events?after_seq=1",
                                     headers=self.headers("bob"))
            self.assertEqual([x["seq"] for x in resumed.json()["events"]], [2])
        finally:
            new_client.close()

    def test_job_lease_artifact_approval_and_fencing(self):
        from tests.test_platform_core import job_spec
        job = self.client.post("/v1/jobs", json={
            "kind": "selfplay", "request_key": "case-1", "spec": job_spec()},
            headers=self.headers("owner"))
        self.assertEqual(job.status_code, 200, job.text)
        jid = job.json()["job_id"]
        self.assertEqual(self.client.get(
            "/v1/jobs/" + jid, headers=self.headers("alice")).status_code, 403)
        self.assertEqual(self.client.post("/v1/workers/lease", json={
            "worker_id": "worker-1"}, headers=self.headers("owner")).status_code, 403)
        claim = self.client.post("/v1/workers/lease", json={
            "worker_id": "worker-1"}, headers=self.headers("operator"))
        self.assertEqual(claim.status_code, 200, claim.text)
        self.assertEqual(claim.json()["job"]["job_id"], jid)
        missing = self.client.post("/v1/jobs/" + jid + "/complete", json={
            "worker_id": "worker-1", "attempt": 1,
            "digest": "sha256:" + "0" * 64}, headers=self.headers("operator"))
        self.assertEqual(missing.status_code, 404)
        blob = self.client.post("/v1/artifacts", content=b"verified-result",
                                headers=self.headers("owner"))
        self.assertEqual(blob.status_code, 200, blob.text)
        result = self.client.post("/v1/jobs/" + jid + "/complete", json={
            "worker_id": "worker-1", "attempt": 1, "digest": blob.json()["digest"]},
            headers=self.headers("operator"))
        self.assertEqual(result.status_code, 200, result.text)
        self.assertEqual(result.json()["status"], "succeeded")
        self.assertEqual(self.client.get(
            "/v1/artifacts/" + blob.json()["digest"], headers=self.headers("owner")
            ).json()["verified"], True)
        repeated = self.client.post("/v1/jobs/" + jid + "/complete", json={
            "worker_id": "worker-1", "attempt": 1, "digest": blob.json()["digest"]},
            headers=self.headers("operator"))
        self.assertEqual(repeated.status_code, 409)

    def test_bad_schema_and_token_configuration_fail_closed(self):
        from go_game.platform.api import create_app
        with self.assertRaises(RuntimeError):
            create_app(str(Path(self.tmp.name) / "bad.sqlite"), tokens={})
        invalid = self.client.post("/v1/games", json={
            "rules": dict(self.rules(), rule_id="research-ssk-v1"),
            "black_actor": "alice", "white_actor": "bob"},
            headers=self.headers("alice"))
        self.assertEqual(invalid.status_code, 422)
        unexpected = self.client.post("/v1/games", json={
            "rules": self.rules(), "black_actor": "alice",
            "white_actor": "bob", "hidden": True}, headers=self.headers("alice"))
        self.assertEqual(unexpected.status_code, 422)


if __name__ == "__main__":
    unittest.main()
