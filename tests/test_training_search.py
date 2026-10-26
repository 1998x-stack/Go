"""Plan B stdlib tests: value sign, legality, replay and sampling contracts."""
import copy
import math
import random
import tempfile
import unittest
from pathlib import Path

from go_game.core import RuleSpec, RulesEngine
from go_game.training.dataset import (
    content_digest, create_shard, read_shard, validate_shard, write_shard,
)
from go_game.training.search import (
    Edge, Node, SearchConfig, UniformPredictor, _backup, search,
)
from go_game.training.selfplay import IncompleteGame, selfplay_game
from go_game.training.arena import promotion_decision


class PassPredictor:
    model_id = "deterministic-pass-v1"

    def predict(self, state):
        n = state.rules.board_size
        return [-12.0] * (n * n) + [12.0], 0.0


class TestSearch(unittest.TestCase):
    def test_value_backup_for_terminal_pass_without_player_flip(self):
        p = Node("X", "parent")
        e = Edge(1.0)
        _backup([(p, e)], 1.0, "X")
        self.assertEqual(e.q, 1.0)
        self.assertEqual(e.visits, 1)
        q = Node("X", "parent-2")
        edge = Edge(1.0)
        _backup([(q, edge)], 1.0, "O")
        self.assertEqual(edge.q, -1.0)

    def test_visit_distribution_and_illegal_mask(self):
        rules = RuleSpec(board_size=5)
        engine = RulesEngine()
        state = engine.new_game(rules)
        engine.apply_in_place(state, 4)
        before = state.fingerprint
        result = search(state, UniformPredictor(),
                        SearchConfig(simulations=12, dirichlet_fraction=0),
                        seed=44, temperature=0)
        self.assertEqual(state.fingerprint, before)
        self.assertEqual(sum(result.visits), 12)
        self.assertEqual(result.visits[4], 0)
        self.assertEqual(result.policy[4], 0.0)
        self.assertAlmostEqual(sum(result.policy), 1)
        self.assertTrue(engine.legal_actions(state)[result.action])
        self.assertTrue(-1 <= result.root_value <= 1)

    def test_deterministic_search_and_noise(self):
        state = RulesEngine().new_game(RuleSpec(board_size=3))
        config = SearchConfig(simulations=8)
        a = search(state, UniformPredictor(), config, seed=12, explore=True)
        b = search(state, UniformPredictor(), config, seed=12, explore=True)
        self.assertEqual(a, b)
        with self.assertRaises(ValueError):
            SearchConfig(simulations=0)
        with self.assertRaises(ValueError):
            search(state, UniformPredictor(), config, temperature=-1)


class TestSamples(unittest.TestCase):
    def make_shard(self, size=3, seed=6):
        return selfplay_game(
            PassPredictor(), rules=RuleSpec(board_size=size),
            config=SearchConfig(simulations=4, dirichlet_fraction=0),
            seed=seed, max_moves=10, explore=False, temperature=0)

    def test_terminal_two_passes_and_actor_z(self):
        shard = self.make_shard()
        self.assertEqual(shard["record"]["outcome"], "O")
        self.assertEqual([s["action"] for s in shard["examples"]], [9, 9])
        self.assertEqual([s["z"] for s in shard["examples"]], [-1, 1])
        self.assertEqual(shard["examples"][0]["to_play"], "X")
        self.assertEqual(shard["examples"][1]["to_play"], "O")
        self.assertTrue(validate_shard(shard))
        self.assertEqual(sum(shard["examples"][0]["visits"]), 4)

    def test_atomic_shard_persist_and_tamper(self):
        shard = self.make_shard()
        with tempfile.TemporaryDirectory() as d:
            name = Path(d) / "data" / "part.json"
            write_shard(name, shard)
            self.assertEqual(read_shard(name), shard)
            write_shard(name, shard)
            with self.assertRaises(FileExistsError):
                write_shard(name, self.make_shard(seed=99))
            modified = copy.deepcopy(shard)
            modified["examples"][0]["z"] = 1
            modified["digest"] = content_digest(
                {k: v for k, v in modified.items() if k != "digest"})
            with self.assertRaisesRegex(ValueError, "Target value"):
                validate_shard(modified)
            modified = copy.deepcopy(shard)
            modified["examples"][0]["visits"][0] = 2
            modified["digest"] = content_digest(
                {k: v for k, v in modified.items() if k != "digest"})
            with self.assertRaisesRegex(ValueError, "visit counts"):
                validate_shard(modified)

    def test_truncation_is_never_training_value(self):
        with self.assertRaises(IncompleteGame):
            selfplay_game(PassPredictor(), RuleSpec(board_size=3),
                          SearchConfig(simulations=1, dirichlet_fraction=0),
                          max_moves=1, explore=False)

    def test_scheme_works_for_large_boards(self):
        for size in (9, 13, 19):
            shard = self.make_shard(size=size, seed=3)
            self.assertEqual(len(shard["examples"][0]["visits"]), size * size + 1)
            self.assertEqual(shard["record"]["rules"]["board_size"], size)

    def test_arena_promotion_requires_independent_evidence(self):
        report = {
            "schema": "model-arena-v1", "completed": 1,
            "complete_pairs": 0, "scored_games": 0,
            "confidence_method": "hoeffding_complete_color_pairs",
            "confidence_95_hoeffding": [0.7, 1.0],
        }
        self.assertEqual(promotion_decision(report), "insufficient_evidence")
        report["completed"] = 100
        report["complete_pairs"] = 50
        report["scored_games"] = 100
        self.assertEqual(promotion_decision(report), "promote")
        report["confidence_95_hoeffding"] = [0.4, 0.8]
        self.assertEqual(promotion_decision(report), "retain_champion")


if __name__ == "__main__":
    unittest.main()
