"""Single-host Go AI platform. Optional HTTP layer; core rules remain headless."""
from .games import GameService
from .jobs import JobService
from .storage import PlatformStore

__all__ = ["GameService", "JobService", "PlatformStore"]
