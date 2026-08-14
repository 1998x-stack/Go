import unittest
from ai import RandomAI, GreedyAI
from game import Game


class TestAI(unittest.TestCase):
    def test_random_returns_legal(self):
        g = Game()
        mv = RandomAI().choose(g)
        self.assertIsNotNone(mv)
        ok, _ = g.play(mv[0], mv[1])
        self.assertTrue(ok)

    def test_greedy_returns_legal(self):
        g = Game()
        mv = GreedyAI().choose(g)
        self.assertIsNotNone(mv)
        ok, _ = g.play(mv[0], mv[1])
        self.assertTrue(ok)

    def test_passes_when_game_over(self):
        g = Game()
        g.pass_move()
        g.pass_move()
        self.assertIsNone(GreedyAI().choose(g))
        self.assertIsNone(RandomAI().choose(g))


if __name__ == '__main__':
    unittest.main()