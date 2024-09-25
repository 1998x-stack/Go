import unittest
from gameboard import GameBoard
from player import Player

class TestGameBoard(unittest.TestCase):

    def setUp(self):
        """Set up a fresh game board and players for each test."""
        self.board = GameBoard()
        self.player_black = Player('X')
        self.player_white = Player('O')

    def test_initialization(self):
        """Test that the board is initialized with all positions set to None."""
        for row in self.board.grid:
            self.assertTrue(all(pos is None for pos in row))

    def test_place_stone_valid(self):
        """Test placing a stone on a valid empty spot."""
        result = self.board.place_stone(self.player_black, 3, 3)
        self.assertTrue(result)
        self.assertEqual(self.board.get_stone(3, 3), 'X')

    def test_place_stone_invalid_out_of_bounds(self):
        """Test placing a stone out of the board's bounds."""
        result = self.board.place_stone(self.player_black, -1, 3)
        self.assertFalse(result)
        self.assertIsNone(self.board.get_stone(-1, 3))

        result = self.board.place_stone(self.player_black, 19, 3)
        self.assertFalse(result)
        self.assertIsNone(self.board.get_stone(19, 3))

    def test_place_stone_invalid_occupied(self):
        """Test placing a stone on an already occupied spot."""
        self.board.place_stone(self.player_black, 3, 3)
        result = self.board.place_stone(self.player_white, 3, 3)
        self.assertFalse(result)
        self.assertEqual(self.board.get_stone(3, 3), 'X')

    def test_capture_stones(self):
        """Test capturing stones by surrounding them."""
        # Setup a scenario where a stone will be captured
        self.board.place_stone(self.player_black, 1, 0)
        self.board.place_stone(self.player_black, 0, 1)
        self.board.place_stone(self.player_black, 1, 2)
        self.board.place_stone(self.player_white, 1, 1)

        # Place stones to capture the white stone
        self.board.place_stone(self.player_black, 2, 1)
        captured_stones = self.board.capture_stones(2, 1)
        
        self.assertEqual(len(captured_stones), 1)
        self.assertEqual(captured_stones, [(1, 1)])
        self.assertIsNone(self.board.get_stone(1, 1))

    def test_get_groups(self):
        """Test getting a group of connected stones."""
        self.board.place_stone(self.player_black, 3, 3)
        self.board.place_stone(self.player_black, 3, 4)
        self.board.place_stone(self.player_black, 4, 3)
        
        group = self.board.get_groups(3, 3)
        self.assertEqual(len(group), 3)
        self.assertIn((3, 3), group)
        self.assertIn((3, 4), group)
        self.assertIn((4, 3), group)

    def test_get_liberties(self):
        """Test calculating the number of liberties for a group of stones."""
        self.board.place_stone(self.player_black, 3, 3)
        self.board.place_stone(self.player_black, 3, 4)
        self.board.place_stone(self.player_black, 4, 3)
        
        group = self.board.get_groups(3, 3)
        liberties = self.board.get_liberties(group)
        self.assertEqual(liberties, 7)  # The group has 7 liberties

    def test_is_valid_move(self):
        """Test that is_valid_move correctly identifies legal and illegal moves."""
        # Legal move
        self.assertTrue(self.board.is_valid_move(self.player_black, 3, 3))
        
        # Move out of bounds
        self.assertFalse(self.board.is_valid_move(self.player_black, -1, 3))
        
        # Move on occupied spot
        self.board.place_stone(self.player_black, 3, 3)
        self.assertFalse(self.board.is_valid_move(self.player_white, 3, 3))
        
        # Self-capture (illegal move)
        self.board.place_stone(self.player_white, 2, 3)
        self.board.place_stone(self.player_white, 3, 2)
        self.board.place_stone(self.player_white, 4, 3)
        self.board.place_stone(self.player_white, 3, 4)
        self.assertFalse(self.board.is_valid_move(self.player_black, 3, 3))

if __name__ == '__main__':
    unittest.main()
