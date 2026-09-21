# Go (囲碁)

A Python implementation of the board game Go with a headless rules engine,
a pygame desktop UI, a browser build (pygbag), and a simple built-in AI.

## Play

Use the repository's GitHub Pages deployment for the browser version, or run
locally with Python 3.9+:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install pygame
python main.py
```

You play Black (`X`), and GreedyAI plays White (`O`). Click an intersection to
place a stone. `P` passes, `U` undoes, `G` ends and scores, `S` saves to
`game.sgf`, `L` loads it, and `Q`/Esc quits. Two consecutive passes end the game.

The game uses Chinese area scoring with a configurable komi, position-history
superko on placements, and fixed handicap stones on the 19×19 board. Its SGF
reader/writer supports a deliberately limited *linear* record subset; it is not
a full SGF FF[4] parser or a professional dead-stone adjudicator.

## Code organization

```text
main.py                         Desktop/pygbag entry point

go_game/
  app.py                        Application lifecycle, pygame event loop
  ui/
    events.py                   Keyboard/mouse mapping
    renderer.py                 Board and score rendering
    sound.py                    Optional audio adapter
  observability/
    logging.py                  Console and optional rotating JSON/text logs

game.py                         Headless turn order, history, scoring

gameboard.py                    Headless board, captures, groups, liberties
player.py                       Player model
ai.py                           RandomAI and GreedyAI
sgf.py                          Linear SGF import/export
constants.py                    Game constants
renderer.py, event_handler.py,
sound.py                        Backward-compatible UI imports

test_*.py                       Headless rules and SGF tests
tests/test_logging.py           Headless logging tests
```

New presentation code belongs in `go_game.ui`, and application orchestration in
`go_game.app`. The rules engine stays pygame-free. The remaining root-level
headless modules will migrate in a separate PR with compatibility shims, so
this restructure does not silently alter capture, scoring, or AI behavior.
For conventions and follow-up architecture see
[Style and architecture](docs/STYLE_AND_ARCHITECTURE.md).

## Logging

Default logs use readable text on stderr. Optional controls:

| Environment variable | Values | Default |
|---|---|---|
| `GO_LOG_LEVEL` | `DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL` | `INFO` |
| `GO_LOG_FORMAT` | `text`, `json` | `text` |
| `GO_LOG_FILE` | desktop log file path | disabled |

Example:

```bash
GO_LOG_LEVEL=DEBUG GO_LOG_FORMAT=json GO_LOG_FILE=game.log python main.py
```

Desktop file output rotates at 5 MiB with three backups. Browser builds use
console logging only. Logging is configured for the `go_game` namespace rather
than globally; gameplay events have a game ID, event name and small contextual
fields, never a full SGF record or AI candidate-by-candidate tracing.
Runtime logs and locally saved `game.sgf` are ignored by Git.

## Testing and style

Headless rules and infrastructure tests need only the standard library:

```bash
python -m unittest discover -p 'test_*.py' -v
python -m unittest discover -s tests -p 'test_*.py' -v
python -m compileall -q go_game main.py game.py gameboard.py sgf.py ai.py
```

For linting, install Ruff and run:

```bash
python -m pip install ruff
ruff check go_game main.py tests/test_logging.py renderer.py event_handler.py sound.py
```

CI runs headless tests and compilation under Python 3.9/3.11/3.13 and Ruff
on the refactored package. These checks do **not** replace an actual pygame
UI smoke test or a browser end-to-end test.

## Web build

The root `main.py` stays in place because the GitHub Pages deploy workflow
uses `python -m pygbag main.py`. The browser landing page is in `web/index.html`.
For a local build, install `pygbag` alongside pygame, then run:

```bash
python -m pygbag --build main.py
```
