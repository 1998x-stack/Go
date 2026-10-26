"""Paired color-swap evaluation, independent of learners and model loss."""
import math
import random
from dataclasses import asdict, dataclass

from ai import GreedyAI
from go_game.core import RuleSpec
from go_game.rl import CoreGoEnv


@dataclass(frozen=True)
class GameResult:
    black_agent: str
    white_agent: str
    winner: object
    truncated: bool
    moves: int
    record_digest: str


def _choose(env, agent, rng):
    if agent == "greedy":
        legacy = GreedyAI().choose(env.state._game)
        if legacy is None:
            return env.rules.board_size ** 2
        x, y = legacy
        return y * env.rules.board_size + x
    if agent == "random":
        legal = env.observe().action_mask
        return rng.choice([i for i, ok in enumerate(legal) if ok])
    raise ValueError("Unsupported baseline agent")


def play_game(black_agent, white_agent, rules=None, seed=0, max_moves=None):
    """Returns an objectively replayable record; truncated != drawn."""
    env = CoreGoEnv(rules or RuleSpec(), max_moves=max_moves)
    env.reset(seed=seed)
    rngs = {"X": random.Random(seed), "O": random.Random(seed + 137)}
    while not env.done:
        current = env.state.current_player
        action = _choose(env, black_agent if current == "X" else white_agent,
                         rngs[current])
        outcome = env.step(action)
    return GameResult(black_agent, white_agent, outcome.info["winner"],
                      outcome.truncated, len(env.state.actions),
                      env.ledger.to_record()["digest"])


def run_paired_arena(agent_a, agent_b, rules=None, pairs=10, seed=0, max_moves=None):
    """Paired common-seed games with swapped colors and honest uncertainty.

    Draw earns 0.5. Truncated games are excluded, not mislabeled as draws.
    Hoeffding interval bounds any bounded per-game [0,1] score.
    """
    if type(pairs) is not int or pairs < 1:
        raise ValueError("pairs must be a positive integer")
    if agent_a not in ("random", "greedy") or agent_b not in ("random", "greedy"):
        raise ValueError("Only frozen baseline agents are supported")
    games = []
    scores = []
    for i in range(pairs):
        for a_is_black, (black, white) in (
                (True, (agent_a, agent_b)), (False, (agent_b, agent_a))):
            result = play_game(black, white, rules=rules, seed=seed + i,
                               max_moves=max_moves)
            games.append(asdict(result))
            if result.truncated:
                continue
            if result.winner == "draw":
                scores.append(0.5)
            elif ((result.winner == "X" and a_is_black)
                  or (result.winner == "O" and not a_is_black)):
                scores.append(1.0)
            else:
                scores.append(0.0)
    count = len(scores)
    mean = sum(scores) / count if count else None
    radius = math.sqrt(math.log(40.0) / (2 * count)) if count else None
    return {
        "schema": "arena-report-v1",
        "agent_a": agent_a, "agent_b": agent_b,
        "rule_id": (rules or RuleSpec()).rule_id,
        "rules": (rules or RuleSpec()).to_dict(),
        "pairs": pairs, "seed": seed,
        "completed": count, "truncated": len(games) - count,
        "agent_a_score": mean,
        "confidence_95_hoeffding": (
            [max(0.0, mean - radius), min(1.0, mean + radius)] if count else None),
        "games": games,
    }
