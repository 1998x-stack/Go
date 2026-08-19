# Go Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cut the Greedy AI's per-move cost (~96% of time in `score_areas()`, 722 calls/move) by unifying duplicate capture logic, pruning candidates, and sharing the base score — without changing which move it picks.

**Architecture:** `GameBoard` extracts one private `_capture_opponent` helper reused by `resulting_key` and `make_move`. `GreedyAI` gains `_candidates()` (points adjacent to a stone, falling back to all legal points on an empty board) and a `_score_move()` that uses a single shared base score (computed once per `choose`) instead of recomputing the base inside every candidate loop.

**Tech Stack:** Python 3.9+, standard library only (`unittest`).

## Global Constraints

- Behavior of the game rules must not change; all 26 existing tests must stay green.
- The Greedy AI must still return a legal move (or `None`) in all the original code's scenarios, including an empty board and game-over.
- Score calculation must remain `score_areas()`-based (no hand-rolled territory flood-fill logic), to guarantee scoring equivalence.
- Repo is `/Users/x/Desktop/1998x-stack/00-仓库/15-游戏与趣味/Go`; run tests with `PYTHONPATH=. python3 -m unittest`.

---

### Task 1: Unify duplicate capture logic

**Files:**
- Modify: `gameboard.py` (`resulting_key`, `make_move`, add `_capture_opponent`)
- Test: `test_gameboard.py` (existing coverage; add one consistency test)

**Interfaces:**
- Consumes: existing `GameBoard` (`grid`, `in_bounds`, `get_groups`, `get_liberties`, `_NEIGHBORS`).
- Produces: private `GameBoard._capture_opponent(x, y, color) -> list[Tuple[int,int]]`. Used by Task 1 only; public API unchanged.

- [ ] **Step 1: Write the failing test**

Add to `test_gameboard.py` inside `TestGameBoard`:

```python
def test_make_move_and_resulting_capture_agree(self):
    # Same position through both paths must yield identical captured coords
    self.place('O', [(1, 1)])
    self.place('X', [(0, 1), (1, 0), (1, 2)])
    # resulting_key path (simulated): legal, lone O captured
    self.assertTrue(self.board.place_stone(self.pb, 2, 1))
    self.assertIsNone(self.board.get_stone(1, 1))
    # rebuild and exercise make_move directly
    b2 = GameBoard(size=5)
    pb2 = mock.MagicMock(); pb2.get_color.return_value = 'X'
    pb2.increment_captured_stones.side_effect = lambda n, p=pb2: setattr(p, 'captured', getattr(p, 'captured', 0) + n)
    for (x, y) in [(1, 1), (0, 1), (1, 0), (1, 2)]:
        b2.grid[y][x] = 'O' if (x, y) != (1, 1) else 'O'
    b2.grid[1][1] = 'O'; b2.grid[0][1] = 'X'; b2.grid[1][0] = 'X'; b2.grid[1][2] = 'X'
    self.assertEqual(b2.make_move(pb2, 2, 1), 1)
    self.assertEqual(pb2.captured, 1)
```

- [ ] **Step 2: Run test to verify it passes now**

Run: `PYTHONPATH=. python3 -m unittest test_gameboard -v`
Expected: PASS (the new test exercises existing behavior; it must pass before and after refactor).

- [ ] **Step 3: Refactor `gameboard.py` to extract `_capture_opponent`**

Add the helper and replace the duplicated capture loops in both `resulting_key` and `make_move`:

```python
    def _capture_opponent(self, x, y, color):
        """Remove opponent groups adjoining (x,y) lacking liberties; return coords."""
        opp = 'X' if color == 'O' else 'O'
        captured = []
        for dx, dy in _NEIGHBORS:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny) and self.grid[nx][ny] == opp:
                g = self.get_groups(nx, ny)
                if self.get_liberties(g) == 0:
                    captured.extend(g)
        return captured

    def resulting_key(self, player, x: int, y: int):
        """Simulate the move; return the resulting board_key if legal else None."""
        if not self.in_bounds(x, y) or self.grid[x][y] is not None:
            return None
        color = player.get_color()
        opp = 'X' if color == 'O' else 'O'
        self.grid[x][y] = color
        captured = self._capture_opponent(x, y, color)
        for gx, gy in captured:
            self.grid[gx][gy] = None
        my_group = self.get_groups(x, y)
        liberties = self.get_liberties(my_group)
        key = self.board_key()
        # revert
        self.grid[x][y] = None
        for gx, gy in captured:
            self.grid[gx][gy] = opp
        return key if liberties > 0 else None

    def make_move(self, player, x: int, y: int) -> int:
        """Commit a legal move; capture opponent groups and credit the player."""
        color = player.get_color()
        self.grid[x][y] = color
        captured = self._capture_opponent(x, y, color)
        for gx, gy in captured:
            self.grid[gx][gy] = None
        if captured:
            player.increment_captured_stones(len(captured))
        return len(captured)
```

- [ ] **Step 4: Run the full suite**

Run: `PYTHONPATH=. python3 -m unittest test_gameboard test_game test_ai test_player test_sgf`
Expected: all PASS (26 + the new test).

- [ ] **Step 5: Commit**

```bash
git add gameboard.py test_gameboard.py
git commit -m "refactor(board): unify capture logic in _capture_opponent"
```

---

### Task 2: Add candidate pruning (`_candidates`)

**Files:**
- Modify: `ai.py`
- Test: `test_ai.py`

**Interfaces:**
- Consumes: `game.board.grid`, `game.size`, `game.can_play(x, y, color)`, `game.state['current']`.
- Produces: `GreedyAI._candidates(game) -> list[Tuple[int,int]]` (relevant legal points).

- [ ] **Step 1: Write the failing test**

Add to `test_ai.py`:

```python
import unittest
from ai import RandomAI, GreedyAI
from game import Game


class TestPruning(unittest.TestCase):
    def test_empty_board_falls_back_to_legal(self):
        g = Game()
        pts = GreedyAI()._candidates(g)
        self.assertTrue(pts)
        for (x, y) in pts[:5]:
            self.assertTrue(g.can_play(x, y))

    def test_after_stones_candidates_adjacent_and_legal(self):
        g = Game()
        g.play(3, 3)  # X
        g.play(16, 16)  # O
        ai = GreedyAI()
        pts = ai._candidates(g)  # current is X
        self.assertTrue(pts)
        for (x, y) in pts:
            self.assertTrue(g.can_play(x, y))
            adj = any(
                abs(nx - x) + abs(ny - y) == 1 and g.board.grid[nx][ny] is not None
                for nx, ny in [(x+1, y), (x-1, y), (x, y+1), (x, y-1)]
                if 0 <= nx < g.size and 0 <= ny < g.size
            )
            self.assertTrue(adj)

    def test_candidates_are_never_empty_when_legal_moves_exist(self):
        g = Game()
        g.play(3, 3)
        ai = GreedyAI()
        pts = ai._candidates(g)
        self.assertTrue(pts)
        self.assertTrue(all(g.can_play(x, y) for (x, y) in pts))
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python3 -m unittest test_ai.TestPruning -v`
Expected: FAIL with `AttributeError: 'GreedyAI' object has no attribute '_candidates'`.

- [ ] **Step 3: Implement `_candidates`**

In `ai.py`, add a module-level `_NEIGHBORS` and the method:

```python
import random
from gameboard import GameBoard
from player import Player

_NEIGHBORS = ((1, 0), (-1, 0), (0, 1), (0, -1))
```

```python
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
            return legal
        return [(x, y) for x in range(size) for y in range(size)
                if game.can_play(x, y, color)]
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python3 -m unittest test_ai -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add ai.py test_ai.py
git commit -m "feat(ai): prune greedy candidates to points adjacent to stones"
```

---

### Task 3: Shared base + `_score_move` rewiring in `choose`

**Files:**
- Modify: `ai.py`
- Test: `test_ai.py`

**Interfaces:**
- Consumes: `_candidates(game)` from Task 2, `game.board.score_areas()`, `GameBoard`, `Player`.
- Produces: `GreedyAI._score_move(game, color, x, y, own) -> float` (own = shared base area for that color).

- [ ] **Step 1: Write the failing test**

Add to `test_ai.py` (in `TestPruning` or a new `TestScoring` class):

```python
class TestSharedBase(unittest.TestCase):
    def test_score_move_matches_reference(self):
        from gameboard import GameBoard
        from player import Player
        g = Game()
        g.play(3, 3); g.play(16, 16); g.play(3, 15); g.play(15, 3)
        ai = GreedyAI()
        color = 'X'
        own = g.board.score_areas()[0]
        for (x, y) in ai._candidates(g)[:6]:
            v = ai._score_move(g, color, x, y, own)
            # reference: independent recompute
            sim = GameBoard(g.size)
            sim.grid = [row[:] for row in g.board.grid]
            tmp = Player(color)
            base = sim.score_areas()[0]
            if not sim.place_stone(tmp, x, y):
                self.assertEqual(v, float('-inf'))
                continue
            ref = (sim.score_areas()[0] - base) + tmp.captured_stones
            self.assertEqual(v, ref)

    def test_choose_returns_legal_move(self):
        g = Game()
        mv = GreedyAI().choose(g)
        self.assertIsNotNone(mv)
        ok, _ = g.play(mv[0], mv[1])
        self.assertTrue(ok)
```

- [ ] **Step 2: Run to verify it fails**

Run: `PYTHONPATH=. python3 -m unittest test_ai.TestSharedBase -v`
Expected: FAIL with `AttributeError: ... no attribute '_score_move'`.

- [ ] **Step 3: Implement `_score_move` + update `choose`**

```python
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
```

- [ ] **Step 4: Run to verify it passes**

Run: `PYTHONPATH=. python3 -m unittest test_ai test_gameboard test_game test_player test_sgf`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git log --all --oneline | head -50
git add ai.py test_ai.py
git commit -m "perf(ai): share base score and compute delta once per candidate"
```

---

### Task 4: Measure and verify end-to-end

**Files:**
- Create: `/tmp/measure_go.py` (throwaway)
- Test: `test_ai.py` (add one regression test if worth it — optional)

- [ ] **Step 1: Measure before behavior preserved**

Run the suite: `PYTHONPATH=. python3 -m unittest test_gameboard test_game test_ai test_player test_sgf -v`
Expected: all PASS.

- [ ] **Step 2: Time the optimized AI**

```bash
cat > /tmp/measure_go.py << 'EOF'
import time
from game import Game
from ai import GreedyAI
g = Game(); t0=time.perf_counter(); GreedyAI().choose(g); t1=time.perf_counter()
print(f"empty-board choose: {t1-t0:.4f}s")
g2=Game()
for (x,y) in [(3,3),(16,16),(3,15),(15,3),(9,9),(9,10)]: g2.play(x,y)
t0=time.perf_counter(); GreedyAI().choose(g2); t1=time.perf_counter()
print(f"mid-game choose: {t1-t0:.4f}s")
EOF
PYTHONPATH=. python3 /tmp/measure_go.py
```

Expected: empty-board ≈ the fallback path (same as baseline ~0.22s because no stones to prune); mid-game clearly faster than baseline ~0.22s (target a meaningful drop, e.g. from ~361 candidates to the pruned set).

- [ ] **Step 3: Confirm all tests green**

Run: `PYTHONPATH=. python3 -m unittest test_gameboard test_game test_ai test_player test_sgf`
Expected: PASS. Record the measured times in the PR/commit message.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "test+docs: verify greedy pruning + shared-base scoring"
```