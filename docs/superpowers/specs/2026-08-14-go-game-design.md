# Go Game — Complete Fix & Feature Design

**Date:** 2026-08-14
**Scope:** Correct the rules engine, build a runnable pygame Go game, add AI, scoring,
undo, SGF, handicap. (Option C)
**Stack:** Python 3.9 stdlib + already-installed pygame (headless-testable engine).

## Problem Summary (from reanalysis)
The current project is a headless, partially-broken Go rules prototype:
1. `is_valid_move` checks liberties of a single point, not the connected group -> rejects
   legal group extensions (confirmed) and ignores captures in the legality calculation.
2. Captures are detected but never credited to the owning `Player`, so scoring is broken.
3. No `ko` rule, no pass/endgame/scoring, no runnable game (`main.py`/`event_handler.py`
   are 0 bytes).
4. The two test files are broken (`unittest.mock` not imported; `test_capture_stones`
   double-executes a capture).

## Goals (non-functional)
- Correct Go legality following real rules.
- Runnable pygame GUI: click to place, AI alternation, pass/end, score overlay, undo.
- Extras: AI (random + greedy), Chinese area scoring + komi, handicap, SGF save/load.
- Everything in the engine is unit-testable with the stdlib `unittest`, no pygame window.

## Architecture

```text
constants.py   (constants only, extended)
gameboard.py   (rules engine + scoring + ko + history of GameBoard states)
player.py      (Player: color, captures, human flag)
game.py        (Game orchestrator: turn, pass, handicap, undo, game-over, score)
ai.py          (strategies: random, greedy)
sgf.py         (SGF reader/writer subset)
renderer.py    (draw board+stones etc. from constants)
event_handler.py (input -> actions)
main.py        (pygame main loop)
test_*.py      (headless tests)
sound.py       (optional audio, already present)
```

Rules-engine must not import pygame; only `main.py`, `renderer.py`, `event_handler.py`,
and (optionally) sound.py depend on pygame. This keeps all logic headless-testable.

## Rules Engine (gameboard.py)

Board: 19x19 `grid[x][y]` (x first) with `None`/`'X'`/`'O'`.

- `is_legal(player, x, y) -> bool`: real Go legality —
  1. in bounds, empty
  2. simulate placement, remove opponent groups that lose all liberties (capture)
  3. the placed stone's **connected group** has >= 1 liberty; otherwise illegal (suicide)
  4. ko: the resulting board position must not equal the position 1-ago (simple ko).
- `make_move(player, x, y) -> (ok: bool, captured: int)`:
  - if illegal, return False
  - place, capture opponent groups with 0 liberties, return True + count
- `capture_stones` returns list of captured coords; **`place_stone`/`make_move` calls
  `player.increment_captured_stones(len(captured))`** (fixes scoring bug).
- `find_groups(color) -> list of groups` (each a list of coords).
- `liberties_of(coords) -> int`.
- `board_key() -> hashable` for ko/history (tuple of tuples).
- `undo_last(self)` internal not needed — Game owns history.

## Player (player.py)
- `__init__(color)` unchanged contract: `'X'`/`'O'`, captures=0.
- add `is_human: bool = True`.
- `increment_captured_stones` stays (now actually called by the engine).

## Game (game.py) — orchestration
- `__init__(board_size=19)`
- `state`: `current_player`, `passes`, `game_over`, `komi`.
- `setup(handicap=0)`: place handicap stones on star points if requested; set komi
  (6.5 normal, 0 when handicap>0).
- `play(x, y)`: board.make_move for current player; on success record to history (for
  undo + SGF), maybe capture+placing triggers reload. Switch turn.
- `pass_move()`: increments `passes`; two consecutive passes -> `finish()`.
- `finish()`: compute Chinese (area) score, returns `(black_score, white_score, winner)`.
- `undo()`: pop last move from history and revert board (restores captures via
  history snapshots of full board state, simplest and robust; board up to 361 cells won't
  be a memory concern).
- `history`: list of `(player_color, move_or_pass, board_snapshot)` for undo + SGF.
- Handicap + komi rules documented here.

## AI (ai.py)
- `choose_move(game) -> (x, y)` given current board.
- RandomAI: choose uniformly from legal empties (may pass if none).
- GreedyAI: for each legal candidate play it via copy, use a small embedded
  heuristic: maximize `(area gain - komi) + captures led`, pick best; tie -> random.
- No mini-max / no external engine. Difficulty = which strategy.
- AI is `injected`; `Game.take_turn()` uses it when `not is_human`.

## Rendering (renderer.py + constants)
- constants.py extended: cell size derived from `BOARD_SIZE`, window sized to fit
  `19x19` comfortably (margin + stones).
- draw: background, grid lines, star points, coordinates, stones, last-move marker,
  current player banner, menu hints.

## event_handler.py
- translate click (px -> board coords); return an `Action`: move / pass / undo / finish /
  save / load / quit.
- keyboard shortcuts (e.g. `p` pass, `u` undo, `q` quit, `g` game-over).

## SGF (sgf.py)
- subset writer: header (`SZ`, `KM`, `HA`, `PB`/`PW`, `B`/`W` move points) and
  reader that replays the record into a Game for inspection/continue.
- strict; unknown properties ignored gracefully.

## main.py
- pygame main loop: create Game, renderer; loop on events -> actions; auto-run AI turns;
- on `finish`, render score dialog + prompt to restart/quit.

## Sound (sound.py) [unchanged]
- optional; each call wrapped in try/except pygame.error already; wire: place, capture,
  game over. never crash if audio file missing.

---

## Testing (headless `unittest`)
Rewrite the two existing files; add:
`test_gameboard.py`: suicide (genuine suicide rejected), legal group extension accepted,
capture-over move allowed, scoring, ko enforced, captured counting, handicap placement.
`test_player.py`: contract, captures increment correctness.
**new** `test_game.py`: turn alternation, pass logic, two-pass finish, undo
(move+no-capture step, scoring, komi, handicap.
**new** `test_ai.py`: greedy picks capture over, random stays in bounds/legal.
**new** `test_sgf.py`: round-trip equality of move records.

All tests exclusively use stdlib and do not import `game.py` without init. No window.

## Error Handling
- All rendering/music failures are swallowed (try/except) so headless/absent audio never
  crash gameplay.
- Illegal moves and invalid SGF records are silently rejected / logged, never crash.

## Out of Scope (YAGNI)
- Japanese (territory) scoring; only Chinese/Korean area scoring.
- Mini-max/engine-grade AI; deep game analysis; full SGF spec; networked play.

### Verification
- `python3 -m pytest *.py -v` green.
- `python3 main.py` launches window, human vs AI; passes 2x -> score overlay.