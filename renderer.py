import pygame
from constants import Constants


class Renderer:
    """Draws the board, stones, and a status panel."""

    def __init__(self, surface, game, origin, cell):
        self.surface = surface
        self.game = game
        self.origin = origin
        self.cell = cell
        self.font = pygame.font.SysFont(None, 20)

    def to_px(self, x: int, y: int):
        ox, oy = self.origin
        return (ox + x * self.cell, oy + y * self.cell)

    def render(self, msg=''):
        c = Constants.COLORS
        n = self.game.size
        self.surface.fill(c['background'])
        # grid lines
        for i in range(n):
            pygame.draw.line(self.surface, c['grid'], self.to_px(0, i), self.to_px(n - 1, i), 1)
            pygame.draw.line(self.surface, c['grid'], self.to_px(i, 0), self.to_px(i, n - 1), 1)
        # star points
        for (sx, sy) in Constants.STAR_POINTS:
            if sx < n and sy < n:
                pygame.draw.circle(self.surface, c['grid'], self.to_px(sx, sy), 3)
        # stones
        for x in range(n):
            for y in range(n):
                s = self.game.board.get_stone(x, y)
                if s is not None:
                    color = c['black_stone'] if s == 'X' else c['white_stone']
                    pygame.draw.circle(self.surface, color, self.to_px(x, y), Constants.STONE_RADIUS)
        self._panel(msg)

    def _panel(self, msg):
        c = Constants.COLORS
        st = self.game.state
        lines = []
        lines.append('Turn: {}'.format('Black' if st['current'] == 'X' else 'White'))
        lines.append('Black captured: {}'.format(self.game.black.get_captured_stones()))
        lines.append('White captured: {}'.format(self.game.white.get_captured_stones()))
        if st['game_over'] and st.get('score'):
            s = st['score']
            lines.append('Black {} : {} White'.format(s['black'], s['white']))
            lines.append('Winner: {}'.format(st.get('winner')))
        if msg:
            lines.append(msg)
        n = self.game.size
        ox, oy = self.origin
        px = ox + n * self.cell + Constants.MARGIN   # panel lives right of the board
        for i, line in enumerate(lines):
            img = self.font.render(line, True, c['text'])
            self.surface.blit(img, (px, 12 + i * 18))