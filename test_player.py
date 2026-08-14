import unittest
from unittest import mock
from player import Player
from gameboard import GameBoard


class TestPlayer(unittest.TestCase):
    def test_initialization(self):
        p = Player('X')
        self.assertEqual(p.get_color(), 'X')
        self.assertEqual(p.get_captured_stones(), 0)
        self.assertTrue(p.is_human)

    def test_invalid_color_raises(self):
        with self.assertRaises(ValueError):
            Player('A')

    def test_increment_captured(self):
        p = Player('O')
        p.increment_captured_stones(3)
        p.increment_captured_stones(2)
        self.assertEqual(p.get_captured_stones(), 5)

    def test_increment_negative_raises(self):
        p = Player('X')
        with self.assertRaises(ValueError):
            p.increment_captured_stones(-1)

    def test_make_move_delegates_to_board(self):
        board = mock.Mock()
        board.place_stone.return_value = True
        p = Player('X')
        self.assertTrue(p.make_move(board, 5, 5))
        board.place_stone.assert_called_once_with(p, 5, 5)

    def test_make_move_real_board(self):
        board = GameBoard(5)
        p = Player('X')
        self.assertTrue(p.make_move(board, 2, 2))
        self.assertEqual(board.get_stone(2, 2), 'X')


if __name__ == '__main__':
    unittest.main()