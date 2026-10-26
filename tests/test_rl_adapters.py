"""Optional dependency compatibility tests; separate CI job installs extras."""
import importlib.util
import unittest

from go_game.core import RuleSpec

HAS_GYM = importlib.util.find_spec("gymnasium") is not None
HAS_PZ = importlib.util.find_spec("pettingzoo") is not None
HAS_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAS_GYM and HAS_NUMPY, "optional gymnasium + numpy not installed")
class TestGymAdapter(unittest.TestCase):
    def test_checker_and_white_player_reset(self):
        from gymnasium.utils.env_checker import check_env
        from go_game.rl.gym_env import GoVsOpponentEnv

        black = GoVsOpponentEnv(RuleSpec(board_size=5), controlled_color="X",
                                max_moves=6)
        try:
            check_env(black, skip_render_check=True)
        finally:
            black.close()
        env = GoVsOpponentEnv(RuleSpec(board_size=5), controlled_color="O",
                              max_moves=6)
        try:
            a, info = env.reset(seed=100)
            b, _ = env.reset(seed=100)
            import numpy as np
            np.testing.assert_array_equal(a["observation"], b["observation"])
            self.assertIn("rule_id", info)
            self.assertTrue(env.observation_space.contains(a))
            legal = np.flatnonzero(a["action_mask"])
            _, reward, term, trunc, info = env.step(int(legal[0]))
            self.assertTrue(-1 <= reward <= 1)
            self.assertIsInstance(term, bool)
            self.assertIsInstance(trunc, bool)
            self.assertIn("opponent_moves", info)
        finally:
            env.close()


@unittest.skipUnless(HAS_GYM and HAS_PZ and HAS_NUMPY,
                     "optional gymnasium, pettingzoo and numpy not installed")
class TestPettingZooAdapter(unittest.TestCase):
    def test_api_and_terminal_dead_steps(self):
        from pettingzoo.test import api_test
        from go_game.rl.pettingzoo_env import GoAECEnv

        env = GoAECEnv(RuleSpec(board_size=5), max_moves=16)
        try:
            api_test(env, num_cycles=100, verbose_progress=False)
        finally:
            env.close()
        env = GoAECEnv(RuleSpec(board_size=5))
        try:
            env.reset(seed=3)
            self.assertEqual(env.agent_selection, "black_0")
            env.step(25)
            env.step(25)
            self.assertTrue(all(env.terminations.values()))
            self.assertEqual(env.rewards["black_0"], -1.0)
            self.assertEqual(env.rewards["white_0"], 1.0)
            while env.agents:
                env.step(None)
            self.assertFalse(env.agents)
        finally:
            env.close()


if __name__ == "__main__":
    unittest.main()
