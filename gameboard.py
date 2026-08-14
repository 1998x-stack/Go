from typing import List, Optional, Tuple

_NEIGHBORS = [(1, 0), (-1, 0), (0, 1), (0, -1)]


class GameBoard:
    """Go board: capture-aware, group-aware legality and Chinese area scoring."""

    def __init__(self, size: int = 19):
        self.size = size
        self.grid = [[None for _ in range(size)] for _ in range(size)]

    # ---- basic access ----
    def in_bounds(self, x: int, y: int) -> bool:
        return 0 <= x < self.size and 0 <= y < self.size

    def get_stone(self, x: int, y: int):
        if self.in_bounds(x, y):
            return self.grid[x][y]
        return None

    def board_key(self):
        return tuple(tuple(row) for row in self.grid)

    # ---- legality ----
    def is_legal(self, player, x: int, y: int) -> bool:
        return self.resulting_key(player, x, y) is not None

    def resulting_key(self, player, x: int, y: int):
        """Simulate the move; return the resulting board_key if legal else None."""
        if not self.in_bounds(x, y) or self.grid[x][y] is not None:
            return None
        color = player.get_color()
        opp = 'X' if color == 'O' else 'O'
        self.grid[x][y] = color
        captured = set()
        for dx, dy in _NEIGHBORS:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny) and self.grid[nx][ny] == opp:
                g = self.get_groups(nx, ny)
                if self.get_liberties(g) == 0:
                    captured.update(g)
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

    def place_stone(self, player, x: int, y: int) -> bool:
        if not self.is_legal(player, x, y):
            return False
        self.make_move(player, x, y)
        return True

    def make_move(self, player, x: int, y: int) -> int:
        """Commit a legal move; capture opponent groups and credit the player."""
        color = player.get_color()
        opp = 'X' if color == 'O' else 'O'
        self.grid[x][y] = color
        captured = []
        for dx, dy in _NEIGHBORS:
            nx, ny = x + dx, y + dy
            if self.in_bounds(nx, ny) and self.grid[nx][ny] == opp:
                g = self.get_groups(nx, ny)
                if self.get_liberties(g) == 0:
                    captured.extend(g)
        for gx, gy in captured:
            self.grid[gx][gy] = None
        if captured:
            player.increment_captured_stones(len(captured))
        return len(captured)

    def make_place(self, player, x: int, y: int) -> None:
        """Place a stone with no capture logic (setup/tests)."""
        self.grid[x][y] = player.get_color()

    # ---- groups / liberties ----
    def get_groups(self, x: int, y: int) -> List[Tuple[int, int]]:
        color = self.grid[x][y]
        if color is None:
            return []
        group, visited, stack = [], set(), [(x, y)]
        while stack:
            cx, cy = stack.pop()
            if (cx, cy) in visited:
                continue
            visited.add((cx, cy))
            group.append((cx, cy))
            for dx, dy in _NEIGHBORS:
                nx, ny = cx + dx, cy + dy
                if self.in_bounds(nx, ny) and self.grid[nx][ny] == color:
                    stack.append((nx, ny))
        return group

    def find_groups(self, color: str):
        seen, groups = set(), []
        for x in range(self.size):
            for y in range(self.size):
                if self.grid[x][y] == color and (x, y) not in seen:
                    g = self.get_groups(x, y)
                    groups.append(g)
                    seen.update(g)
        return groups

    def get_liberties(self, group) -> int:
        libs = set()
        for x, y in group:
            for dx, dy in _NEIGHBORS:
                nx, ny = x + dx, y + dy
                if self.in_bounds(nx, ny) and self.grid[nx][ny] is None:
                    libs.add((nx, ny))
        return len(libs)

    # ---- scoring ----
    def count_stones(self, color: str) -> int:
        return sum(1 for row in self.grid for c in row if c == color)

    def score_areas(self):
        """Chinese area scoring: stones + enclosed empty points. Komi excluded."""
        black_points = self.count_stones('X')
        white_points = self.count_stones('O')
        visited_empty = set()
        for x in range(self.size):
            for y in range(self.size):
                if self.grid[x][y] is not None or (x, y) in visited_empty:
                    continue
                region, stack = [], [(x, y)]
                visited_empty.add((x, y))
                borders = set()
                while stack:
                    cx, cy = stack.pop()
                    region.append((cx, cy))
                    for dx, dy in _NEIGHBORS:
                        nx, ny = cx + dx, cy + dy
                        if not self.in_bounds(nx, ny):
                            continue
                        cell = self.grid[nx][ny]
                        if cell is None:
                            if (nx, ny) not in visited_empty:
                                visited_empty.add((nx, ny))
                                stack.append((nx, ny))
                        else:
                            borders.add(cell)
                if borders == {'X'}:
                    black_points += len(region)
                elif borders == {'O'}:
                    white_points += len(region)
        return black_points, white_points