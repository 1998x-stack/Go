"""Idempotent jobs and fencing-token leases for a single-host control plane."""
import hashlib
import json
import math
import re
import time
import uuid

from .errors import PlatformError
from .games import utc_now
from .storage import encode


ALLOWED_KINDS = {"selfplay", "validate_shard", "learn", "evaluate", "export_model"}
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")


def _job(row):
    return {"schema": "experiment-job-v1", "job_id": row["id"],
            "owner": row["owner"], "kind": row["kind"],
            "spec": json.loads(row["spec"]), "status": row["status"],
            "attempt": row["attempt"], "lease_owner": row["lease_owner"],
            "lease_until": row["lease_until"],
            "artifact_digest": row["artifact_digest"]}


class JobService:
    def __init__(self, store, clock=None):
        self.store = store
        self.clock = clock or time.time

    def submit(self, owner, idempotency_key, kind, spec):
        if not isinstance(owner, str) or not 1 <= len(owner) <= 80:
            raise PlatformError("invalid_owner", "Invalid owner", 422)
        if (not isinstance(idempotency_key, str)
                or not 1 <= len(idempotency_key) <= 120):
            raise PlatformError("invalid_key", "Invalid job idempotency key", 422)
        if kind not in ALLOWED_KINDS:
            raise PlatformError("invalid_kind", "Unknown job kind", 422)
        if not isinstance(spec, dict):
            raise PlatformError("invalid_spec", "Expected experiment parameters", 422)
        if set(spec) != {"experiment_id", "run_id", "inputs", "budget"}:
            raise PlatformError("invalid_spec", "Incorrect experiment manifest fields", 422)
        if any(not isinstance(spec[k], str) or not 1 <= len(spec[k]) <= 120
               for k in ("experiment_id", "run_id")):
            raise PlatformError("invalid_spec", "Invalid experiment/run id", 422)
        if not isinstance(spec["inputs"], dict) or len(spec["inputs"]) > 40:
            raise PlatformError("invalid_spec", "Inputs must be a bounded manifest", 422)
        budget = spec["budget"]
        if not isinstance(budget, dict) or set(budget) != {
                "cpu_seconds", "gpu_seconds", "storage_mb"}:
            raise PlatformError("invalid_budget", "CPU/GPU/storage budget required", 422)
        for key, maximum in (("cpu_seconds", 86400), ("gpu_seconds", 86400),
                             ("storage_mb", 102400)):
            value = budget[key]
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or value < 0 or value > maximum):
                raise PlatformError("invalid_budget", "Resource limit is invalid", 422)
        try:
            serialized = encode({"kind": kind, "spec": spec})
        except (TypeError, ValueError) as exc:
            raise PlatformError("invalid_spec", "Not a JSON-safe manifest", 422) from exc
        if len(serialized) > 16384:
            raise PlatformError("invalid_spec", "Manifest too large", 422)
        digest = hashlib.sha256(serialized.encode("ascii")).hexdigest()
        with self.store.write() as conn:
            previous = conn.execute(
                "SELECT * FROM jobs WHERE owner=? AND request_key=?",
                (owner, idempotency_key)).fetchone()
            if previous is not None:
                if previous["spec_hash"] != digest:
                    raise PlatformError("idempotency_conflict",
                                        "Job key reused with different manifest", 409)
                return _job(previous)
            job_id, now = uuid.uuid4().hex, utc_now()
            conn.execute("""
                INSERT INTO jobs(id,owner,kind,request_key,spec_hash,spec,status,
                                 attempt,created_utc,updated_utc)
                VALUES(?,?,?,?,?,?,'queued',0,?,?)
            """, (job_id, owner, kind, idempotency_key, digest,
                  encode(spec), now, now))
            return _job(conn.execute("SELECT * FROM jobs WHERE id=?",
                                     (job_id,)).fetchone())

    def get(self, job_id):
        with self.store.connection() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise PlatformError("job_not_found", "Unknown job", 404)
            return _job(row)

    def claim(self, worker_id, lease_seconds=30, kinds=None):
        if not isinstance(worker_id, str) or not 1 <= len(worker_id) <= 80:
            raise PlatformError("invalid_worker", "Worker ID is invalid", 422)
        if (type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600):
            raise PlatformError("invalid_lease", "Lease must be 1..3600 seconds", 422)
        allowed = set(kinds) if kinds is not None else ALLOWED_KINDS
        if not allowed or not allowed.issubset(ALLOWED_KINDS):
            raise PlatformError("invalid_kind", "Invalid worker job types", 422)
        now = float(self.clock())
        with self.store.write() as conn:
            marks = ",".join("?" for _ in allowed)
            row = conn.execute(
                "SELECT * FROM jobs WHERE kind IN (" + marks + ") AND "
                "(status='queued' OR (status='leased' AND lease_until<=?)) "
                "ORDER BY created_utc,id LIMIT 1",
                tuple(sorted(allowed)) + (now,)).fetchone()
            if row is None:
                return None
            conn.execute("""
                UPDATE jobs SET status='leased',attempt=attempt+1,
                       lease_owner=?,lease_until=?,updated_utc=? WHERE id=?
            """, (worker_id, now + lease_seconds, utc_now(), row["id"]))
            return self.get_from_connection(conn, row["id"])

    @staticmethod
    def get_from_connection(conn, job_id):
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return _job(row)

    def _guard(self, conn, job_id, worker_id, attempt):
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise PlatformError("job_not_found", "Unknown job", 404)
        if (row["status"] != "leased" or row["lease_owner"] != worker_id
                or type(attempt) is not int or row["attempt"] != attempt
                or row["lease_until"] <= self.clock()):
            raise PlatformError("stale_lease", "Worker lease has expired or been fenced", 409)
        return row

    def heartbeat(self, job_id, worker_id, attempt, lease_seconds=30):
        if type(lease_seconds) is not int or not 1 <= lease_seconds <= 3600:
            raise PlatformError("invalid_lease", "Lease must be 1..3600 seconds", 422)
        with self.store.write() as conn:
            self._guard(conn, job_id, worker_id, attempt)
            conn.execute("UPDATE jobs SET lease_until=?,updated_utc=? WHERE id=?",
                         (self.clock() + lease_seconds, utc_now(), job_id))
            return self.get_from_connection(conn, job_id)

    def finish(self, job_id, worker_id, attempt, artifact_digest=None, failed=False):
        if not failed and (not isinstance(artifact_digest, str)
                           or not SHA256_RE.fullmatch(artifact_digest)):
            raise PlatformError("invalid_artifact", "Completed job needs SHA256 artifact", 422)
        with self.store.write() as conn:
            self._guard(conn, job_id, worker_id, attempt)
            conn.execute("""
                UPDATE jobs SET status=?,artifact_digest=?,lease_owner=NULL,
                       lease_until=NULL,updated_utc=? WHERE id=?
            """, ("failed" if failed else "succeeded", artifact_digest,
                  utc_now(), job_id))
            return self.get_from_connection(conn, job_id)

    def cancel(self, job_id, owner, operator=False):
        with self.store.write() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise PlatformError("job_not_found", "Unknown job", 404)
            if row["owner"] != owner and not operator:
                raise PlatformError("forbidden", "Cannot cancel another user's job", 403)
            if row["status"] in ("succeeded", "failed", "cancelled"):
                raise PlatformError("terminal_job", "Job is already completed", 409)
            conn.execute("""
                UPDATE jobs SET status='cancelled',lease_owner=NULL,
                       lease_until=NULL,updated_utc=? WHERE id=?
            """, (utc_now(), job_id))
            return self.get_from_connection(conn, job_id)
