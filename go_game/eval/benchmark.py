"""Manual, reproducible, non-asserting baseline microbenchmark CLI."""
import argparse
import json
import platform
import time

from go_game.core import RuleSpec, RulesEngine


def measure(board_size=9, repetitions=10):
    rules = RuleSpec(board_size=board_size, komi_half_points=11)
    engine = RulesEngine()
    state = engine.new_game(rules)
    start = time.perf_counter()
    for _ in range(repetitions):
        engine.legal_actions(state)
    masks_seconds = time.perf_counter() - start
    start = time.perf_counter()
    for _ in range(repetitions):
        clone = state.clone()
        action = next(i for i, valid in enumerate(engine.legal_actions(clone)) if valid)
        token = engine.apply_in_place(clone, action)
        engine.undo(clone, token)
    undo_seconds = time.perf_counter() - start
    return {
        "schema": "go-benchmark-v1",
        "board_size": board_size, "rules": rules.to_dict(),
        "repetitions": repetitions, "python": platform.python_version(),
        "machine": platform.machine(), "processor": platform.processor(),
        "legal_masks_per_second": repetitions / masks_seconds,
        "clone_apply_undo_per_second": repetitions / undo_seconds,
        "note": "Numbers are only comparable under matched hardware/configuration",
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--size", type=int, default=9)
    parser.add_argument("--repeat", type=int, default=10)
    args = parser.parse_args()
    if args.repeat < 1:
        parser.error("--repeat must be positive")
    print(json.dumps(measure(args.size, args.repeat), indent=2))


if __name__ == "__main__":
    main()
