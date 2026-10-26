"""Synchronous bounded search analysis pinned to an authoritative game revision."""
import hashlib
import time
from dataclasses import asdict

from go_game.training.search import SearchConfig, UniformPredictor, search
from go_game.training.dataset import canonical_bytes

from .errors import PlatformError


class AnalysisService:
    def __init__(self, games, registry=None):
        self.games = games
        self.registry = registry

    def _predictor(self, model_id):
        if model_id == "uniform-baseline-v1":
            return UniformPredictor()
        if self.registry is None:
            raise PlatformError("model_not_found", "No model registry configured", 404)
        current = self.registry.current()
        if current is None or current["model_id"] != model_id:
            raise PlatformError("model_not_found", "Not a registered champion", 404)
        # Trusted local registry: manifest digest + actual tensor weights verified
        # prior to loading. Never accept arbitrary checkpoint paths from request.
        from go_game.training.registry import verify_checkpoint
        from go_game.training.learner import Learner
        from go_game.training.network import TorchPredictor

        verify_checkpoint(current["manifest"], current["checkpoint"])
        model = Learner.load(current["checkpoint"], device="cpu").model
        predictor = TorchPredictor(model)
        if predictor.model_id != model_id:
            raise PlatformError("model_mismatch", "Registry weights do not match", 500)
        return predictor

    def analyze(self, game_id, expected_seq, model_id=None, simulations=8):
        if type(expected_seq) is not int or expected_seq < 0:
            raise PlatformError("invalid_seq", "Sequence must be a positive integer", 422)
        if type(simulations) is not int or not 1 <= simulations <= 32:
            raise PlatformError("invalid_budget", "Analysis simulations must be 1..32", 422)
        snap, state = self.games.snapshot_and_state(game_id)
        if snap["seq"] != expected_seq:
            raise PlatformError("stale_sequence", "Position advanced", 409,
                                current_seq=snap["seq"])
        if snap["terminated"]:
            raise PlatformError("game_terminated", "Cannot analyze terminal state", 409)
        pinned = snap["model_id"]
        if model_id is not None and model_id != pinned:
            raise PlatformError("model_mismatch", "Game model identity is pinned", 409)
        if state.rules.board_size > 9 and simulations > 8:
            raise PlatformError("invalid_budget", "Large-board analysis is capped", 422)
        predictor = self._predictor(pinned)
        config = SearchConfig(simulations=simulations, dirichlet_fraction=0)
        start = time.perf_counter()
        result = search(state, predictor, config, temperature=0, explore=False)
        duration = (time.perf_counter() - start) * 1000
        latest = self.games.snapshot(game_id)
        if latest["seq"] != snap["seq"] or latest["state_hash"] != snap["state_hash"]:
            raise PlatformError("stale_analysis", "State changed during search", 409,
                                current_seq=latest["seq"])
        search_config_id = "sha256:" + hashlib.sha256(
            canonical_bytes(asdict(config))).hexdigest()
        return {
            "schema": "analysis-result-v1", "game_id": game_id,
            "source_seq": snap["seq"], "state_hash": snap["state_hash"],
            "rule_id": state.rules.rule_id, "model_id": pinned,
            "search_config_id": search_config_id, "visits": list(result.visits),
            "policy": list(result.policy), "root_value_current_to_play": result.root_value,
            "principal_action": result.action, "simulation_count": simulations,
            "latency_ms": round(duration, 3), "status": "completed",
        }
