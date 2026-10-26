"""Stdlib-only Plan A tests (must pass without pygame/gym/torch)."""
import copy
import unittest

from go_game.core import RuleSpec, RulesEngine
from go_game.rl import CoreGoEnv, encode_observation
from go_game.records import EventLedger, replay_and_verify
from go_game.eval import play_game, run_paired_arena
from sgf import game_to_sgf


class TestRulesContract(unittest.TestCase):
    def setUp(self):
        self.engine = RulesEngine()
        self.rules = RuleSpec(board_size=5, komi_half_points=11)

    def test_preserve_legacy_psk_and_rulespec(self):
        self.assertEqual(RuleSpec.from_dict(self.rules.to_dict()), self.rules)
        for values in ({"rule_id": "research-ssk-v1"},
                       {"board_size": 1}, {"komi_half_points": 2.5}):
            with self.assertRaises(ValueError):
                RuleSpec(**values)
        with self.assertRaises(ValueError):
            RuleSpec(board_size=9, handicap=2)

    def test_action_to_legacy_coordinate_not_transposed(self):
        state = self.engine.new_game(self.rules)
        action = 1 * 5 + 4
        self.assertTrue(self.engine.try_apply(state, action).ok)
        self.assertEqual(state.board[1][4], "X")
        self.assertIsNone(state.board[4][1])
        self.assertEqual(state._game.board.grid[4][1], "X")
        self.assertIn(";B[eb]", game_to_sgf(state._game))
        self.assertEqual(len(self.engine.legal_actions(state)), 26)

    def test_ko_and_rollback(self):
        state = self.engine.new_game(RuleSpec(board_size=19, komi_half_points=13))
        seq = [(1, 0), (2, 0), (1, 2), (2, 2), (0, 1),
               (3, 1), (4, 0), (1, 1), (2, 1)]
        for x, y in seq:
            self.assertTrue(self.engine.try_apply(state, y * 19 + x).ok)
        before = state.fingerprint
        result = self.engine.try_apply(state, 1 * 19 + 1)
        self.assertFalse(result.ok)
        self.assertEqual(state.fingerprint, before)
        self.assertFalse(self.engine.legal_actions(state)[1 * 19 + 1])

    def test_clone_undo_pass_and_token_isolation(self):
        state = self.engine.new_game(self.rules)
        original = state.fingerprint
        token = self.engine.apply_in_place(state, 7)
        clone = state.clone()
        with self.assertRaises(ValueError):
            self.engine.undo(clone, token)
        self.engine.undo(state, token)
        self.assertEqual(state.fingerprint, original)
        self.assertEqual(self.engine.legal_actions(state)[25], True)
        with self.assertRaises(ValueError):
            self.engine.undo(state, token)
        self.assertTrue(self.engine.try_apply(state, 25).ok)
        self.assertTrue(self.engine.try_apply(state, 25).ok)
        self.assertTrue(state.terminated)
        self.assertTrue(all(not v for v in self.engine.legal_actions(state)))
        self.assertEqual(self.engine.score(state).winner, "O")

    def test_history_planes_and_perspective(self):
        state = self.engine.new_game(self.rules)
        first = encode_observation(state, self.engine)
        self.assertEqual(len(first.planes), 13)
        self.assertEqual(len(first.planes[0]), 5)
        self.assertEqual(len(first.action_mask), 26)
        self.engine.apply_in_place(state, 7)
        obs = encode_observation(state, self.engine)
        self.assertEqual(obs.perspective, "O")
        self.assertEqual(obs.planes[1][1][2], 1.0)
        self.assertEqual(obs.planes[2][1][2], 1.0)
        self.assertEqual(sum(sum(row) for row in obs.planes[5]), 0.0)
        not_turn = encode_observation(state, self.engine, perspective="X")
        self.assertFalse(any(not_turn.action_mask))


class TestLedger(unittest.TestCase):
    def test_roundtrip_tamper_detection_and_seed(self):
        ledger = EventLedger(RuleSpec(board_size=5, komi_half_points=11), seed=42)
        for move in (1, 10, 25, 25):
            ledger.append(move)
        record = ledger.to_record()
        restored = replay_and_verify(copy.deepcopy(record))
        self.assertEqual(restored.state.fingerprint, ledger.state.fingerprint)
        self.assertEqual(restored.to_record(), record)
        tampered = copy.deepcopy(record)
        tampered["events"][1]["action"] = 11
        with self.assertRaisesRegex(ValueError, "digest"):
            replay_and_verify(tampered)
        tampered = copy.deepcopy(record)
        tampered["events"][1]["actor"] = "X"
        from go_game.records.ledger import _digest
        tampered["digest"] = _digest({k: v for k, v in tampered.items() if k != "digest"})
        with self.assertRaisesRegex(ValueError, "precondition"):
            replay_and_verify(tampered)

    def test_illegal_and_truncate_are_not_wins(self):
        env = CoreGoEnv(RuleSpec(board_size=5, komi_half_points=11), max_moves=1)
        env.reset(seed=7)
        env.step(0)
        self.assertTrue(env.done)
        self.assertTrue(env._truncated)
        self.assertFalse(env.state.terminated)
        self.assertIsNone(env.ledger.to_record()["outcome"])
        self.assertEqual(replay_and_verify(env.export_record()).to_record(),
                         env.export_record())
        with self.assertRaises(ValueError):
            env.step(1)
        env.reset(seed=7)
        env.step(0)
        with self.assertRaises(ValueError):
            env.ledger.append(0)


class TestArena(unittest.TestCase):
    def test_replayable_small_baseline_and_pair_report(self):
        result = play_game("random", "random", RuleSpec(board_size=5),
                           seed=8, max_moves=6)
        self.assertTrue(result.truncated or result.winner is not None)
        report = run_paired_arena("random", "greedy",
                                  RuleSpec(board_size=5), pairs=1,
                                  seed=5, max_moves=4)
        self.assertEqual(report["pairs"], 1)
        self.assertEqual(len(report["games"]), 2)
        self.assertEqual(report["completed"] + report["truncated"], 2)


if __name__ == "__main__":
    unittest.main()
