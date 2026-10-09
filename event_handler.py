"""Backward-compatible input mapping; prefer go_game.ui.events."""

from go_game.ui.events import click_to_point, handle_key

__all__ = ["click_to_point", "handle_key"]
