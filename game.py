"""Turn management and rules state for a headless Go game."""

import copy

from constants import Constants
from gameboard import GameBoard
from player import Player


class Game:
    """Go with positional-superko for stone placements and two-pass scoring.

    The initial setup position is part of the position history. Passes do not
    count as repeated positions. The history stores pre-move board snapshots
    for compatibility with the existing renderer and SGF writer.
    """

    def __init__(self, size: int = Constants.BOARD_SIZE):
        if type(size) is not int or not 2 <= size <= 26:
            raise ValueError('Board size must be an integer between 2 and 26')
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
        self.history = []
        self.handicap = 0
        self._initial_grid = copy.deepcopy(self.board.grid)
        self._seen = {self.board.board_key()}

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
        """Set up a fresh 19x19 handicap game, or reset to an empty game."""
        if type(handicap) is not int or not 0 <= handicap <= len(Constants.STAR_POINTS):
            raise ValueError('Handicap must be between 0 and {}'.format(len(Constants.STAR_POINTS)))
        if handicap and self.size != 19:
            raise ValueError('Fixed handicap is supported only on a 19x19 board')
        if self.history:
            raise ValueError('Cannot change the setup after the game has started')
        self.board = GameBoard(self.size)
        self.handicap = handicap
        for x, y in Constants.STAR_POINTS[:handicap]:
            self.board.grid[x][y] = 'X'
        self._initial_grid = copy.deepcopy(self.board.grid)
        self._seen = {self.board.board_key()}
        self.black.captured_stones = 0
        self.white.captured_stones = 0
        self.state.update({
            'current': 'O' if handicap else 'X',
            'passes': 0,
            'game_over': False,
            'komi': 0 if handicap else Constants.DEFAULT_KOMI,
            'score': None,
        })

    def can_play(self, x: int, y: int, color=None) -> bool:
        if self.state['game_over']:
            return False
        if color is None:
            color = self.state['current']
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
            self.finish()
        else:
            self._flip()
        return True, 'passed'

    def undo(self) -> bool:
        if not self.history:
            return False
        self.history.pop()
        self._recompute()
        return True

    def _recompute(self):
        """Rebuild *all* derived state from setup and the surviving moves."""
        fresh = GameBoard(self.size)
        fresh.grid = copy.deepcopy(self._initial_grid)
        seen = {fresh.board_key()}
        self.black.captured_stones = 0
        self.white.captured_stones = 0
        passes = 0
        current = 'O' if self.handicap else 'X'
        for color, kind, move, _ in self.history:
            if color != current:
                raise ValueError('Inconsistent turn history')
            if kind == 'pass':
                passes += 1
            elif kind == 'move':
                if move is None:
                    raise ValueError('Missing move coordinates')
                k = fresh.resulting_key(self.player(color), *move)
                if k is None or k in seen:
                    raise ValueError('Invalid move in history')
                fresh.make_move(self.player(color), *move)
                seen.add(k)
                passes = 0
            else:
                raise ValueError('Unknown history action')
            current = self.other(current)
        self.board.grid = fresh.grid
        self._seen = seen
        self.state['current'] = current
        self.state['passes'] = passes
        self.state['game_over'] = passes >= 2
        self.state['score'] = None
        if self.state['game_over']:
            self.finish()

    def finish(self):
        self.state['game_over'] = True
        black_area, white_area = self.board.score_areas()
        black = black_area
        white = white_area + self.state['komi']
        winner = 'X' if black > white else ('O' if white > black else 'draw')
        margin = abs(black - white)
        self.state['score'] = {'black': black, 'white': white}
        return {'black': black, 'white': white, 'winner': winner, 'margin': margin, 'over': True}
