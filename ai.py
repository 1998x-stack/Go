import random
from gameboard import GameBoard
from player import Player

_NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))


class RandomAI:
    """Uniformly random legal, non-ko move (or None to pass)."""

    name = 'Random'

    def choose(self, game):
        if game.state['game_over']:
            return None
        color = game.state['current']
        pts = [(x, y) for x in range(game.size) for y in range(game.size)
               if game.can_play(x, y, color)]
        return random.choice(pts) if pts else None


class GreedyAI(RandomAI):
    """Maximize own area gain + captures, simulated on a board copy."""

    name = 'Greedy'

    def _candidates(self, game):
        """Relevant legal points: empty cells adjacent to a stone. Falls back
        to all legal points when there are no stones (empty board)."""
        color = game.state['current']
        grid = game.board.grid
        size = game.size
        relevant = set()
        for x in range(size):
            for y in range(size):
                if grid[x][y] is not None:
                    for dx, dy in _NEIGHBORS:
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < size and 0 <= ny < size and grid[nx][ny] is None:
                            relevant.add((nx, ny))
        legal = [p for p in relevant if game.can_play(p[0], p[1], color)]
        if legal:
            return sorted(legal, key=lambda p: (p[0], p[1]))
        return sorted(((x, y) for x in range(size) for y in range(size)
                       if game.can_play(x, y, color)), key=lambda p: (p[0], p[1]))

    CAPTURE_BONUS = 1.0  # explicit weight for captured stones in scoring

    def _score_move(self, game, color, x, y, own):
        """Post-move area minus shared base, plus the capture weight.
        Uses score_areas() for the after-score (identical scoring to the
        reference), so territory evaluation is guaranteed equivalent. The
        per-attempt board copy is retained: profiling showed it negligible
        vs score_areas(), and it keeps the simulation isolated/readable."""
        sim = GameBoard(game.size)
        sim.grid = [row[:] for row in game.board.grid]
        tmp = Player(color)
        if not sim.place_stone(tmp, x, y):
            return float('-inf')
        new = sim.score_areas()[0 if color == 'X' else 1]
        return (new - own) + self.CAPTURE_BONUS * tmp.captured_stones

    def choose(self, game):
        if game.state['game_over']:
            return None
        color = game.state['current']
        own = game.board.score_areas()[0 if color == 'X' else 1]  # shared base, once
        pts = self._candidates(game)
        best, best_val = None, float('-inf')
        for (x, y) in pts:
            v = self._score_move(game, color, x, y, own)
            if v > best_val:
                best_val, best = v, (x, y)
        return best