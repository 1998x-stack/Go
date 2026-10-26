"""Small board-size-specific ResNet policy/value network and batched predictor.

Optional PyTorch dependency; no Torch import in headless Rules/Env modules.
"""
import hashlib
import json
from dataclasses import asdict, dataclass

import torch
from torch import nn

from go_game.rl.features import CHANNELS, OBS_SPEC, encode_observation
from go_game.core import RulesEngine


@dataclass(frozen=True)
class NetworkConfig:
    board_size: int
    channels: int = 32
    blocks: int = 2

    def __post_init__(self):
        if (type(self.board_size) is not int or not 2 <= self.board_size <= 26
                or type(self.channels) is not int or self.channels < 4
                or type(self.blocks) is not int or not 0 <= self.blocks <= 20):
            raise ValueError("Invalid network architecture")

    def to_dict(self):
        return dict(asdict(self), architecture_id="pv-resnet-small-v1",
                    observation_spec_id=OBS_SPEC)


class ResidualBlock(nn.Module):
    def __init__(self, channels):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
            nn.ReLU(),
            nn.Conv2d(channels, channels, 3, padding=1, bias=False),
        )
        self.activation = nn.ReLU()

    def forward(self, x):
        return self.activation(x + self.layers(x))


class PolicyValueNet(nn.Module):
    """Policy logits of N*N+1 (last Pass) and actor-perspective tanh value."""

    def __init__(self, config):
        super().__init__()
        self.config = config
        self.stem = nn.Sequential(
            nn.Conv2d(CHANNELS, config.channels, 3, padding=1),
            nn.ReLU(),
        )
        self.residual = nn.Sequential(
            *(ResidualBlock(config.channels) for _ in range(config.blocks)))
        self.policy_conv = nn.Conv2d(config.channels, 1, 1)
        self.pass_head = nn.Linear(config.channels, 1)
        self.value_head = nn.Sequential(
            nn.Linear(config.channels, config.channels),
            nn.ReLU(),
            nn.Linear(config.channels, 1),
            nn.Tanh(),
        )

    def forward(self, boards):
        if boards.ndim != 4 or boards.shape[1] != CHANNELS or (
                tuple(boards.shape[2:]) != (self.config.board_size,) * 2):
            raise ValueError("Incompatible observation tensor dimensions")
        trunk = self.residual(self.stem(boards))
        pooled = trunk.mean(dim=(2, 3))
        policy = torch.cat(
            (self.policy_conv(trunk).flatten(1), self.pass_head(pooled)), dim=1)
        return policy, self.value_head(pooled).squeeze(-1)


def model_digest(model):
    """Content hash across sorted parameter tensors AND architecture/observation spec."""
    digest = hashlib.sha256(json.dumps(
        model.config.to_dict(), sort_keys=True).encode("utf-8"))
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        contiguous = tensor.detach().cpu().contiguous()
        digest.update(contiguous.numpy().tobytes())
    return "sha256:" + digest.hexdigest()


class TorchPredictor:
    def __init__(self, model, device="cpu"):
        self.model = model.to(device)
        self.device = device
        self.model.eval()
        self.model_id = model_digest(self.model)
        self.engine = RulesEngine()

    def predict_batch(self, states):
        if not states:
            return []
        size = self.model.config.board_size
        for state in states:
            if state.terminated or state.rules.board_size != size:
                raise ValueError("Terminal state or incompatible board size")
        observations = [encode_observation(state, self.engine) for state in states]
        board_tensor = torch.tensor(
            [obs.planes for obs in observations], dtype=torch.float32,
            device=self.device)
        with torch.no_grad():
            logits, values = self.model(board_tensor)
        return [(row, float(v)) for row, v in
                zip(logits.detach().cpu().tolist(), values.detach().cpu().tolist())]

    def predict(self, state):
        return self.predict_batch([state])[0]

    def refresh_model_id(self):
        self.model.eval()
        self.model_id = model_digest(self.model)
        return self.model_id
