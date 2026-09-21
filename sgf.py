"""Minimal, strict SGF reader/writer for this game's linear records.

This is intentionally not a general-purpose SGF parser: variations, markup,
non-handicap setup edits, and escaped property values are not supported.
"""

import re

from game import Game


def _pt_to_sgf(move):
    x, y = move
    return chr(ord('a') + x) + chr(ord('a') + y)


def _sgf_to_pt(s):
    if len(s) != 2 or not s.isascii() or not s.islower() or not s.isalpha():
        raise ValueError('Invalid SGF coordinate')
    return ord(s[0]) - ord('a'), ord(s[1]) - ord('a')


def game_to_sgf(game) -> str:
    """Export board size, komi, fixed handicap positions, moves and passes."""
    lines = ['(;GM[1]FF[4]SZ[{}]KM[{}]'.format(game.size, game.state['komi'])]
    if game.handicap:
        points = [(x, y) for x in range(game.size) for y in range(game.size)
                  if game._initial_grid[x][y] == 'X']
        lines.append('HA[{}]AB{}'.format(
            game.handicap, ''.join('[{}]'.format(_pt_to_sgf(p)) for p in points)))
    for color, kind, move, _ in game.history:
        tag = 'B' if color == 'X' else 'W'
        value = '' if kind == 'pass' else _pt_to_sgf(move)
        lines.append(';{}[{}]'.format(tag, value))
    return ''.join(lines) + ')'


def sgf_to_game(text) -> Game:
    """Read one linear game; fail loudly on invalid turns or illegal moves."""
    if not isinstance(text, str) or not text.startswith('(;') or not text.endswith(')'):
        raise ValueError('Expected a single SGF game tree')
    if '(' in text[1:] or ')' in text[:-1]:
        raise ValueError('SGF variations are not supported')
    nodes = text[2:-1].split(';')
    header = nodes[0]
    size_match = re.search(r'SZ\[(\d+)\]', header)
    if not size_match:
        raise ValueError('Missing board size')
    g = Game(size=int(size_match.group(1)))
    ha_match = re.search(r'HA\[(\d+)\]', header)
    handicap = int(ha_match.group(1)) if ha_match else 0
    if handicap:
        g.setup(handicap=handicap)
        ab_match = re.search(r'AB((?:\[[a-z]{2}\])+)', header)
        if ab_match:
            points = re.findall(r'\[([a-z]{2})\]', ab_match.group(1))
            if len(points) != handicap or len(set(points)) != handicap:
                raise ValueError('Handicap placements do not match HA')
            g.board = type(g.board)(g.size)
            for value in points:
                x, y = _sgf_to_pt(value)
                if not g.board.in_bounds(x, y):
                    raise ValueError('Handicap point outside board')
                g.board.grid[x][y] = 'X'
            g._initial_grid = [row[:] for row in g.board.grid]
            g._seen = {g.board.board_key()}
    elif re.search(r'AB\[', header):
        raise ValueError('Setup stones require HA in this SGF subset')
    km_match = re.search(r'KM\[(-?\d+(?:\.\d+)?)\]', header)
    if km_match:
        g.state['komi'] = float(km_match.group(1))
    for node in nodes[1:]:
        match = re.fullmatch(r'([BW])\[([a-z]{2})?\]', node)
        if not match:
            raise ValueError('Unsupported or invalid SGF move node: {!r}'.format(node))
        color = 'X' if match.group(1) == 'B' else 'O'
        if g.state['current'] != color:
            raise ValueError('SGF moves are out of turn')
        if match.group(2) is None:
            ok, reason = g.pass_move()
        else:
            x, y = _sgf_to_pt(match.group(2))
            ok, reason = g.play(x, y)
        if not ok:
            raise ValueError('Invalid SGF move: {}'.format(reason))
    return g
