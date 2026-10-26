"""D4 transforms must preserve action/policy/mask alignment and pass action."""
import unittest
from go_game.training.augmentation import point, transform_sample


class TestD4(unittest.TestCase):
    def test_all_eight_transformations(self):
        n = 5
        sample = {
            "action": 1 * n + 3,
            "planes": [[[r * n + c for c in range(n)] for r in range(n)]
                       for _ in range(13)],
            "mask": [True] * (n * n) + [True],
            "visits": list(range(n * n)) + [99],
            "pi": [float(i) for i in range(n * n)] + [1.5],
            "z": 1, "ply": 10, "state_fingerprint": "unchanged",
        }
        for rotation in range(4):
            for reflect in (False, True):
                transformed = transform_sample(sample, n, rotation, reflect)
                rr, cc = point(1, 3, n, rotation, reflect)
                self.assertEqual(transformed["action"], rr * n + cc)
                self.assertEqual(transformed["visits"][rr * n + cc],
                                 sample["visits"][1 * n + 3])
                self.assertEqual(transformed["planes"][0][rr][cc], 8)
                self.assertEqual(transformed["visits"][-1], 99)
                self.assertEqual(transformed["pi"][-1], 1.5)
                self.assertEqual(transformed["state_fingerprint"], "unchanged")
                self.assertEqual(sample["action"], 8)
        passed = dict(sample, action=n * n)
        self.assertEqual(transform_sample(passed, n, 3, True)["action"], n * n)


if __name__ == "__main__":
    unittest.main()
