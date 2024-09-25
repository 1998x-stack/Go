

class Player:
    """Represents a player in the Go game, managing their color and captured stones."""

    def __init__(self, color: str):
        """Initialize the player with a color and a captured stones counter.
        
        Args:
            color (str): The color of the player ('X' for black, 'O' for white).

        Raises:
            ValueError: If the color is not 'X' or 'O'.
        """
        if color not in ['X', 'O']:
            raise ValueError("Invalid color: must be 'X' (black) or 'O' (white)")
        
        self.color = color
        self.captured_stones = 0
        print(f"Player {self.color} created with captured stones set to 0.")

    def make_move(self, game_board: 'GameBoard', x: int, y: int) -> bool:
        """Attempt to place a stone on the board.
        
        Args:
            game_board (GameBoard): The current game board.
            x (int): The x-coordinate on the board.
            y (int): The y-coordinate on the board.

        Returns:
            bool: True if the move was successful, False otherwise.
        """
        try:
            successful_move = game_board.place_stone(self, x, y)
            if successful_move:
                print(f"Player {self.color} placed a stone at ({x}, {y}).")
            else:
                print(f"Player {self.color} failed to place a stone at ({x}, {y}).")
            return successful_move
        except Exception as e:
            print(f"An error occurred while placing a stone: {e}")
            return False

    def get_color(self) -> str:
        """Return the player's color.
        
        Returns:
            str: The color of the player ('X' or 'O').
        """
        return self.color

    def increment_captured_stones(self, count: int) -> None:
        """Increase the number of captured stones by the given count.
        
        Args:
            count (int): The number of stones to add to the captured count.
        
        Raises:
            ValueError: If the count is negative.
        """
        if count < 0:
            raise ValueError("Captured stones count cannot be negative.")
        
        self.captured_stones += count
        print(f"Player {self.color} captured {count} stones. Total captured: {self.captured_stones}.")

    def get_captured_stones(self) -> int:
        """Return the number of stones captured by the player.
        
        Returns:
            int: The number of captured stones.
        """
        return self.captured_stones
