from typing import Optional, List, Tuple

class GameBoard:
    """Represents the 19x19 Go board, managing stone placement and group capture."""

    def __init__(self):
        """Initialize the board with a 19x19 grid, each point set to None (empty)."""
        self.size = 19
        self.grid = [[None for _ in range(self.size)] for _ in range(self.size)]
        print("GameBoard initialized with an empty 19x19 grid.")

    def place_stone(self, player: 'Player', x: int, y: int) -> bool:
        """Place a stone on the board for the given player, and capture opponent stones if necessary.
        
        Args:
            player (Player): The player placing the stone.
            x (int): The x-coordinate on the board.
            y (int): The y-coordinate on the board.

        Returns:
            bool: True if the move is valid and the stone was placed, False otherwise.
        """
        if not self.is_valid_move(player, x, y):
            print(f"Move at ({x}, {y}) is invalid.")
            return False

        # Place the stone
        self.grid[x][y] = player.get_color()
        print(f"Placed {player.get_color()} stone at ({x}, {y}).")

        # Check for captures
        captured_stones = self.capture_stones(x, y)
        if captured_stones:
            print(f"Captured stones: {captured_stones}")
        return True

    def remove_stone(self, x: int, y: int) -> None:
        """Remove a stone from the board."""
        print(f"Removing stone at ({x}, {y}).")
        self.grid[x][y] = None

    def get_stone(self, x: int, y: int) -> Optional[str]:
        """Return the stone at a specific coordinate.
        
        Args:
            x (int): The x-coordinate.
            y (int): The y-coordinate.

        Returns:
            Optional[str]: 'X' if a black stone is present, 'O' if a white stone, or None if empty.
        """
        if 0 <= x < self.size and 0 <= y < self.size:
            return self.grid[x][y]
        return None

    def is_valid_move(self, player: 'Player', x: int, y: int) -> bool:
        """Check if a move is valid (i.e., the space is empty and the move is legal).
        
        Args:
            player (Player): The player making the move.
            x (int): The x-coordinate on the board.
            y (int): The y-coordinate on the board.

        Returns:
            bool: True if the move is valid, False otherwise.
        """
        # Ensure the position is empty and on the board
        if not (0 <= x < self.size and 0 <= y < self.size):
            return False
        if self.grid[x][y] is not None:
            return False

        # Simulate the move to check for suicide (no liberties after placement)
        self.grid[x][y] = player.get_color()
        if self.get_liberties([(x, y)]) == 0:
            # Revert the move if it results in no liberties
            self.grid[x][y] = None
            return False
        # Revert the move for now (it will be placed in place_stone)
        self.grid[x][y] = None
        return True

    def capture_stones(self, x: int, y: int) -> List[Tuple[int, int]]:
        """Check and capture any opponent stones that are fully surrounded.
        
        Args:
            x (int): The x-coordinate of the most recent move.
            y (int): The y-coordinate of the most recent move.

        Returns:
            List[Tuple[int, int]]: A list of coordinates of captured stones.
        """
        opponent_color = 'X' if self.grid[x][y] == 'O' else 'O'
        captured_stones = []

        for dx, dy in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            nx, ny = x + dx, y + dy
            if 0 <= nx < self.size and 0 <= ny < self.size and self.grid[nx][ny] == opponent_color:
                group = self.get_groups(nx, ny)
                print(f"Checking group at ({nx}, {ny}): {group}")
                liberties = self.get_liberties(group)
                print(f"Liberties for group {group}: {liberties}")
                if liberties == 0:
                    for (gx, gy) in group:
                        self.remove_stone(gx, gy)
                        captured_stones.append((gx, gy))
        if captured_stones:
            print(f"Captured stones at {captured_stones}.")
        return captured_stones

    def get_groups(self, x: int, y: int) -> List[Tuple[int, int]]:
        """Return the group of stones connected to the given point (same color).
        
        Args:
            x (int): The x-coordinate on the board.
            y (int): The y-coordinate on the board.

        Returns:
            List[Tuple[int, int]]: A list of coordinates representing the group of stones.
        """
        color = self.grid[x][y]
        if color is None:
            return []

        group = []
        visited = set()
        stack = [(x, y)]

        while stack:
            cx, cy = stack.pop()
            if (cx, cy) not in visited:
                visited.add((cx, cy))
                group.append((cx, cy))
                # Check neighbors
                for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < self.size and 0 <= ny < self.size and self.grid[nx][ny] == color:
                        stack.append((nx, ny))
        return group

    def get_liberties(self, group: List[Tuple[int, int]]) -> int:
        """Calculate the number of liberties for a group of stones.
        
        Args:
            group (List[Tuple[int, int]]): The group of stones.

        Returns:
            int: The number of liberties (empty adjacent spaces).
        """
        liberties = set()
        for x, y in group:
            for dx, dy in [(0, 1), (0, -1), (1, 0), (-1, 0)]:
                nx, ny = x + dx, y + dy
                if 0 <= nx < self.size and 0 <= ny < self.size and self.grid[nx][ny] is None:
                    liberties.add((nx, ny))
        return len(liberties)