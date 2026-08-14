import re
from game import Game


def _pt_to_sgf(move):
    x, y = move
    return chr(ord('a') + x) + chr(ord('a') + y)


def _sgf_to_pt(s):
    return (ord(s[0]) - ord('a'), ord(s[1]) - ord('a'))


def game_to_sgf(game) -> str:
    lines = ['(;GM[1]FF[4]SZ[{}]KM[{}]'.format(game.size, game.state['komi'])]
    for (color, kind, move, _) in game.history:
        tag = 'B' if color == 'X' else 'W'
        if kind == 'pass' or move is None:
            lines.append('{}[]'.format(tag))
        else:
            lines.append('{}[{}]'.format(tag, _pt_to_sgf(move)))
    return ''.join(lines) + ')'


def sgf_to_game(text) -> Game:
    g = Game()
    km = re.search(r'KM\[([0-9.]+)\]', text)
    if km:
        g.state['komi'] = float(km.group(1))
    ha = re.search(r'HA\[(\d+)\]', text)
    if ha:
        g.setup(handicap=int(ha.group(1)))
    for m in re.finditer(r'[BW]\[[a-t]{2}\]', text):
        tag = m.group(0)[0]
        who = 'X' if tag == 'B' else 'O'
        x, y = _sgf_to_pt(m.group(0)[2:4])
        if g.state['current'] != who:
            g.pass_move()
        g.play(x, y)
    return g