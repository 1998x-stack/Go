# Go (囲碁)

A complete, correct implementation of the classic board game **Go** in Python with
a pygame desktop client and a playable in-browser build, powered by a proper Go rules
engine.

[![GitHub Pages](https://img.shields.io/badge/Play%20Online-GitHub%20Pages-blue)](#play-online)

---

## Overview

Go — played on a 19×19 grid — is a territory-capture game of remarkable depth. This
project delivers a faithful rules engine plus a friendly interface, so you can enjoy
a real game against a built-in AI, on your desktop or right in the browser.

The rules engine is deliberately **pygame-free and headless-testable**, so every Go
rule is verified by an automated unit test suite.

---

## Features

- ✅ **Correct Go rules** — capture-aware *and* group-aware suicide legality, and the **Ko rule** via position-history, so no illegal moves slip through.
- 🧮 **Chinese (area) scoring** with komi (6.5; 0 for handicap games).
- 🤖 **Two AI players** — `Random` (casual) and `Greedy` (territory- and capture-seeking).
- ↪️ **Undo** for taking back moves.
- 📅 **Handicap stones** at the nine star points.
- 🧷 **SGF save / load** — export and replay game records.
- 🔊 Optional sound, with a defensive wrapper that never crashes the game.
- 🖱️ **Pygame desktop client** and **playable web build** (pygbag).

---

## 🚀 Getting Started

### Play online (no install)

Deployed automatically to GitHub Pages on every push to `main` — open the
**Play Online** badge above or visit the repo's Pages URL.

### Run on desktop

Requires **Python 3.9+** and [pygame](https://www.pygame.org/wiki/GettingStarted):

```bash
# 1. Create and use a virtual environment (recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2. Install pygame
pip install pygame

# 3. Run
python main.py
```

You (Black) play first; the Greedy AI (White) responds automatically.

---

## How to Play — Controls

| Action            | Control                        |
|-------------------|--------------------------------|
| Place a stone     | Click an intersection (Black)  |
| Pass              | `P`                            |
| Undo              | `U`                            |
| End & score       | `G`                            |
| Save SGF          | `S` (writes `game.sgf`)        |
| Load SGF          | `L` (reads `game.sgf`)         |
| Quit              | `Q` / `Esc` / close window     |

The game ends after **two consecutive passes**; the score overlay then shows the
Chinese-area result with komi included.

---

## 🏗️ Architecture

The project cleanly separates a headless rules core from the presentation layers.

```
gameboard.py       Rules engine: legality, capture, groups, liberties, area scoring
game.py            Game orchestrator: turn order, Ko, undo, handicap, scoring
player.py          Player (color, captures, is_human)
ai.py              AI strategies: RandomAI, GreedyAI
sgf.py             Minimal SGF reader/writer
renderer.py        pygame board/stone/panel rendering
event_handler.py   input -> actions (clicks + keys)
main.py            pygame main loop (asyncio-compatible for desktop & web)
sound.py           defensive audio wrapper
constants.py       shared constants
test_*.py          headless unit tests (run with: python3 -m pytest)
```

The **rules core** (`gameboard.py`, `game.py`, `ai.py`, `sgf.py`, `player.py`) never
imports `pygame`, so it can be tested headlessly with the standard library.

---

## The Game in 60 Seconds (for newcomers)

- Two players place **stones** of their color on the intersections of a 19×19 grid.
- Stones connect horizontally/vertically into **groups**; a group is captured when it
  has **no liberties** (no adjacent empty points).
- You may not play a move that leaves your own group with no liberties (suicide) —
  unless that move captures opponent stones.
- **Ko** prevents an immediate re-capture that would repeat a previous position.
- The game ends when both players pass consecutively; territory + komi decides the winner.

---

## Testing

All Go-rule logic is covered by a headless test suite:

```bash
python3 -m pytest test_*.py -v
```

Coverage includes legal/illegal moves, group-aware suicide, capture-aware moves,
Ko enforcement, Chinese-area scoring, handicap, undo, AI legality, and SGF round-trips.

---

## Building the Web Version

The in-browser build is generated with [pygbag](https://pygbag.github.io/), normally
in CI (GitHub Actions → GitHub Pages):

```bash
pip install pygame pygbag
python -m pygbag --build main.py   # outputs build/web
```

---

## Tech Stack

**Python ≥ 3.9** · **pygame 2.x** · **pygbag** (web build) · **GitHub Actions**
(deploy) · **pytest** (tests)

## License

This project is provided for educational purposes. See the repository for details.