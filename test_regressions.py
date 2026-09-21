"""Rules and record regressions (stdlib only, no pygame display needed)."""

import unittest

from game import Game
from gameboard import GameBoard
from player import Player
from sgf import game_to_sgf, sgf_to_game


class TestStateRestoration(unittest.TestCase):
    def test_initial_position_is_known(self):
        g = Game(size=5)
        self.assertIn(g.board.board_key(), g._seen)

    def test_undo_after_capture_restores_board_prisoners_and_turn(self):
        g = Game(size=5)
        for move in ((0, 1), (1, 1), (1, 0), (4, 4),
                     (1, 2), (4, 3), (2, 1)):
            self.assertTrue(g.play(*move)[0])
        self.assertEqual(g.black.captured_stones, 1)
        self.assertIsNone(g.board.get_stone(1, 1))
        self.assertTrue(g.undo())
        self.assertEqual(g.state['current'], 'X')
        self.assertEqual(g.black.captured_stones, 0)
        self.assertEqual(g.board.get_stone(1, 1), 'O')
        self.assertIsNone(g.board.get_stone(2, 1))
        self.assertTrue(g.play(2, 1)[0])
        self.assertEqual(g.black.captured_stones, 1)

    def test_undo_keeps_handicap(self):
        g = Game()
        g.setup(handicap=2)
        initial = g.board.board_key()
        self.assertTrue(g.play(10, 10)[0])
        self.assertTrue(g.undo())
        self.assertEqual(g.board.board_key(), initial)
        self.assertEqual(g.state['current'], 'O')
        self.assertEqual(len(g._seen), 1)
        self.assertEqual(g.state['komi'], 0)

    def test_undo_consecutive_pass_restores_counter(self):
        g = Game(size=5)
        g.pass_move()
        g.pass_move()
        self.assertTrue(g.state['game_over'])
        self.assertTrue(g.undo())
        self.assertFalse(g.state['game_over'])
        self.assertEqual(g.state['passes'], 1)
        self.assertIsNone(g.state['score'])
        self.assertEqual(g.state['current'], 'O')
        self.assertTrue(g.pass_move()[0])
        self.assertTrue(g.state['game_over'])

    def test_undo_after_manual_finish_clears_stale_score(self):
        g = Game(size=5)
        g.play(0, 0)
        g.finish()
        self.assertTrue(g.undo())
        self.assertFalse(g.state['game_over'])
        self.assertIsNone(g.state['score'])

    def test_can_play_disallows_finished_game(self):
        g = Game(size=5)
        g.finish()
        self.assertFalse(g.can_play(1, 1))

    def test_setup_rejects_invalid_handicap_and_late_setup(self):
        g = Game()
        for h in (-1, 10, 1.5):
            with self.subTest(handicap=h), self.assertRaises(ValueError):
                g.setup(h)
        g.play(0, 0)
        with self.assertRaises(ValueError):
            g.setup(2)
        with self.assertRaises(ValueError):
            Game(9).setup(2)

    def test_ko_recapture_still_forbidden(self):
        g = Game()
        seq = [(1, 0), (2, 0), (1, 2), (2, 2), (0, 1),
               (3, 1), (4, 0), (1, 1), (2, 1)]
        for move in seq:
            self.assertTrue(g.play(*move)[0])
        self.assertFalse(g.can_play(1, 1))
        self.assertTrue(g.can_play(9, 9))


class TestSGFRecords(unittest.TestCase):
    def test_roundtrip_passes_and_board_size(self):
        g = Game(size=9)
        g.play(0, 0)
        g.pass_move()
        g.play(8, 8)
        record = game_to_sgf(g)
        self.assertIn('SZ[9]', record)
        self.assertIn(';W[]', record)
        restored = sgf_to_game(record)
        self.assertEqual(restored.board.board_key(), g.board.board_key())
        self.assertEqual(restored.state['current'], g.state['current'])
        self.assertEqual([entry[:3] for entry in restored.history],
                         [entry[:3] for entry in g.history])

    def test_roundtrip_two_passes_and_komi(self):
        g = Game(size=9)
        g.state['komi'] = 7.5
        g.pass_move()
        g.pass_move()
        restored = sgf_to_game(game_to_sgf(g))
        self.assertTrue(restored.state['game_over'])
        self.assertEqual(restored.state['komi'], 7.5)
        self.assertEqual(len(restored.history), 2)

    def test_roundtrip_handicap_points_and_turn(self):
        g = Game()
        g.setup(handicap=3)
        g.play(10, 10)
        record = game_to_sgf(g)
        self.assertIn('HA[3]AB', record)
        restored = sgf_to_game(record)
        self.assertEqual(restored.board.board_key(), g.board.board_key())
        self.assertEqual(restored.state['current'], g.state['current'])
        self.assertEqual(restored.state['komi'], g.state['komi'])
        self.assertEqual(restored.handicap, 3)
        self.assertTrue(restored.undo())
        self.assertEqual(restored.board.board_key(),
                         tuple(tuple(row) for row in g._initial_grid))

    def test_custom_handicap_coordinates_preserved(self):
        text = '(;GM[1]FF[4]SZ[19]KM[0]HA[2]AB[dd][pp];W[jj])'
        g = sgf_to_game(text)
        self.assertEqual(g.board.get_stone(3, 3), 'X')
        self.assertEqual(g.board.get_stone(15, 15), 'X')
        self.assertEqual(g.board.get_stone(9, 9), 'O')
        self.assertEqual(sgf_to_game(game_to_sgf(g)).board.board_key(),
                         g.board.board_key())

    def test_invalid_moves_fail_instead_of_being_dropped(self):
        bad = [
            '(;SZ[5];B[aa];W[aa])',
            '(;SZ[5];B[zz])',
            '(;SZ[5];W[aa])',
            '(;SZ[5];B[];W[];B[aa])',
            '(;SZ[5];B[aa];B[bb])',
            '(;SZ[5];B[aa];W)',
            '(;SZ[5];B[aa](;W[bb]))',
            '(;SZ[5]HA[2]AB[aa])',
        ]
        for record in bad:
            with self.subTest(record=record), self.assertRaises(ValueError):
                sgf_to_game(record)

    def test_plain_record_without_komi_uses_default(self):
        g = sgf_to_game('(;GM[1]SZ[9];B[aa];W[bb])')
        self.assertEqual(g.state['komi'], 6.5)
        self.assertEqual(g.board.get_stone(0, 0), 'X')
        self.assertEqual(g.board.get_stone(1, 1), 'O')


class TestCaptureAccounting(unittest.TestCase):
    def test_one_connected_group_touching_move_four_times_counted_once(self):
        b = GameBoard(size=5)
        group = {(1, 1), (1, 2), (1, 3), (2, 1), (2, 3),
                 (3, 1), (3, 2), (3, 3)}
        for x in range(5):
            for y in range(5):
                b.grid[x][y] = None if (x, y) == (2, 2) else (
                    'O' if (x, y) in group else 'X')
        player = Player('X')
        self.assertTrue(b.place_stone(player, 2, 2))
        self.assertEqual(player.captured_stones, len(group))
        for x, y in group:
            self.assertIsNone(b.grid[x][y])


if __name__ == '__main__':
    unittest.main()
