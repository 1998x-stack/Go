"""Authoritative Go game commands, replay verification, CAS and idempotency.

Every accepted move and its response commit together under SQLite BEGIN IMMEDIATE.
No client-supplied board or hash is ever treated as authoritative.
"""
import hashlib
import json
import uuid
from datetime import datetime, timezone

from go_game.core import RuleSpec
from go_game.records import EventLedger, replay_and_verify
from sgf import game_to_sgf

from .errors import PlatformError
from .storage import encode


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def _hash(value):
    return hashlib.sha256(encode(value).encode("ascii")).hexdigest()


def _game_id(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 80:
        raise PlatformError("invalid_id", "Invalid game ID", 400)
    return value


def _move(action, size):
    if not isinstance(action, dict) or action.get("kind") not in ("place", "pass"):
        raise PlatformError("invalid_action", "Expected place or pass action", 422)
    if action["kind"] == "pass":
        if set(action) != {"kind"}:
            raise PlatformError("invalid_action", "Pass does not take coordinates", 422)
        return size * size
    if set(action) != {"kind", "row", "col"}:
        raise PlatformError("invalid_action", "Place requires row and col", 422)
    row, col = action["row"], action["col"]
    if (type(row) is not int or type(col) is not int
            or not (0 <= row < size and 0 <= col < size)):
        raise PlatformError("invalid_action", "Coordinates out of bounds", 422)
    return row * size + col


def _action_dict(action, size):
    if action == size * size:
        return {"kind": "pass"}
    row, col = divmod(action, size)
    return {"kind": "place", "row": row, "col": col}


class GameService:
    def __init__(self, store):
        self.store = store

    def create(self, rule_spec, black_actor, white_actor, model_id="uniform-baseline-v1"):
        if not isinstance(rule_spec, RuleSpec):
            raise PlatformError("invalid_rules", "Expected versioned RuleSpec", 422)
        if rule_spec.board_size > 19 or rule_spec.handicap:
            raise PlatformError("unsupported_rules", "Platform supports <=19 and no handicap",
                                422)
        if (not all(isinstance(x, str) and 1 <= len(x) <= 80 for x in
                    (black_actor, white_actor)) or black_actor == white_actor):
            raise PlatformError("invalid_actors", "Two distinct named actors required", 422)
        if not isinstance(model_id, str) or not 1 <= len(model_id) <= 150:
            raise PlatformError("invalid_model", "Invalid model identifier", 422)
        game_id = uuid.uuid4().hex
        ledger = EventLedger(rule_spec)
        with self.store.write() as conn:
            conn.execute("""
                INSERT INTO games(id,rules,black_actor,white_actor,model_id,seq,
                                  state_hash,terminated,created_utc)
                VALUES(?,?,?,?,?,0,?,0,?)
            """, (game_id, encode(rule_spec.to_dict()), black_actor, white_actor,
                  model_id, ledger.state.fingerprint, utc_now()))
        return self.snapshot(game_id)

    def _row(self, conn, game_id):
        row = conn.execute("SELECT * FROM games WHERE id=?", (_game_id(game_id),)).fetchone()
        if row is None:
            raise PlatformError("game_not_found", "Game does not exist", 404)
        return row

    def _rehydrate(self, conn, row):
        rules = RuleSpec.from_dict(json.loads(row["rules"]))
        ledger = EventLedger(rules)
        event_rows = conn.execute(
            "SELECT seq,event FROM game_events WHERE game_id=? ORDER BY seq",
            (row["id"],)).fetchall()
        if len(event_rows) != row["seq"]:
            raise PlatformError("corrupt_ledger", "Event sequence has gaps", 500)
        for index, stored in enumerate(event_rows, 1):
            event = json.loads(stored["event"])
            if (stored["seq"] != index or event["seq"] != index
                    or event["state_before"] != ledger.state.fingerprint
                    or event["actor"] != ledger.state.current_player):
                raise PlatformError("corrupt_ledger", "Game event precondition mismatch", 500)
            try:
                result = ledger.append(event["action"])
            except (ValueError, TypeError) as exc:
                raise PlatformError("corrupt_ledger", "Stored move is invalid", 500) from exc
            if (result["state_after"] != event["state_after"]
                    or result["seq"] != index - 1):
                raise PlatformError("corrupt_ledger", "Game event state mismatch", 500)
        if (ledger.state.fingerprint != row["state_hash"]
                or int(ledger.state.terminated) != row["terminated"]):
            raise PlatformError("corrupt_ledger", "Game head does not match replay", 500)
        return ledger

    @staticmethod
    def _snapshot(row, ledger):
        state = ledger.state
        return {
            "schema": "game-snapshot-v1", "game_id": row["id"], "seq": row["seq"],
            "state_hash": state.fingerprint, "rules": state.rules.to_dict(),
            "board": [[v if v is not None else "." for v in rank] for rank in state.board],
            "to_play": state.current_player, "terminated": state.terminated,
            "passes": state.consecutive_passes,
            "legal_actions": list(ledger.engine.legal_actions(state)),
            "black_actor": row["black_actor"], "white_actor": row["white_actor"],
            "model_id": row["model_id"],
            "score": (vars(ledger.engine.score(state)) if state.terminated else None),
        }

    def snapshot(self, game_id):
        with self.store.connection() as conn:
            row = self._row(conn, game_id)
            return self._snapshot(row, self._rehydrate(conn, row))

    def snapshot_and_state(self, game_id):
        with self.store.connection() as conn:
            row = self._row(conn, game_id)
            ledger = self._rehydrate(conn, row)
            return self._snapshot(row, ledger), ledger.state.clone()

    def command(self, game_id, command_id, expected_seq, actor_id, action):
        if (not isinstance(command_id, str) or not 1 <= len(command_id) <= 120
                or not isinstance(actor_id, str) or not 1 <= len(actor_id) <= 80
                or type(expected_seq) is not int or expected_seq < 0):
            raise PlatformError("invalid_command", "Bad command ID, actor or seq", 422)
        with self.store.write() as conn:
            row = self._row(conn, game_id)
            size = RuleSpec.from_dict(json.loads(row["rules"])).board_size
            index = _move(action, size)
            payload = {"command_id": command_id, "expected_seq": expected_seq,
                       "actor_id": actor_id, "action": _action_dict(index, size)}
            payload_hash = _hash(payload)
            prior = conn.execute(
                "SELECT payload_hash,response FROM game_events "
                "WHERE game_id=? AND command_id=?", (game_id, command_id)).fetchone()
            if prior is not None:
                if prior["payload_hash"] != payload_hash:
                    raise PlatformError("idempotency_conflict",
                                        "Command ID reused with different payload", 409)
                return json.loads(prior["response"])
            if expected_seq != row["seq"]:
                raise PlatformError("stale_sequence", "Expected sequence is outdated", 409,
                                    current_seq=row["seq"], state_hash=row["state_hash"])
            if row["terminated"]:
                raise PlatformError("game_terminated", "Game has already ended", 409)
            ledger = self._rehydrate(conn, row)
            expected_actor = (row["black_actor"] if ledger.state.current_player == "X"
                              else row["white_actor"])
            if actor_id != expected_actor:
                raise PlatformError("not_your_turn", "Actor is not authorized to move", 403)
            try:
                event = ledger.append(index)
            except ValueError as exc:
                raise PlatformError("illegal_move", str(exc), 422) from exc
            seq = row["seq"] + 1
            accepted_event = {
                "schema": "go-game-event-v1", "game_id": game_id, "seq": seq,
                "event_id": uuid.uuid4().hex, "command_id": command_id,
                "actor_id": actor_id, "actor": event["actor"],
                "action": event["action"], "move": payload["action"],
                "state_before": event["state_before"],
                "state_after": event["state_after"],
            }
            response = self._snapshot(dict(row, seq=seq), ledger)
            response["accepted_event"] = accepted_event
            conn.execute(
                "INSERT INTO game_events(game_id,seq,command_id,payload_hash,event,response)"
                " VALUES(?,?,?,?,?,?)",
                (game_id, seq, command_id, payload_hash, encode(accepted_event),
                 encode(response)))
            conn.execute("UPDATE games SET seq=?,state_hash=?,terminated=? WHERE id=?",
                         (seq, ledger.state.fingerprint, int(ledger.state.terminated),
                          game_id))
            return response

    def events(self, game_id, after_seq=0, limit=500):
        if (type(after_seq) is not int or after_seq < 0 or type(limit) is not int
                or not 1 <= limit <= 500):
            raise PlatformError("invalid_cursor", "Invalid event cursor/limit", 422)
        with self.store.connection() as conn:
            row = self._row(conn, game_id)
            if after_seq > row["seq"]:
                raise PlatformError("invalid_cursor", "Cursor ahead of game", 422)
            events = conn.execute(
                "SELECT event FROM game_events WHERE game_id=? AND seq>? "
                "ORDER BY seq LIMIT ?", (game_id, after_seq, limit)).fetchall()
            return {"schema": "game-event-page-v1", "game_id": game_id,
                    "current_seq": row["seq"], "after_seq": after_seq,
                    "events": [json.loads(x["event"]) for x in events],
                    "has_more": (bool(events) and
                                 json.loads(events[-1]["event"])["seq"] < row["seq"])}

    def record(self, game_id):
        with self.store.connection() as conn:
            row = self._row(conn, game_id)
            record = self._rehydrate(conn, row).to_record()
            replay_and_verify(record)
            return record

    def sgf(self, game_id):
        with self.store.connection() as conn:
            row = self._row(conn, game_id)
            ledger = self._rehydrate(conn, row)
            return game_to_sgf(ledger.state._game)
