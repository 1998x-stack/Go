import random
from gameboard import GameBoard
from player import Player


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

    def _score_move(self, game, color, x, y):
        sim = GameBoard(game.size)
        sim.grid = [row[:] for row in game.board.grid]
        tmp = Player(color)
        base = sim.score_areas()
        idx = 0 if color == 'X' else 1
        if not sim.place_stone(tmp, x, y):
            return float('-inf')
        new = sim.score_areas()
        return (new[idx] - base[idx]) + tmp.captured_stones

    def choose(self, game):
        if game.state['game_over']:
            return None
        color = game.state['current']
        pts = [(x, y) for x in range(game.size) for y in range(game.size)
              if game.can_play(x, y, color)]
        if not pts:
            return None
        best, best_val = None, float('-inf')
        for (x, y) in pts:
            v = self._score_move(game, color, x, y)
            if v > best_val:
                best_val, best = v, (x, y)
        return best