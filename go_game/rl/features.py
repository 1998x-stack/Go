"""Versioned current-player perspective observations and legal action masks."""
from dataclasses import dataclass


OBS_SPEC = "obs-history4-v1"
HISTORY_FRAMES = 4
CHANNELS = 5 + 2 * HISTORY_FRAMES


@dataclass(frozen=True)
class Observation:
    planes: tuple
    action_mask: tuple
    to_play: str
    perspective: str
    state_fingerprint: str
    observation_spec_id: str = OBS_SPEC


def encode_observation(state, engine, perspective=None):
    """Returns pure Python immutable planes in [channel][row][col] order.

    Current stones, opponent stones, last non-pass coordinate of the *last*
    action, black-to-play flag, signed normalized komi, then 4 historic
    board snapshots, most recent first, in the same perspective.
    """
    perspective = perspective or state.current_player
    if perspective not in ("X", "O"):
        raise ValueError("Unknown observation perspective")
    board = state.board
    n = state.rules.board_size
    opposite = "O" if perspective == "X" else "X"

    def stone_plane(snapshot, color):
        return tuple(tuple(1.0 if cell == color else 0.0 for cell in row)
                     for row in snapshot)

    def constant(value):
        return tuple(tuple(float(value) for _ in range(n)) for _ in range(n))

    last = state.actions[-1] if state.actions else n * n
    last_move = tuple(tuple(float(last == row * n + col)
                            for col in range(n)) for row in range(n))
    komi = state.rules.komi_half_points / (2.0 * n * n)
    if perspective == "X":
        komi = -komi
    planes = [
        stone_plane(board, perspective),
        stone_plane(board, opposite),
        last_move,
        constant(state.current_player == "X"),
        constant(komi),
    ]
    history = state.history_boards(HISTORY_FRAMES)
    for snapshot in reversed(history):
        planes.extend((stone_plane(snapshot, perspective),
                       stone_plane(snapshot, opposite)))
    while len(planes) < CHANNELS:
        planes.extend((constant(0), constant(0)))
    mask = engine.legal_actions(state) if perspective == state.current_player else (
        False,) * (n * n + 1)
    return Observation(tuple(planes), tuple(mask), state.current_player,
                       perspective, state.fingerprint)


def numpy_observation(observation):
    """Only adapters import NumPy, leaving pure rules usable on minimal installs."""
    import numpy as np
    return {
        "observation": np.asarray(observation.planes, dtype=np.float32),
        "action_mask": np.asarray(observation.action_mask, dtype=np.int8),
    }
