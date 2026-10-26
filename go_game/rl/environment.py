"""Framework-independent episodic Go environment."""
from dataclasses import dataclass

from go_game.core import RuleSpec
from go_game.records import EventLedger
from .features import encode_observation


@dataclass(frozen=True)
class Transition:
    observation: object
    rewards: dict
    terminated: bool
    truncated: bool
    info: dict


class CoreGoEnv:
    """Both agents act in turn; runtime truncation never invents a winner."""

    def __init__(self, rules=None, max_moves=None):
        self.rules = rules or RuleSpec()
        if max_moves is not None and (type(max_moves) is not int or max_moves < 1):
            raise ValueError("max_moves must be a positive integer or None")
        self.max_moves = max_moves
        self.ledger = None
        self._truncated = False
        self.reset()

    @property
    def state(self):
        return self.ledger.state

    @property
    def done(self):
        return self.state.terminated or self._truncated

    def reset(self, seed=None):
        self.ledger = EventLedger(self.rules, seed)
        self._truncated = False
        return self.observe()

    def observe(self, perspective=None):
        return encode_observation(self.state, self.ledger.engine, perspective)

    def step(self, action):
        if self.done:
            raise ValueError("Episode finished; call reset()")
        self.ledger.append(action)
        terminated = self.state.terminated
        self._truncated = not terminated and (
            self.max_moves is not None and len(self.state.actions) >= self.max_moves)
        winner = self.ledger.engine.score(self.state).winner if terminated else None
        rewards = {"black_0": 0.0, "white_0": 0.0}
        if winner in ("X", "O"):
            rewards = {"black_0": 1.0 if winner == "X" else -1.0,
                       "white_0": 1.0 if winner == "O" else -1.0}
        return Transition(
            self.observe(), rewards, terminated, self._truncated,
            {"winner": winner, "terminal_reason": ("two_pass" if terminated else
             "move_limit" if self._truncated else None),
             "rule_id": self.rules.rule_id,
             "state_fingerprint": self.state.fingerprint,
             "ply": len(self.state.actions)},
        )

    def export_record(self):
        # A move-limit truncation is an episode property, not a rule winner.
        # Keep the canonical game record digest intact.
        return self.ledger.to_record()
