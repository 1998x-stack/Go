import copy
from constants import Constants
from gameboard import GameBoard
from player import Player


class Game:
    """Turn + pass + undo + ko + score orchestrator (pygame-free)."""

    def __init__(self, size: int = Constants.BOARD_SIZE):
        self.board = GameBoard(size)
        self.black = Player('X')
        self.white = Player('O')
        self.state = {
            'current': 'X',
            'passes': 0,
            'game_over': False,
            'komi': Constants.DEFAULT_KOMI,
            'score': None,
        }
        self.history = []          # (color, kind, move, grid_snapshot)
        self._seen = set()         # board keys that occurred, for ko

    @property
    def size(self):
        return self.board.size

    def players(self):
        return {'X': self.black, 'O': self.white}

    def player(self, color):
        return self.players()[color]

    def other(self, color):
        return 'O' if color == 'X' else 'X'

    def _flip(self):
        self.state['current'] = self.other(self.state['current'])

    def _push(self, color, kind, move):
        self.history.append((color, kind, move, copy.deepcopy(self.board.grid)))

    def setup(self, handicap: int = 0):
        self.state['komi'] = 0 if handicap > 0 else Constants.DEFAULT_KOMI
        for i in range(min(handicap, len(Constants.STAR_POINTS))):
            x, y = Constants.STAR_POINTS[i]
            self.board.grid[y][x] = 'X'
        self.state['current'] = 'O' if handicap > 0 else 'X'

    def can_play(self, x: int, y: int, color=None) -> bool:
        color = color or self.state['current']
        k = self.board.resulting_key(self.player(color), x, y)
        return k is not None and k not in self._seen

    def play(self, x: int, y: int):
        if self.state['game_over']:
            return False, 'Game over'
        color = self.state['current']
        k = self.board.resulting_key(self.player(color), x, y)
        if k is None:
            return False, 'Illegal move'
        if k in self._seen:
            return False, 'Ko repetition'
        self._push(color, 'move', (x, y))
        captured = self.board.make_move(self.player(color), x, y)
        self._seen.add(k)
        self.state['passes'] = 0
        self._flip()
        return True, 'placed (captured {})'.format(captured)

    def pass_move(self):
        if self.state['game_over']:
            return False, 'Game over'
        color = self.state['current']
        self._push(color, 'pass', None)
        self.state['passes'] += 1
        if self.state['passes'] >= 2:
            self.state['game_over'] = True
            self.finish()
        else:
            self._flip()
        return True, 'passed'

    def undo(self) -> bool:
        if not self.history:
            return False
        who, _, _, _ = self.history.pop()
        self.state['current'] = who
        self.state['passes'] = 0
        self.state['game_over'] = False
        self._recompute()
        return True

    def _recompute(self):
        """Rebuild the board and seen-keys from the remaining history."""
        fresh = GameBoard(self.size)
        seen = set()
        for (color, kind, move, _) in self.history:
            if kind == 'move':
                k = fresh.resulting_key(self.player(color), move[0], move[1])
                fresh.make_move(self.player(color), move[0], move[1])
                if k is not None:
                    seen.add(k)
        self.board.grid = fresh.grid
        self._seen = seen

    def finish(self):
        self.state['game_over'] = True
        black_area, white_area = self.board.score_areas()
        black = black_area
        white = white_area + self.state['komi']
        winner = 'X' if black > white else ('O' if white > black else 'draw')
        margin = abs(black - white)
        self.state['score'] = {'black': black, 'white': white}
        return {'black': black, 'white': white, 'winner': winner, 'margin': margin, 'over': True}