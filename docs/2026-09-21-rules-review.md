# Rules-engine review and follow-up plan (2026-09-21)

## Scope and implementation

The project is a Python Go game, not a Go-language codebase. The headless core is in `gameboard.py`, `game.py`, `ai.py`, and `sgf.py`; the pygame client is in `main.py`. This change deliberately limits behavioral modifications to rules, game-state recovery, and the supported SGF record subset.

| Priority | Finding | Resolution |
| --- | --- | --- |
| P0 | A connected opponent group touching a move from multiple directions is captured more than once in the reported prisoner count. | Remember visited group coordinates before accumulating captures. |
| P0 | Undo replays from an empty board and retains stale prisoner/pass/score state. | Replay from an immutable initial setup snapshot and recompute derived state. |
| P0 | SGF save/load loses passes, handicap placements, and board size, and ignores invalid moves. | Export linear SGF nodes, preserve `SZ/KM/HA/AB`, and reject invalid moves rather than skipping them. |
| P1 | Positional-superko history omits the initial setup board; `can_play()` still advertises moves after scoring. | Include the initial position in `_seen`, rebuild the set on undo, and reject play after the game ends. |
| P1 | A rules regression could be merged without any automated tests. | Add a standard-library `unittest` job on pull requests and `main` pushes. |

## Rules contract

* The engine rejects suicide and uses **positional superko for stone placements**. A pass is legal without a board-position check, and two successive passes end the game.
* The scorer counts stones plus empty regions bordered by only one color and adds komi to White. It **does not automatically identify and remove dead stones** or resolve disputed life-and-death positions. Players should finish captures before passing; this is not a tournament adjudicator.
* The SGF reader/writer supports a **single linear game** with `SZ`, `KM`, fixed 19x19 `HA`/`AB`, and `;B[xy]`, `;W[xy]`, `;B[]`, `;W[]` nodes. It is **not a full SGF parser**: variations, markup, arbitrary setup edits, and escaped property values are outside scope. Unsupported move nodes raise `ValueError`.
* `setup()` resets an unstarted game only. Fixed handicap is restricted to a 19x19 board in this implementation.

## Verification

Run `python -m unittest discover -p 'test_*.py' -v` and `python -m compileall -q game.py gameboard.py sgf.py ai.py test_*.py` from the repository root. The CI workflow runs the same checks for Python 3.9, 3.11 and 3.13. The new 15-case regression suite was locally exercised against a recreated headless core; GitHub CI is the authoritative repository-wide integration check.

## Next stages (not included in this change)

1. **Full SGF interoperability:** adopt a tested parser to support variations, comments, escapes, standard handicap layouts, and property preservation. Add fixture-based round-trip tests from independent SGF generators.
2. **Rule presets and adjudication:** clearly separate Chinese area scoring, ko variants, suicide rules, komi, and optional dead-stone agreement. Test each preset with published rule examples before exposing it in the UI.
3. **AI and performance:** add an explicit pass decision, tactical capture/atari heuristics, cached legality evaluation, and deterministic benchmark positions. Profile on 9x9 and 19x19 before changing move ranking; the current `GreedyAI` is not a competitive Go engine.
4. **Client lifecycle:** test save/load/undo around an AI turn, verify sound failures cannot interrupt the loop, and run pygame/pygbag smoke tests with a headless display in CI.
5. **Release gate:** require the test workflow to pass before merging and verify the Pages build and desktop interactions after changes to the UI layer.
