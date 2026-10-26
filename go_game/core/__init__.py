"""Headless, versioned Go rules API. No UI or RL dependencies."""
from .specs import RuleSpec
from .engine import GoState, MoveResult, RulesEngine, ScoreReport, UndoToken

__all__ = ["RuleSpec", "GoState", "MoveResult", "RulesEngine", "ScoreReport", "UndoToken"]
