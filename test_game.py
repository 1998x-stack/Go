import unittest
from game import Game


class TestGame(unittest.TestCase):
    def test_turn_alternation(self):
        g = Game()
        g.play(3, 3)
        self.assertEqual(g.state['current'], 'O')

    def test_pass_then_continue(self):
        g = Game()
        g.play(3, 3)
        g.pass_move()
        self.assertEqual(g.state['current'], 'X')

    def test_two_passes_end_game(self):
        g = Game()
        g.pass_move()
        g.pass_move()
        self.assertTrue(g.state['game_over'])

    def test_undo_restores_turn_and_board(self):
        g = Game()
        g.play(3, 3)   # X -> current O
        g.play(4, 4)   # O -> current X
        g.undo()        # remove O's move
        self.assertEqual(g.state['current'], 'O')
        self.assertIsNone(g.board.get_stone(4, 4))

    def test_setup_handicap_sets_komi_zero(self):
        g = Game()
        g.setup(handicap=2)
        self.assertEqual(g.state['komi'], 0)
        self.assertEqual(g.state['current'], 'O')
        black = sum(1 for row in g.board.grid for c in row if c == 'X')
        self.assertEqual(black, 2)

    def test_finish_returns_score(self):
        g = Game()
        g.play(3, 3)
        g.pass_move()
        g.pass_move()
        res = g.finish()
        self.assertIn('winner', res)
        self.assertTrue(res['over'])

    def test_ko_forbids_immediate_recapture(self):
        # Genuine ko: X captures a lone O stone at (1,1) with a stone at (2,1)
        # that ends up with exactly one liberty (the now-empty point). O must
        # not be allowed to immediately recapture at (1,1).
        g = Game()
        seq = [(1, 0), (2, 0), (1, 2), (2, 2), (0, 1), (3, 1), (4, 0), (1, 1), (2, 1)]
        for i, (x, y) in enumerate(seq):
            ok, _ = g.play(x, y)
            self.assertTrue(ok, 'move #{} ({} {}) unexpectedly rejected'.format(i, x, y))
        # current is now O (white). White must NOT recapture at (1,1):
        self.assertFalse(g.can_play(1, 1))
        # but may play elsewhere:
        self.assertTrue(g.can_play(9, 9))


if __name__ == '__main__':
    unittest.main()