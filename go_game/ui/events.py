"""Translate pygame input into board coordinates and application commands."""

import pygame


def click_to_point(game, pos, origin, cell):
    """Return a nearby board intersection, or None for off-board clicks."""
    x, y = pos
    ox, oy = origin
    gx = round((x - ox) / cell)
    gy = round((y - oy) / cell)
    if 0 <= gx < game.size and 0 <= gy < game.size:
        px, py = ox + gx * cell, oy + gy * cell
        if abs(x - px) <= cell * 0.45 and abs(y - py) <= cell * 0.45:
            return gx, gy
    return None


def handle_key(key):
    """Convert a pygame key to a known action, or None."""
    actions = {
        pygame.K_u: "undo", pygame.K_p: "pass", pygame.K_g: "finish",
        pygame.K_s: "save", pygame.K_l: "load", pygame.K_q: "quit",
        pygame.K_ESCAPE: "quit",
    }
    return actions.get(key)
