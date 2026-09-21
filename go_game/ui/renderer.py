"""Draw the Go board, stones, and match status using pygame."""

import pygame

from constants import Constants


class Renderer:
    """Present an existing game state without modifying its rules engine."""

    def __init__(self, surface, game, origin, cell):
        self.surface = surface
        self.game = game
        self.origin = origin
        self.cell = cell
        self.font = pygame.font.SysFont(None, 20)

    def to_px(self, x: int, y: int):
        ox, oy = self.origin
        return ox + x * self.cell, oy + y * self.cell

    def render(self, msg=""):
        colors = Constants.COLORS
        size = self.game.size
        self.surface.fill(colors["background"])
        for pos in range(size):
            pygame.draw.line(
                self.surface, colors["grid"], self.to_px(0, pos),
                self.to_px(size - 1, pos), 1,
            )
            pygame.draw.line(
                self.surface, colors["grid"], self.to_px(pos, 0),
                self.to_px(pos, size - 1), 1,
            )
        for x, y in Constants.STAR_POINTS:
            if x < size and y < size:
                pygame.draw.circle(self.surface, colors["grid"], self.to_px(x, y), 3)
        for x in range(size):
            for y in range(size):
                stone = self.game.board.get_stone(x, y)
                if stone is not None:
                    color = colors["black_stone"] if stone == "X" else colors["white_stone"]
                    pygame.draw.circle(
                        self.surface, color, self.to_px(x, y), Constants.STONE_RADIUS,
                    )
        self._panel(msg)

    def _panel(self, msg):
        colors = Constants.COLORS
        state = self.game.state
        lines = [
            "Turn: {}".format("Black" if state["current"] == "X" else "White"),
            "Black captured: {}".format(self.game.black.get_captured_stones()),
            "White captured: {}".format(self.game.white.get_captured_stones()),
        ]
        if state["game_over"] and state.get("score"):
            score = state["score"]
            lines.append("Black {} : {} White".format(score["black"], score["white"]))
            winner = "Black" if score["black"] > score["white"] else (
                "White" if score["white"] > score["black"] else "Draw"
            )
            lines.append("Winner: {}".format(winner))
        if msg:
            lines.append(msg)
        offset_x = self.origin[0] + self.game.size * self.cell + Constants.MARGIN
        for index, line in enumerate(lines):
            image = self.font.render(line, True, colors["text"])
            self.surface.blit(image, (offset_x, 12 + index * 18))
