class Constants:
    """Constants used throughout the Go game."""

    # Board dimensions
    BOARD_SIZE = 19  # The Go board is 19x19

    # Screen dimensions
    SCREEN_WIDTH = 600
    SCREEN_HEIGHT = 600
    SCREEN_SIZE = (SCREEN_WIDTH, SCREEN_HEIGHT)

    # Colors
    COLORS = {
        'background': (255, 255, 255),  # White background
        'grid': (0, 0, 0),              # Black grid lines
        'black_stone': (0, 0, 0),       # Black stones
        'white_stone': (255, 255, 255), # White stones
    }

    # Other game settings
    STONE_RADIUS = 14  # Radius of the stones when drawn on the board
    GRID_LINE_WIDTH = 2  # Width of the grid lines
    MARGIN = 20  # Margin from the edge of the window to the grid