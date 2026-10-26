"""Single source of truth: adapter around legacy Game, with a stable RL ABI."""
import copy
import hashlib
import json
import uuid
from dataclasses import dataclass, field

from game import Game
from .specs import RuleSpec


@dataclass(frozen=True)
class ScoreReport:
    black: float
    white: float
    winner: str
    margin: float
    adjudication_status: str = "unresolved_dead_stones"
    scoring_method: str = "area_simple"


@dataclass(frozen=True)
class UndoToken:
    state_id: str
    sequence_after: int
    fingerprint_after: str
    generation_after: int


@dataclass(frozen=True)
class MoveResult:
    ok: bool
    reason: str
    token: object = None


@dataclass
class GoState:
    rules: RuleSpec
    _game: Game = field(repr=False)
    _actions: list = field(default_factory=list, repr=False)
    _id: str = field(default_factory=lambda: uuid.uuid4().hex, repr=False)
    _generation: int = field(default=0, repr=False)

    @property
    def board(self):
        """Canonical [row][col]; legacy GameBoard stores grid[x][y]."""
        size = self.rules.board_size
        return tuple(tuple(self._game.board.grid[col][row] for col in range(size))
                     for row in range(size))

    @property
    def current_player(self):
        return self._game.state["current"]

    @property
    def terminated(self):
        return bool(self._game.state["game_over"])

    @property
    def consecutive_passes(self):
        return self._game.state["passes"]

    @property
    def actions(self):
        return tuple(self._actions)

    @property
    def fingerprint(self):
        # Incorporates *full ordered history*, not just the current board.
        payload = {
            "rules": self.rules.to_dict(), "board": self.board,
            "to_play": self.current_player, "passes": self.consecutive_passes,
            "terminated": self.terminated, "actions": self._actions,
            "captured": [self._game.black.captured_stones,
                         self._game.white.captured_stones],
        }
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def clone(self):
        return GoState(self.rules, copy.deepcopy(self._game), list(self._actions))

    def history_boards(self, count):
        """Earlier board snapshots in chronological order, canonical [row][col]."""
        n = self.rules.board_size
        return tuple(
            tuple(tuple(grid[col][row] for col in range(n)) for row in range(n))
            for _, _, _, grid in self._game.history[-count:]
        )


class RulesEngine:
    """All move legality delegates to the repository's existing PSK Game."""

    def new_game(self, rules=None):
        rules = rules or RuleSpec()
        game = Game(size=rules.board_size)
        if rules.handicap:
            game.setup(handicap=rules.handicap)
        game.state["komi"] = rules.komi_half_points / 2
        return GoState(rules, game)

    @staticmethod
    def pass_action(state):
        return state.rules.board_size ** 2

    def legal_actions(self, state):
        n = state.rules.board_size
        if state.terminated:
            return tuple(False for _ in range(n * n + 1))
        # Translation is explicit: row,col -> existing Game.play(x=col,y=row).
        return tuple(state._game.can_play(col, row) for row in range(n)
                     for col in range(n)) + (True,)

    def try_apply(self, state, action):
        n = state.rules.board_size
        if type(action) is not int or not 0 <= action <= n * n:
            return MoveResult(False, "Action outside discrete action space")
        if state.terminated:
            return MoveResult(False, "Game over")
        if action == n * n:
            ok, reason = state._game.pass_move()
        else:
            row, col = divmod(action, n)
            ok, reason = state._game.play(col, row)
        if not ok:
            return MoveResult(False, reason)
        state._actions.append(action)
        state._generation += 1
        token = UndoToken(state._id, len(state._actions), state.fingerprint,
                          state._generation)
        return MoveResult(True, reason, token)

    def apply_in_place(self, state, action):
        result = self.try_apply(state, action)
        if not result.ok:
            raise ValueError(result.reason)
        return result.token

    def undo(self, state, token):
        if (not isinstance(token, UndoToken) or token.state_id != state._id
                or token.sequence_after != len(state._actions)
                or token.fingerprint_after != state.fingerprint
                or token.generation_after != state._generation):
            raise ValueError("Stale or foreign undo token")
        if not state._game.undo():
            raise RuntimeError("Legacy game history unexpectedly empty")
        state._actions.pop()
        state._generation += 1

    @staticmethod
    def clone(state):
        return state.clone()

    @staticmethod
    def score(state):
        b, w = state._game.board.score_areas()
        black, white = float(b), float(w) + state.rules.komi_half_points / 2
        winner = "X" if black > white else "O" if white > black else "draw"
        return ScoreReport(black, white, winner, abs(black - white))

    def replay(self, rules, actions):
        state = self.new_game(rules)
        for index, action in enumerate(actions):
            result = self.try_apply(state, action)
            if not result.ok:
                raise ValueError("Invalid action at ply {}: {}".format(index, result.reason))
        return state
