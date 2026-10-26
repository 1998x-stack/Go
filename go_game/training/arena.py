"""Independent model-vs-model arena with color swaps and fixed search budget."""
import math
import random
from dataclasses import asdict

from go_game.core import RuleSpec
from go_game.rl import CoreGoEnv
from go_game.records import replay_and_verify
from .search import SearchConfig, search


def _play(black, white, rules, config, seed, max_moves):
    env = CoreGoEnv(rules, max_moves=max_moves)
    env.reset(seed=seed)
    rng = random.Random(seed)
    while not env.done:
        predictor = black if env.state.current_player == "X" else white
        result = search(env.state, predictor, config, temperature=0,
                        explore=False, rng=rng, engine=env.ledger.engine)
        env.step(result.action)
    record = env.export_record()
    replay_and_verify(record)
    return {
        "black": black.model_id, "white": white.model_id,
        "winner": record["outcome"],
        "truncated": not env.state.terminated,
        "record_digest": record["digest"], "moves": len(env.state.actions),
        "seed": seed,
    }


def evaluate_candidate(candidate, champion, rules=None, config=None, pairs=2,
                       seed=0, max_moves=120):
    if type(pairs) is not int or pairs < 1:
        raise ValueError("pairs must be positive")
    rules = rules or RuleSpec(board_size=5)
    config = config or SearchConfig()
    candidate_id, champion_id = candidate.model_id, champion.model_id
    results, scores = [], []
    for pair in range(pairs):
        for candidate_is_black, (black, white) in (
                (True, (candidate, champion)), (False, (champion, candidate))):
            item = _play(black, white, rules, config, seed + pair, max_moves)
            results.append(item)
            if item["truncated"]:
                continue
            if item["winner"] == "draw":
                scores.append(0.5)
            elif ((item["winner"] == "X" and candidate_is_black)
                  or (item["winner"] == "O" and not candidate_is_black)):
                scores.append(1.0)
            else:
                scores.append(0.0)
    if candidate.model_id != candidate_id or champion.model_id != champion_id:
        raise RuntimeError("Model changed during evaluation")
    n = len(scores)
    mean = sum(scores) / n if n else None
    radius = math.sqrt(math.log(40) / (2 * n)) if n else None
    return {
        "schema": "model-arena-v1", "candidate_id": candidate_id,
        "champion_id": champion_id, "rules": rules.to_dict(),
        "search_config": asdict(config), "pairs": pairs, "seed": seed,
        "max_moves": max_moves, "completed": n,
        "truncated": len(results) - n,
        "candidate_score": mean,
        "confidence_95_hoeffding": (
            [max(0.0, mean - radius), min(1.0, mean + radius)] if n else None),
        "games": results,
    }


def promotion_decision(report, min_completed=20, threshold=0.5):
    """Fail closed: never claim stronger play without prespecified evidence."""
    if report.get("schema") != "model-arena-v1":
        raise ValueError("Unsupported evaluation schema")
    if (type(min_completed) is not int or min_completed < 1
            or not 0 < threshold < 1):
        raise ValueError("Invalid predeclared gate")
    if report["completed"] < min_completed:
        return "insufficient_evidence"
    confidence = report["confidence_95_hoeffding"]
    if confidence is None:
        return "insufficient_evidence"
    return "promote" if confidence[0] > threshold else "retain_champion"
