import pygame


def click_to_point(game, pos, origin, cell):
    x, y = pos
    ox, oy = origin
    gx = round((x - ox) / cell)
    gy = round((y - oy) / cell)
    if 0 <= gx < game.size and 0 <= gy < game.size:
        px, py = ox + gx * cell, oy + gy * cell
        if abs(x - px) <= cell * 0.45 and abs(y - py) <= cell * 0.45:
            return (gx, gy)
    return None


def handle_key(key):
    if key == pygame.K_u:
        return 'undo'
    if key == pygame.K_p:
        return 'pass'
    if key == pygame.K_g:
        return 'finish'
    if key == pygame.K_s:
        return 'save'
    if key == pygame.K_l:
        return 'load'
    if key in (pygame.K_q, pygame.K_ESCAPE):
        return 'quit'
    return None