"""Optional Gymnasium fixed-opponent adapter for a single learning agent."""
import random

try:
    import gymnasium as gym
    from gymnasium import spaces
    import numpy as np
except ImportError:
    gym = None
    spaces = None
    np = None

from ai import GreedyAI
from go_game.core import RuleSpec
from .environment import CoreGoEnv
from .features import CHANNELS, numpy_observation


class GoVsOpponentEnv(gym.Env if gym is not None else object):
    metadata = {"render_modes": ["ansi"]}

    def __init__(self, rules=None, controlled_color="X", opponent="random",
                 max_moves=None, render_mode=None):
        if gym is None:
            raise ImportError("Install optional dependencies: gymnasium numpy")
        if controlled_color not in ("X", "O"):
            raise ValueError("controlled_color must be X or O")
        if opponent not in ("random", "greedy"):
            raise ValueError("opponent must be random or greedy")
        if render_mode not in (None, "ansi"):
            raise ValueError("Unsupported render mode")
        self.rules = rules or RuleSpec()
        self.controlled_color = controlled_color
        self.controlled_agent = "black_0" if controlled_color == "X" else "white_0"
        self.opponent = opponent
        self.render_mode = render_mode
        self.core = CoreGoEnv(self.rules, max_moves=max_moves)
        self._rng = random.Random()
        n = self.rules.board_size
        self.action_space = spaces.Discrete(n * n + 1)
        self.observation_space = spaces.Dict({
            "observation": spaces.Box(
                low=-np.inf, high=np.inf, shape=(CHANNELS, n, n), dtype=np.float32),
            "action_mask": spaces.MultiBinary(n * n + 1),
        })

    def _observe(self):
        return numpy_observation(self.core.observe(self.controlled_color))

    def _opponent_action(self):
        if self.opponent == "greedy":
            move = GreedyAI().choose(self.core.state._game)
            if move is None:
                return self.rules.board_size ** 2
            x, y = move
            return y * self.rules.board_size + x
        mask = self.core.observe().action_mask
        return self._rng.choice([i for i, legal in enumerate(mask) if legal])

    def _opponent_step(self):
        if self.core.done:
            return None
        return self.core.step(self._opponent_action())

    def reset(self, *, seed=None, options=None):
        if options:
            raise ValueError("Rule configuration cannot be changed by reset options")
        super().reset(seed=seed)
        self._rng = random.Random(seed)
        self.core.reset(seed=seed)
        result = None
        if self.core.state.current_player != self.controlled_color:
            result = self._opponent_step()
        info = dict(result.info) if result is not None else {
            "rule_id": self.rules.rule_id,
            "state_fingerprint": self.core.state.fingerprint,
        }
        return self._observe(), info

    def step(self, action):
        if self.core.done:
            raise ValueError("Episode finished; reset before stepping")
        if self.core.state.current_player != self.controlled_color:
            raise RuntimeError("Not the controlled player's turn")
        result = self.core.step(int(action) if isinstance(action, (int, np.integer)) else action)
        opponent_moves = 0
        if not self.core.done:
            result = self._opponent_step()
            opponent_moves = 1
        info = dict(result.info)
        info["opponent_moves"] = opponent_moves
        return (self._observe(), float(result.rewards[self.controlled_agent]),
                bool(result.terminated), bool(result.truncated), info)

    def render(self):
        return "\n".join("".join("." if p is None else p for p in row)
                         for row in self.core.state.board)

    def close(self):
        pass
