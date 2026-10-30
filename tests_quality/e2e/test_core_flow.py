"""Headless E2E: environment -> ledger -> replay -> score, no browser claim."""
import random

from go_game.core import RuleSpec, RulesEngine
from go_game.rl import CoreGoEnv
from go_game.records import replay_and_verify
from go_game.eval.arena import run_paired_arena


def test_sequential_play_record_restore_and_reset():
    env = CoreGoEnv(RuleSpec(board_size=5, komi_half_points=11), max_moves=30)
    rng = random.Random(11)
    observation = env.reset(seed=11)
    while not env.done:
        actions = [i for i, ok in enumerate(observation.action_mask) if ok]
        # 15% passes; no invented episode winners if max_moves reached.
        action = rng.choice(actions) if rng.random() < 0.85 else 25
        transition = env.step(action)
        observation = transition.observation
    restored = replay_and_verify(env.export_record())
    assert restored.state.fingerprint == env.state.fingerprint
    if transition.truncated:
        assert transition.info["winner"] is None
        assert transition.rewards == {"black_0": 0.0, "white_0": 0.0}
    else:
        assert transition.rewards["black_0"] == -transition.rewards["white_0"]
    initial = env.reset(seed=11)
    assert sum(initial.action_mask) == 26


def test_branch_clone_undo_immutable_replay():
    engine = RulesEngine()
    state = engine.new_game(RuleSpec(board_size=5))
    base = state.fingerprint
    token = engine.apply_in_place(state, 7)
    branched = engine.clone(state)
    assert state.fingerprint == branched.fingerprint
    engine.undo(state, token)
    assert state.fingerprint == base
    assert branched.fingerprint != base


def test_paired_arena_consistent_schema():
    report = run_paired_arena("random", "random", rules=RuleSpec(board_size=5),
                              pairs=1, seed=17, max_moves=10)
    assert report["schema"] == "arena-report-v1"
    assert report["completed"] + report["truncated"] == 2
    assert len(report["games"]) == 2
