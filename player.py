class Player:
    """A Go player: color, captured-stones counter, human designation."""

    def __init__(self, color: str):
        if color not in ['X', 'O']:
            raise ValueError("Invalid color: must be 'X' (black) or 'O' (white)")
        self.color = color
        self.captured_stones = 0
        self.is_human = True

    def get_color(self) -> str:
        return self.color

    def increment_captured_stones(self, count: int) -> None:
        if count < 0:
            raise ValueError("Captured stones count cannot be negative.")
        self.captured_stones += count

    def get_captured_stones(self) -> int:
        return self.captured_stones

    def make_move(self, game_board, x: int, y: int) -> bool:
        return game_board.place_stone(self, x, y)