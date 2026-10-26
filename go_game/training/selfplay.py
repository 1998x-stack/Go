"""Game-complete, model-pinned AlphaZero-style self-play trajectories."""
import random

from go_game.core import RuleSpec
from go_game.rl import CoreGoEnv
from .dataset import create_shard
from .search import SearchConfig, search


class IncompleteGame(RuntimeError):
    """A max-move truncated game has no valid final z target."""


def selfplay_game(predictor, rules=None, config=None, seed=0, max_moves=120,
                  temperature=1.0, explore=True, revision="uncommitted"):
    rules = rules or RuleSpec(board_size=5, komi_half_points=11)
    config = config or SearchConfig()
    if type(seed) is not int:
        raise ValueError("seed must be an integer")
    rng = random.Random(seed)
    env = CoreGoEnv(rules, max_moves=max_moves)
    env.reset(seed=seed)
    pinned_id = predictor.model_id
    examples = []
    while not env.done:
        if predictor.model_id != pinned_id:
            raise RuntimeError("Model changed during self-play game")
        obs = env.observe()
        result = search(env.state, predictor, config, temperature=temperature,
                        explore=explore, engine=env.ledger.engine, rng=rng)
        if result.model_id != pinned_id or not obs.action_mask[result.action]:
            raise RuntimeError("Search returned an illegal or unpinned move")
        examples.append({
            "ply": len(env.state.actions),
            "to_play": env.state.current_player,
            "state_fingerprint": env.state.fingerprint,
            "action": result.action,
            "planes": [[list(row) for row in plane] for plane in obs.planes],
            "mask": list(obs.action_mask),
            "visits": list(result.visits),
            "pi": list(result.policy),
            "root_value": result.root_value,
            "z": None,
        })
        env.step(result.action)
    if not env.state.terminated:
        raise IncompleteGame("Max move budget reached; refusing false winner/value labels")
    winner = env.ledger.engine.score(env.state).winner
    for sample in examples:
        sample["z"] = (0 if winner == "draw" else
                       1 if winner == sample["to_play"] else -1)
    return create_shard(env.ledger.to_record(), examples, pinned_id,
                        config, revision=revision)
