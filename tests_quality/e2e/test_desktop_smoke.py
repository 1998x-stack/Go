"""Exercise pygame UI only when the complete upstream repository is available."""
import os
from pathlib import Path

import pytest


def test_ui_render_smoke_only_in_complete_checkout():
    repo = Path(__file__).resolve().parents[2]
    if not (repo / "go_game" / "app.py").is_file():
        pytest.skip("Core-only extraction has no desktop UI files")
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    os.environ["SDL_AUDIODRIVER"] = "dummy"
    import pygame
    from game import Game
    from go_game.ui.renderer import Renderer

    pygame.init()
    try:
        screen = pygame.display.set_mode((800, 650))
        game = Game()
        renderer = Renderer(screen, game, (24, 24), 30)
        renderer.render("isolated-e2e")
        game.pass_move()
        game.pass_move()
        renderer.render("terminated")
        assert game.state["game_over"]
    finally:
        pygame.quit()
