"""Reproducible small-scale training CLI. Not a distributed/19x19 strength claim."""
import argparse
import copy
import json
import os
import random

from go_game.core import RuleSpec
from .arena import evaluate_candidate, promotion_decision
from .dataset import write_shard
from .learner import Learner
from .network import NetworkConfig, PolicyValueNet, TorchPredictor
from .search import SearchConfig
from .selfplay import IncompleteGame, selfplay_game


def run_smoke(args):
    import torch

    random.seed(args.seed)
    torch.manual_seed(args.seed)
    if args.size < 2 or args.size > 19:
        raise ValueError("Size must be 2..19 for this experimental CLI")
    spec = RuleSpec(board_size=args.size, komi_half_points=args.komi_half_points)
    config = SearchConfig(simulations=args.simulations, dirichlet_fraction=0.0)
    network_config = NetworkConfig(args.size, channels=args.channels, blocks=1)
    learner = Learner(PolicyValueNet(network_config), seed=args.seed)
    original = TorchPredictor(copy.deepcopy(learner.model))
    os.makedirs(args.output, exist_ok=True)
    shards = []
    for index in range(args.games):
        for attempt in range(args.retries):
            try:
                shard = selfplay_game(
                    original, rules=spec, config=config,
                    seed=args.seed + index * 100 + attempt,
                    max_moves=args.max_moves, explore=False, temperature=1.0,
                    revision="smoke-cli")
                break
            except IncompleteGame:
                if attempt + 1 == args.retries:
                    raise
        path = os.path.join(args.output, "game-{:03d}-{}.json".format(
            index, shard["digest"].split(":")[1][:16]))
        write_shard(path, shard)
        shards.append(shard)
    metrics = learner.train(shards, steps=args.steps, batch_size=args.batch_size)
    checkpoint_path = os.path.join(args.output, "candidate.pt")
    manifest = learner.save(checkpoint_path)
    candidate = TorchPredictor(learner.model)
    report = evaluate_candidate(candidate, original, rules=spec, config=config,
                                pairs=args.pairs, seed=args.seed + 10000,
                                max_moves=args.max_moves)
    result = {"schema": "smoke-run-v1", "seed": args.seed,
              "rules": spec.to_dict(), "search_config": vars(config),
              "input_shards": [s["digest"] for s in shards],
              "training": metrics, "model": manifest, "arena": report,
              "promotion_decision": promotion_decision(report)}
    with open(os.path.join(args.output, "run-report.json"), "w", encoding="utf-8") as fh:
        json.dump(result, fh, indent=2, sort_keys=True, allow_nan=False)
    print(json.dumps({
        "model_id": manifest["model_id"], "samples": sum(
            len(s["examples"]) for s in shards),
        "steps": learner.step_number,
        "arena_completed": report["completed"],
        "promotion_decision": result["promotion_decision"],
        "output": os.path.abspath(args.output),
    }, sort_keys=True))
    return result


def main():
    parser = argparse.ArgumentParser(description="Plan B verified small-board self-play")
    parser.add_argument("--output", default="runs/plan-b-smoke")
    parser.add_argument("--size", type=int, default=3)
    parser.add_argument("--komi-half-points", type=int, default=11)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--games", type=int, default=1)
    parser.add_argument("--simulations", type=int, default=4)
    parser.add_argument("--max-moves", type=int, default=120)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--steps", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=4)
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--pairs", type=int, default=1)
    args = parser.parse_args()
    if min(args.games, args.retries, args.steps, args.batch_size, args.pairs) < 1:
        parser.error("Counts must all be positive")
    run_smoke(args)


if __name__ == "__main__":
    main()
