"""Optional PyTorch tests: tensor ABI, gradients, replay lineage, restore, arena."""
import copy
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

TORCH = importlib.util.find_spec("torch") is not None


@unittest.skipUnless(TORCH, "CPU PyTorch not installed")
class TestTorchTraining(unittest.TestCase):
    def setUp(self):
        import torch
        torch.manual_seed(7)
        from go_game.training.network import NetworkConfig, PolicyValueNet, TorchPredictor
        from go_game.training.search import SearchConfig
        from go_game.training.selfplay import selfplay_game
        from go_game.core import RuleSpec

        self.model = PolicyValueNet(NetworkConfig(3, channels=8, blocks=1))
        self.shard = selfplay_game(
            PassPredictor(), RuleSpec(board_size=3),
            SearchConfig(simulations=3, dirichlet_fraction=0),
            seed=9, max_moves=10, explore=False, temperature=0)

    def test_network_shapes_and_masking(self):
        import torch
        from go_game.training.network import TorchPredictor
        from go_game.core import RuleSpec, RulesEngine
        from go_game.training.search import SearchConfig, search

        predictor = TorchPredictor(self.model)
        state = RulesEngine().new_game(RuleSpec(board_size=3))
        result = predictor.predict_batch([state, state.clone()])
        self.assertEqual(len(result), 2)
        for logits, value in result:
            self.assertEqual(len(logits), 10)
            self.assertTrue(-1 <= value <= 1)
        RulesEngine().try_apply(state, 0)
        searched = search(state, predictor, SearchConfig(
            simulations=2, dirichlet_fraction=0))
        self.assertEqual(searched.visits[0], 0)
        self.assertTrue(math.isfinite(searched.root_value))

    def test_checkpoint_exact_restart_and_registry(self):
        from go_game.training.learner import Learner
        from go_game.training.network import PolicyValueNet, model_digest
        from go_game.training.registry import LocalRegistry
        from go_game.training.arena import evaluate_candidate
        from go_game.training.network import TorchPredictor
        from go_game.training.search import SearchConfig
        from go_game.core import RuleSpec

        learner = Learner(self.model, seed=17)
        first = learner.train([self.shard], steps=2, batch_size=2)
        self.assertTrue(all(math.isfinite(row["loss"]) for row in first))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "candidate.pt"
            manifest = learner.save(path)
            initial_digest = model_digest(learner.model)
            restored = Learner.load(path)
            self.assertEqual(restored.step_number, learner.step_number)
            self.assertEqual(restored.training_rules, self.shard["record"]["rules"])
            self.assertEqual(manifest["action_spec_id"], "row-major-pass-last-v1")
            self.assertEqual(manifest["supported_rulesets"], ["research-psk-v1"])
            self.assertEqual(model_digest(restored.model), initial_digest)
            learner.train([self.shard], steps=1, batch_size=2)
            restored.train([self.shard], steps=1, batch_size=2)
            self.assertEqual(model_digest(restored.model), model_digest(learner.model))
            registry = LocalRegistry(Path(folder) / "champion.json")
            registry.bootstrap(manifest, path)
            self.assertEqual(registry.current()["model_id"], manifest["model_id"])
            with self.assertRaises(ValueError):
                registry.bootstrap(manifest, path)
            gate = {"schema": "model-arena-v1", "candidate_id": "different",
                    "champion_id": manifest["model_id"], "completed": 100,
                    "confidence_95_hoeffding": [0.9, 1.0]}
            with self.assertRaises(ValueError):
                registry.promote(manifest, path, gate)

    def test_cpu_actor_process_pins_checkpoint_and_commits_only_valid_shards(self):
        import torch
        from go_game.training.actors import collect_selfplay
        from go_game.training.learner import Learner
        from go_game.training.network import NetworkConfig, PolicyValueNet
        from go_game.training.search import SearchConfig
        from go_game.training.dataset import read_shard
        from go_game.core import RuleSpec

        # Force a deterministic pass-biased model to get complete 2-pass games.
        model = PolicyValueNet(NetworkConfig(2, channels=8, blocks=0))
        with torch.no_grad():
            for param in model.parameters():
                param.zero_()
            model.pass_head.bias.fill_(12.0)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pass-model.pt"
            manifest = Learner(model, seed=99).save(path)
            results = collect_selfplay(
                path, manifest["model_id"], RuleSpec(board_size=2),
                SearchConfig(simulations=2, dirichlet_fraction=0),
                seeds=[11, 12], workers=1, max_moves=10,
                output=Path(folder) / "shards")
            self.assertEqual(len(results), 2)
            self.assertNotEqual(results[0]["digest"], results[1]["digest"])
            for result in results:
                shard = read_shard(result["path"])
                self.assertTrue(shard["record"]["terminated"])
                self.assertEqual(len(shard["examples"]), 2)
                self.assertEqual(result["model_id"], manifest["model_id"])
            with self.assertRaises(ValueError):
                collect_selfplay(path, "wrong-model-id",
                                 RuleSpec(board_size=2),
                                 SearchConfig(simulations=2), seeds=[13],
                                 workers=1, max_moves=10,
                                 output=Path(folder) / "bad")

    def test_independent_color_swapped_arena(self):
        from go_game.training.arena import evaluate_candidate
        from go_game.training.network import TorchPredictor
        from go_game.training.search import SearchConfig
        from go_game.core import RuleSpec

        candidate = TorchPredictor(self.model)
        champion = TorchPredictor(copy.deepcopy(self.model))
        report = evaluate_candidate(
            candidate, champion, RuleSpec(board_size=3),
            SearchConfig(simulations=1, dirichlet_fraction=0),
            pairs=1, seed=5, max_moves=100)
        self.assertEqual(len(report["games"]), 2)
        self.assertEqual(report["completed"] + report["truncated"], 2)
        self.assertEqual(report["confidence_method"],
                         "hoeffding_complete_color_pairs")
        self.assertEqual(report["complete_pairs"] * 2, report["scored_games"])


# Keep Torch imports entirely out of standard-library CI discovery.
class PassPredictor:
    model_id = "torch-test-pass-baseline-v1"

    def predict(self, state):
        n = state.rules.board_size
        return [-12.] * (n * n) + [12.], 0.


if __name__ == "__main__":
    unittest.main()
