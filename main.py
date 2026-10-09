"""Entry point for desktop Python and pygbag web builds.

Keep this file at the repository root: the existing deployment runs
``python -m pygbag main.py``. Application logic lives in go_game.app.
"""

import asyncio

from go_game.app import main


if __name__ == "__main__":
    asyncio.run(main())
