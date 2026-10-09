"""Go game application package.

The headless rules modules remain importable at the repository root during the
incremental migration, so existing scripts and tests keep working.
"""

__all__ = ["app", "observability"]
