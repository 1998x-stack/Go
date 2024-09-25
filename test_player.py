import unittest
from player import Player

class TestPlayer(unittest.TestCase):
    
    def test_initialization(self):
        """Test that a player is initialized with the correct color and 0 captured stones."""
        player_black = Player('X')
        player_white = Player('O')
        
        self.assertEqual(player_black.get_color(), 'X')
        self.assertEqual(player_black.get_captured_stones(), 0)
        
        self.assertEqual(player_white.get_color(), 'O')
        self.assertEqual(player_white.get_captured_stones(), 0)

    def test_invalid_color_initialization(self):
        """Test that initializing a player with an invalid color raises a ValueError."""
        with self.assertRaises(ValueError):
            Player('A')  # Invalid color

    def test_make_move_success(self):
        """Test that make_move returns True when a valid move is made."""
        player = Player('X')
        
        # Mocking a GameBoard object and place_stone method
        game_board_mock = unittest.mock.Mock()
        game_board_mock.place_stone.return_value = True
        
        result = player.make_move(game_board_mock, 5, 5)
        
        self.assertTrue(result)
        game_board_mock.place_stone.assert_called_with(player, 5, 5)

    def test_make_move_failure(self):
        """Test that make_move returns False when the move fails."""
        player = Player('X')
        
        # Mocking a GameBoard object and place_stone method
        game_board_mock = unittest.mock.Mock()
        game_board_mock.place_stone.return_value = False
        
        result = player.make_move(game_board_mock, 5, 5)
        
        self.assertFalse(result)
        game_board_mock.place_stone.assert_called_with(player, 5, 5)

    def test_increment_captured_stones(self):
        """Test that captured stones are incremented correctly."""
        player = Player('X')
        player.increment_captured_stones(3)
        
        self.assertEqual(player.get_captured_stones(), 3)
        
        player.increment_captured_stones(2)
        self.assertEqual(player.get_captured_stones(), 5)

    def test_increment_captured_stones_negative(self):
        """Test that incrementing captured stones with a negative number raises a ValueError."""
        player = Player('X')
        
        with self.assertRaises(ValueError):
            player.increment_captured_stones(-1)

if __name__ == '__main__':
    unittest.main()
