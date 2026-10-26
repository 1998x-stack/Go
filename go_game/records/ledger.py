"""Append-only, self-verifying in-memory Go game ledger (schema game-record-v1)."""
import hashlib
import json

from go_game.core import RuleSpec, RulesEngine


def _digest(value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)
    return hashlib.sha256(data.encode("ascii")).hexdigest()


class EventLedger:
    def __init__(self, rules=None, seed=None):
        if seed is not None and type(seed) is not int:
            raise ValueError("seed must be an int or None")
        self.engine = RulesEngine()
        self.state = self.engine.new_game(rules or RuleSpec())
        self.seed = seed
        self._events = []

    @property
    def events(self):
        return tuple(dict(event) for event in self._events)

    def append(self, action):
        before = self.state.fingerprint
        actor = self.state.current_player
        result = self.engine.try_apply(self.state, action)
        if not result.ok:
            raise ValueError(result.reason)
        event = {
            "seq": len(self._events), "actor": actor, "action": action,
            "state_before": before, "state_after": self.state.fingerprint,
        }
        self._events.append(event)
        return dict(event)

    def to_record(self):
        value = {
            "schema": "game-record-v1",
            "rules": self.state.rules.to_dict(),
            "seed": self.seed,
            "initial_state": self.engine.new_game(self.state.rules).fingerprint,
            "events": [dict(event) for event in self._events],
            "outcome": (self.engine.score(self.state).winner
                        if self.state.terminated else None),
            "terminated": self.state.terminated,
        }
        value["digest"] = _digest(value)
        return value


def replay_and_verify(record):
    """Fail closed on schema changes, illegal actions, tampering or missing events."""
    if not isinstance(record, dict) or record.get("schema") != "game-record-v1":
        raise ValueError("Unsupported record schema")
    required = {"schema", "rules", "seed", "initial_state", "events",
                "outcome", "terminated", "digest"}
    if set(record) != required or not isinstance(record["events"], list):
        raise ValueError("Unexpected game-record-v1 fields")
    if len(record["events"]) > 10000:
        raise ValueError("Record exceeds maximum supported move count")
    raw = dict(record)
    supplied_digest = raw.pop("digest", None)
    if not isinstance(supplied_digest, str) or _digest(raw) != supplied_digest:
        raise ValueError("Record digest mismatch")
    rules = RuleSpec.from_dict(record["rules"])
    ledger = EventLedger(rules, record.get("seed"))
    if ledger.state.fingerprint != record.get("initial_state"):
        raise ValueError("Initial state mismatch")
    for seq, event in enumerate(record["events"]):
        if type(event.get("action")) is not int or event.get("seq") != seq:
            raise ValueError("Non-contiguous sequence or invalid action")
        if (event.get("actor") != ledger.state.current_player
                or event.get("state_before") != ledger.state.fingerprint):
            raise ValueError("Actor/state precondition mismatch")
        rebuilt = ledger.append(event["action"])
        if rebuilt != event:
            raise ValueError("Move transition mismatch")
    if record.get("terminated") != ledger.state.terminated:
        raise ValueError("Terminal flag mismatch")
    if record.get("outcome") != ledger.to_record()["outcome"]:
        raise ValueError("Scoring/outcome mismatch")
    return ledger
