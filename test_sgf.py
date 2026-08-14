import unittest
from game import Game
from sgf import game_to_sgf, sgf_to_game


class TestSGF(unittest.TestCase):
    def test_roundtrip_moves(self):
        g = Game()
        g.play(3, 3)    # X
        g.play(16, 16)  # O
        sgf = game_to_sgf(g)
        g2 = sgf_to_game(sgf)
        self.assertEqual(g2.board.get_stone(3, 3), 'X')
        self.assertEqual(g2.board.get_stone(16, 16), 'O')

    def test_contains_header(self):
        g = Game()
        sgf = game_to_sgf(g)
        self.assertIn('SZ[19]', sgf)
        self.assertIn('KM[6.5]', sgf)


if __name__ == '__main__':
    unittest.main()