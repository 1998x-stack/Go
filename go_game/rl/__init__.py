"""Optional RL adapters; pure-Python core is always importable."""
from .environment import CoreGoEnv, Transition
from .features import encode_observation

__all__ = ["CoreGoEnv", "Transition", "encode_observation"]
