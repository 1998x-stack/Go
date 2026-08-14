import unittest
from unittest import mock
from gameboard import GameBoard


def make_player(color):
    p = mock.MagicMock()
    p.get_color.return_value = color
    p.captured = 0
    p.increment_captured_stones.side_effect = lambda n, p=p: setattr(p, 'captured', p.captured + n)
    return p


class TestGameBoard(unittest.TestCase):
    def setUp(self):
        self.board = GameBoard(size=5)
        self.pb = make_player('X')
        self.pw = make_player('O')

    def place(self, color, coords):
        p = self.pb if color == 'X' else self.pw
        for (x, y) in coords:
            self.board.make_place(p, x, y)

    def test_place_and_get(self):
        self.assertTrue(self.board.place_stone(self.pb, 2, 2))
        self.assertEqual(self.board.get_stone(2, 2), 'X')

    def test_group_extension_into_surrounded_slot_is_legal(self):
        self.place('X', [(2, 0), (2, 1)])
        self.place('O', [(0, 1), (1, 0), (1, 2)])
        self.assertTrue(self.board.is_legal(self.pb, 1, 1))

    def test_genuine_suicide_is_illegal(self):
        self.place('X', [(0, 1), (1, 0), (1, 2), (2, 1)])
        self.assertFalse(self.board.is_legal(self.pw, 1, 1))

    def test_capture_credits_the_mover(self):
        self.place('O', [(1, 1)])
        self.place('X', [(0, 1), (1, 0), (1, 2)])
        self.assertTrue(self.board.place_stone(self.pb, 2, 1))
        self.assertEqual(self.pb.captured, 1)
        self.assertIsNone(self.board.get_stone(1, 1))

    def test_find_groups(self):
        self.place('X', [(0, 0), (0, 1)])
        self.place('O', [(2, 2)])
        self.assertEqual(sum(len(g) for g in self.board.find_groups('X')), 2)

    def test_score_areas_no_territory(self):
        self.place('X', [(0, 0)])
        self.place('O', [(4, 4)])
        black, white = self.board.score_areas()
        self.assertEqual(black, 1)
        self.assertEqual(white, 1)

    def test_score_areas_enclosed_territory(self):
        # black ring around empty (2,2); a lone white stone at a far corner makes
        # the outside region border BOTH colors (neutral), so only the interior
        # pocket (2,2) counts as black territory.
        self.place('X', [(1, 2), (2, 1), (3, 2), (2, 3)])
        self.place('O', [(0, 0)])
        black, white = self.board.score_areas()
        self.assertEqual(black, 5)   # 4 stones + 1 enclosed empty
        self.assertEqual(white, 1)

    def test_resulting_key_none_for_illegal(self):
        self.assertIsNone(self.board.resulting_key(self.pb, 99, 99))
        self.assertIsNotNone(self.board.resulting_key(self.pb, 0, 0))


if __name__ == '__main__':
    unittest.main()