class Constants:
    """Shared constants for the Go game."""

    BOARD_SIZE = 19
    MARGIN = 24
    STONE_RADIUS = 14
    DEFAULT_KOMI = 6.5

    # 9 star points on a 19x19 board, as (x, y)
    STAR_POINTS = [
        (3, 3), (9, 3), (15, 3),
        (3, 9), (9, 9), (15, 9),
        (3, 15), (9, 15), (15, 15),
    ]

    COLORS = {
        'background': (222, 184, 135),
        'grid': (60, 40, 20),
        'black_stone': (20, 20, 20),
        'white_stone': (245, 245, 245),
        'text': (30, 30, 30),
        'accent': (200, 30, 30),
    }