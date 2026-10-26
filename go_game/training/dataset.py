"""Content-addressed, replay-validated policy/value samples and atomic shards."""
import hashlib
import json
import math
import os
import tempfile
from dataclasses import asdict

from go_game.core import RuleSpec, RulesEngine
from go_game.records import replay_and_verify
from go_game.rl.features import OBS_SPEC, encode_observation


SCHEMA = "go-sample-v1"
MAX_SHARD_BYTES = 100 * 1024 * 1024


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False, ensure_ascii=True).encode("ascii")


def content_digest(value):
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def create_shard(record, examples, model_id, search_config, revision="uncommitted"):
    """Fully validate the source episode before returning an immutable shard."""
    if not isinstance(model_id, str) or not model_id:
        raise ValueError("Missing pinned model id")
    shard = {
        "schema": SCHEMA,
        "record": record,
        "model_id": model_id,
        "search_config": asdict(search_config),
        "search_config_id": content_digest(asdict(search_config)),
        "observation_spec_id": OBS_SPEC,
        "action_spec_id": "row-major-pass-last-v1",
        "reward_spec_id": "terminal-zero-sum-v1",
        "code_revision": revision,
        "examples": examples,
    }
    validate_shard(shard)
    shard["digest"] = content_digest(shard)
    return shard


def validate_shard(shard):
    if not isinstance(shard, dict):
        raise ValueError("Not a shard object")
    expected = {"schema", "record", "model_id", "search_config",
                "search_config_id", "observation_spec_id", "action_spec_id",
                "reward_spec_id", "code_revision", "examples"}
    if set(shard) not in (expected, expected | {"digest"}):
        raise ValueError("Unexpected shard schema fields")
    if (shard["schema"] != SCHEMA or shard["observation_spec_id"] != OBS_SPEC
            or shard["action_spec_id"] != "row-major-pass-last-v1"
            or shard["reward_spec_id"] != "terminal-zero-sum-v1"):
        raise ValueError("Incompatible training data ABI")
    if content_digest(shard["search_config"]) != shard["search_config_id"]:
        raise ValueError("Search config mismatch")
    if "digest" in shard:
        unhashed = {k: v for k, v in shard.items() if k != "digest"}
        if content_digest(unhashed) != shard["digest"]:
            raise ValueError("Shard digest mismatch")
    record = shard["record"]
    final_ledger = replay_and_verify(record)
    if not final_ledger.state.terminated or record["outcome"] is None:
        raise ValueError("Incomplete/truncated games cannot train a final value")
    examples = shard["examples"]
    if not isinstance(examples, list) or len(examples) != len(record["events"]):
        raise ValueError("One sample per canonical event is required")
    rules = RuleSpec.from_dict(record["rules"])
    engine = RulesEngine()
    state = engine.new_game(rules)
    winner = record["outcome"]
    n = rules.board_size
    config = shard["search_config"]
    if (type(config.get("simulations")) is not int
            or config["simulations"] < 1):
        raise ValueError("Invalid recorded search budget")
    for ply, (sample, event) in enumerate(zip(examples, record["events"])):
        if not isinstance(sample, dict):
            raise ValueError("Invalid sample")
        needed = {"ply", "to_play", "state_fingerprint", "action",
                  "planes", "mask", "visits", "pi", "root_value", "z"}
        if set(sample) != needed:
            raise ValueError("Unexpected sample fields")
        obs = encode_observation(state, engine)
        if (sample["ply"] != ply or sample["to_play"] != state.current_player
                or sample["state_fingerprint"] != state.fingerprint
                or sample["action"] != event["action"]
                or sample["planes"] != [[list(row) for row in plane]
                                        for plane in obs.planes]
                or sample["mask"] != list(obs.action_mask)):
            raise ValueError("Sample observation/actor/action replay mismatch")
        counts, target = sample["visits"], sample["pi"]
        if (len(counts) != n * n + 1 or len(target) != n * n + 1
                or not all(type(v) is int and v >= 0 for v in counts)
                or sum(counts) != config["simulations"]):
            raise ValueError("Invalid MCTS visit counts")
        if any(counts[a] and not obs.action_mask[a] for a in range(len(counts))):
            raise ValueError("Illegal action has nonzero search visits")
        if not all(isinstance(v, (int, float)) and math.isfinite(v)
                   for v in target):
            raise ValueError("Nonfinite policy targets")
        if any(abs(float(v) - count / sum(counts)) > 1e-7
               for v, count in zip(target, counts)):
            raise ValueError("Policy targets disagree with search visits")
        z = (0 if winner == "draw" else
             1 if winner == state.current_player else -1)
        if sample["z"] != z:
            raise ValueError("Target value is not actor-perspective terminal result")
        if (not isinstance(sample["root_value"], (float, int))
                or not math.isfinite(sample["root_value"])
                or abs(sample["root_value"]) > 1.000001):
            raise ValueError("Invalid root value")
        outcome = engine.try_apply(state, sample["action"])
        if not outcome.ok:
            raise ValueError("Replay detected illegal action")
    if state.fingerprint != final_ledger.state.fingerprint:
        raise ValueError("Final state mismatch")
    return True


def write_shard(path, shard):
    """Immutable publish: write+fsync temp, then atomic rename in same directory."""
    validate_shard(shard)
    payload = canonical_bytes(shard)
    if len(payload) > MAX_SHARD_BYTES:
        raise ValueError("Shard too large")
    target = os.path.abspath(os.fspath(path))
    os.makedirs(os.path.dirname(target), exist_ok=True)
    if os.path.exists(target):
        with open(target, "rb") as previous:
            if previous.read() == payload:
                return shard["digest"]
        raise FileExistsError("Shard names are immutable; use a new content ID")
    fd, temp = tempfile.mkstemp(prefix=".uncommitted-", dir=os.path.dirname(target))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        # One process per shard ID in this single-process store. A concurrent
        # multi-host producer requires an external CAS/lease (Plan C).
        if os.path.exists(target):
            raise FileExistsError("Concurrent shard writer")
        os.replace(temp, target)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return shard["digest"]


def read_shard(path):
    with open(path, "rb") as stream:
        data = stream.read(MAX_SHARD_BYTES + 1)
    if len(data) > MAX_SHARD_BYTES:
        raise ValueError("Shard exceeds size limit")
    value = json.loads(data)
    validate_shard(value)
    return value
