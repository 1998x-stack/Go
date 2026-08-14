import sys
import pygame
from constants import Constants
from game import Game
from ai import GreedyAI
from renderer import Renderer
from event_handler import click_to_point, handle_key
from sgf import game_to_sgf, sgf_to_game


def main():
    pygame.init()
    cell = 30
    margin = Constants.MARGIN
    n = Constants.BOARD_SIZE
    board_w = (n - 1) * cell + 2 * margin
    panel_w = 180
    width, height = board_w + panel_w, board_w
    screen = pygame.display.set_mode((width, height))
    pygame.display.set_caption('Go')
    game = Game()
    ai = GreedyAI()
    human = 'X'
    origin = (margin, margin)
    renderer = Renderer(screen, game, origin, cell)
    # optional sound: never allowed to crash the game
    try:
        from sound import Sound
        snd = Sound()
    except Exception:
        snd = None
    clock = pygame.time.Clock()
    msg = ''
    running = True

    while running:
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False
            elif ev.type == pygame.KEYDOWN:
                act = handle_key(ev.key)
                if act == 'undo':
                    msg = 'Undid' if game.undo() else 'Nothing to undo'
                elif act == 'pass' and game.state['current'] == human and not game.state['game_over']:
                    game.pass_move()
                    msg = 'You passed'
                elif act == 'finish':
                    game.finish()
                elif act == 'save':
                    with open('game.sgf', 'w') as f:
                        f.write(game_to_sgf(game))
                    msg = 'Saved game.sgf'
                elif act == 'load':
                    try:
                        with open('game.sgf') as f:
                            game = sgf_to_game(f.read())
                        renderer.game = game
                        msg = 'Loaded game.sgf'
                    except Exception:
                        msg = 'Load failed'
                elif act == 'quit':
                    running = False

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                pt = click_to_point(game, ev.pos, origin, cell)
                if pt and game.state['current'] == human and not game.state['game_over']:
                    ok, text = game.play(pt[0], pt[1])
                    msg = text if ok else 'Illegal move'
                    if ok and snd is not None:
                        snd.play_sound_effect('place.wav')

        # AI responds when it's not the human's turn
        if not game.state['game_over'] and game.state['current'] != human:
            mv = ai.choose(game)
            pygame.time.wait(200)
            if mv is None:
                game.pass_move()
                msg = 'AI passed'
            else:
                msg = 'AI played {}'.format(mv)
                game.play(mv[0], mv[1])

        renderer.render(msg)
        pygame.display.flip()
        clock.tick(30)

    pygame.quit()
    sys.exit(0)


if __name__ == '__main__':
    main()