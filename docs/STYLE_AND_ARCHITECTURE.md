# Code style, architecture, and logging

## Goals and migration status

The game is a small Python project, not a service. Prefer clear modules and
stdlib infrastructure over a dependency-injection framework, an ORM, or a
custom event bus. The current refactor moves pygame presentation and application
lifecycle into `go_game/`; the headless core (`game.py`, `gameboard.py`, `ai.py`,
`sgf.py`, `player.py`, `constants.py`) deliberately remains at the repository
root **for now**. Existing imports and the `python main.py` / pygbag entry point
continue to work. Avoid describing a future package layout as already migrated.

## Actual layout after this change

```
main.py                       # thin pygbag + desktop entry point
go_game/
  app.py                      # pygame application loop, lifecycle and event logging
  ui/{events,renderer,sound}.py # pygame-only display/input/audio
  observability/logging.py    # stdlib JSON/text logger, console and desktop rotation
{game,gameboard,player,ai,sgf,constants}.py  # unchanged headless domain modules
{renderer,event_handler,sound}.py           # compatibility import shims
tests/test_logging.py         # headless logging regression tests
pyproject.toml                # minimum Ruff and pytest configuration
```

## Dependency rules

* The headless rules engine must not import pygame, application logging setup,
  the renderer, UI events, or the file system.
* The presentation layer may depend on rules, but gameplay decisions must not
  depend on presentation or logging.
* Configure `go_game` logging only in the application entry point; never modify
  the root logger and never configure logging during import.
* Keep the old root-level UI re-exports until callers have migrated. New UI
  imports should use `go_game.ui.*`.
* Prefer simple functions and direct Python types over frameworks or global
  registries for a small single-player application.

## Conventions

* Python 3.9+ syntax; 4-space indentation; `snake_case` functions and modules,
  `PascalCase` classes and `UPPER_SNAKE_CASE` constants. Ruff settings live in
  `pyproject.toml`. Existing domain behavior is intentionally not reformatted
  in this change to keep diffs reviewable.
* Keep UI handlers small; each event action should report success/failure rather
  than swallowing unexpected errors. Use `logger.exception` at application
  boundaries for unexpected failures, not for normal illegal moves.
* Annotate public APIs and new data models as they are introduced, without
  forcing an immediate rewrite of the legacy domain layer.
* Keep SGF input content and user paths out of logs. Never log entire game
  boards or candidate AI moves at INFO level.

## Logging contract

The only configured logger is `go_game`, with child loggers such as
`go_game.app` and `go_game.ui.sound`. Default output is text to stderr. Set:

```
GO_LOG_LEVEL=DEBUG GO_LOG_FORMAT=json GO_LOG_FILE=game.log python main.py
```

* `GO_LOG_LEVEL`: DEBUG, INFO (default), WARNING, ERROR or CRITICAL.
* `GO_LOG_FORMAT`: `text` (default) or `json`.
* `GO_LOG_FILE`: optional desktop file with 5 MiB rotation and 3 backups;
  omitted by default. Browser builds log to console only. If the directory is
  unavailable, logging falls back to the console without aborting the game.
* JSON log fields: `timestamp` (UTC), `level`, `logger`, `message`, and a small
  allowlist of optional `event`, `game_id`, `turn`, `move`, `captures`, `reason`.
  Exception stacks are included only for explicit exception logging.
* Reconfiguring the application logger replaces only its own handlers; the
  process root logger and third-party logging remain untouched.
* Structured events include game start/stop, user or AI moves/pass, undo,
  load/save failures and audio initialization failures. Do not log every render
  frame or AI candidate evaluation.

## Validation and follow-up

Run `python -m unittest discover -p 'test_*.py' -v`,
`python -m unittest discover -s tests -p 'test_*.py' -v`, and
`ruff check go_game main.py tests/test_logging.py renderer.py event_handler.py sound.py`.
CI runs the headless tests and compilation under Python 3.9/3.11/3.13.

Next migrations should be separate PRs: (1) move the rules and SGF modules to a
headless `go_game/core`, `go_game/ai`, and `go_game/io`, with temporary root
re-exports; (2) model game state explicitly and add types; (3) test the pygame
interaction loop and verify a pygbag browser build on a clean environment.
Do not change rules/AI strategy while performing mechanical package moves.
