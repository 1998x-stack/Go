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


class TestPruning(unittest.TestCase):
    def test_empty_board_falls_back_to_legal(self):
        g = Game()
        pts = GreedyAI()._candidates(g)
        self.assertTrue(pts)
        for (x, y) in pts[:5]:
            self.assertTrue(g.can_play(x, y))

    def test_after_stones_candidates_adjacent_and_legal(self):
        g = Game()
        g.play(3, 3)  # X
        g.play(16, 16)  # O
        ai = GreedyAI()
        pts = ai._candidates(g)  # current is X
        self.assertTrue(pts)
        for (x, y) in pts:
            self.assertTrue(g.can_play(x, y))
            adj = any(
                abs(nx - x) + abs(ny - y) == 1 and g.board.grid[nx][ny] is not None
                for nx, ny in [(x+1, y), (x-1, y), (x, y+1), (x, y-1)]
                if 0 <= nx < g.size and 0 <= ny < g.size
            )
            self.assertTrue(adj)

    def test_candidates_are_never_empty_when_legal_moves_exist(self):
        g = Game()
        g.play(3, 3)
        ai = GreedyAI()
        pts = ai._candidates(g)
        self.assertTrue(pts)
        self.assertTrue(all(g.can_play(x, y) for (x, y) in pts))


class TestSharedBase(unittest.TestCase):
    def test_score_move_matches_reference(self):
        from gameboard import GameBoard
        from player import Player
        g = Game()
        g.play(3, 3); g.play(16, 16); g.play(3, 15); g.play(15, 3)
        ai = GreedyAI()
        color = 'X'
        own = g.board.score_areas()[0]
        for (x, y) in ai._candidates(g)[:6]:
            v = ai._score_move(g, color, x, y, own)
            # reference: independent recompute
            sim = GameBoard(g.size)
            sim.grid = [row[:] for row in g.board.grid]
            tmp = Player(color)
            base = sim.score_areas()[0]
            if not sim.place_stone(tmp, x, y):
                self.assertEqual(v, float('-inf'))
                continue
            ref = (sim.score_areas()[0] - base) + tmp.captured_stones
            self.assertEqual(v, ref)

    def test_choose_returns_legal_move(self):
        g = Game()
        mv = GreedyAI().choose(g)
        self.assertIsNotNone(mv)
        ok, _ = g.play(mv[0], mv[1])
        self.assertTrue(ok)


if __name__ == '__main__':
    unittest.main()