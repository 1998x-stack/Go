"""Desktop/browser application entry point; rules remain pygame-free."""

import asyncio
import logging
from uuid import uuid4

import pygame

from ai import GreedyAI
from constants import Constants
from game import Game
from sgf import game_to_sgf, sgf_to_game

from .observability import configure_logging
from .ui.events import click_to_point, handle_key
from .ui.renderer import Renderer
from .ui.sound import Sound

logger = logging.getLogger("go_game.app")
_RECORD_FILE = "game.sgf"


def _event(game_id, event, **fields):
    """Build a small allowlisted diagnostic context; never include SGF text."""
    return {"game_id": game_id, "event": event, **fields}


async def main():
    """Start the interactive game and yield to the pygbag event loop."""
    configure_logging()
    pygame.init()
    cell = 30
    margin = Constants.MARGIN
    board_width = (Constants.BOARD_SIZE - 1) * cell + 2 * margin
    screen = pygame.display.set_mode((board_width + 180, board_width))
    pygame.display.set_caption("Go")

    game = Game()
    game_id = uuid4().hex[:12]
    ai = GreedyAI()
    human = "X"
    origin = (margin, margin)
    renderer = Renderer(screen, game, origin, cell)
    try:
        sound = Sound()
    except Exception:
        logger.exception("Optional sound setup failed", extra=_event(game_id, "audio.setup_failed"))
        sound = None

    logger.info("Game started", extra=_event(game_id, "game.started"))
    message = ""
    running = True
    try:
        while running:
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN:
                    action = handle_key(event.key)
                    if action == "undo":
                        undone = game.undo()
                        message = "Undid" if undone else "Nothing to undo"
                        if undone:
                            logger.info("Move undone", extra=_event(game_id, "game.undo"))
                    elif action == "pass" and game.state["current"] == human and not game.state["game_over"]:
                        game.pass_move()
                        message = "You passed"
                        logger.info("Human passed", extra=_event(game_id, "game.pass", turn=human))
                    elif action == "finish":
                        result = game.finish()
                        logger.info(
                            "Game scored", extra=_event(game_id, "game.finished", reason=result["winner"]),
                        )
                    elif action == "save":
                        try:
                            with open(_RECORD_FILE, "w", encoding="utf-8") as output:
                                output.write(game_to_sgf(game))
                        except OSError:
                            message = "Save failed"
                            logger.exception("Unable to save game", extra=_event(game_id, "sgf.save_failed"))
                        else:
                            message = "Saved game.sgf"
                            logger.info("Game saved", extra=_event(game_id, "sgf.saved"))
                    elif action == "load":
                        try:
                            with open(_RECORD_FILE, encoding="utf-8") as source:
                                loaded = sgf_to_game(source.read())
                        except (OSError, ValueError):
                            message = "Load failed"
                            logger.exception("Unable to load game", extra=_event(game_id, "sgf.load_failed"))
                        else:
                            game = loaded
                            renderer.game = game
                            game_id = uuid4().hex[:12]
                            message = "Loaded game.sgf"
                            logger.info("Game loaded", extra=_event(game_id, "sgf.loaded"))
                    elif action == "quit":
                        running = False

                elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                    point = click_to_point(game, event.pos, origin, cell)
                    if point and game.state["current"] == human and not game.state["game_over"]:
                        ok, reason = game.play(*point)
                        message = reason if ok else "Illegal move"
                        if ok:
                            logger.info(
                                "Human played", extra=_event(
                                    game_id, "game.move", turn=human, move=point,
                                ),
                            )
                            if sound is not None:
                                sound.play_sound_effect("place.wav")
                        else:
                            logger.debug(
                                "Move rejected: %s", reason,
                                extra=_event(game_id, "game.move_rejected", turn=human),
                            )

            if not running:
                break
            if not game.state["game_over"] and game.state["current"] != human:
                current_game = game
                move = ai.choose(game)
                await asyncio.sleep(0.1)
                # A saved/restored game or an external event can invalidate a planned move.
                if current_game is game and not game.state["game_over"] and game.state["current"] != human:
                    if move is None:
                        ok, reason = game.pass_move()
                        message = "AI passed" if ok else reason
                        if ok:
                            logger.info("AI passed", extra=_event(game_id, "game.pass", turn="O"))
                    else:
                        ok, reason = game.play(*move)
                        message = "AI played {}".format(move) if ok else reason
                        if ok:
                            logger.info(
                                "AI played", extra=_event(game_id, "game.move", turn="O", move=move),
                            )
                        else:
                            logger.error(
                                "AI move rejected: %s", reason,
                                extra=_event(game_id, "ai.move_rejected", turn="O", move=move),
                            )

            renderer.render(message)
            pygame.display.flip()
            await asyncio.sleep(0)
    finally:
        logger.info("Game stopped", extra=_event(game_id, "game.stopped"))
        pygame.quit()
