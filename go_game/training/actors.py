"""Bounded local process self-play actors with immutable model and shard provenance.

This is not a cross-machine job queue. Remote leases/fencing are Plan C.
"""
import os
import multiprocessing
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict

from go_game.core import RuleSpec
from .dataset import read_shard, write_shard
from .search import SearchConfig


def _actor_job(args):
    # Import Torch only in actor subprocess, not in the headless rules layer.
    from .learner import Learner
    from .network import TorchPredictor
    from .selfplay import selfplay_game

    checkpoint, expected_id, rule_spec, config_spec, seed, max_moves, folder = args
    learner = Learner.load(checkpoint, device="cpu")
    predictor = TorchPredictor(learner.model)
    if learner.training_rules is not None and learner.training_rules != rule_spec:
        raise ValueError("Actor requested a different training rule configuration")
    if predictor.model_id != expected_id:
        raise ValueError("Actor checkpoint does not match pinned model ID")
    shard = selfplay_game(predictor, RuleSpec.from_dict(rule_spec),
                          SearchConfig(**config_spec), seed=seed,
                          max_moves=max_moves, explore=True)
    path = os.path.join(folder, shard["digest"].split(":")[1] + ".json")
    write_shard(path, shard)
    return {"path": path, "digest": shard["digest"], "seed": seed,
            "model_id": expected_id, "samples": len(shard["examples"])}


def collect_selfplay(checkpoint, model_id, rules=None, config=None, seeds=None,
                     workers=1, max_moves=120, output="runs/shards"):
    """Spawn isolated actors; only return fully validated, immutable shards.

    Failed/aborted workers propagate errors and do not produce training targets.
    """
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("workers must be 1..8")
    seeds = list(seeds if seeds is not None else [1])
    if not seeds or len(seeds) > 100 or any(type(s) is not int for s in seeds):
        raise ValueError("Provide 1..100 integral game seeds")
    if len(set(seeds)) != len(seeds):
        raise ValueError("Duplicate seeds would make duplicate training games")
    rules = rules or RuleSpec(board_size=5)
    config = config or SearchConfig()
    os.makedirs(output, exist_ok=True)
    job_args = [(os.fspath(checkpoint), model_id, rules.to_dict(),
                 asdict(config), seed, max_moves, os.fspath(output)) for seed in seeds]
    # Spawn avoids forking an already-initialized PyTorch/OpenMP thread pool.
    with ProcessPoolExecutor(
            max_workers=workers, mp_context=multiprocessing.get_context("spawn")) as pool:
        results = list(pool.map(_actor_job, job_args))
    for result in results:
        item = read_shard(result["path"])
        if item["digest"] != result["digest"] or item["model_id"] != model_id:
            raise ValueError("Actor output failed final manifest validation")
    return results
