"""CPU/GPU PyTorch learner with strict replay input and resumable checkpoints."""
import hashlib
import os
import random
import tempfile

import torch
import torch.nn.functional as F

from go_game.rl.features import OBS_SPEC
from .dataset import validate_shard
from .augmentation import transform_sample
from .network import NetworkConfig, PolicyValueNet, model_digest


CHECKPOINT_SCHEMA = "go-checkpoint-v1"


class Learner:
    def __init__(self, model, seed=0, learning_rate=0.001, device="cpu"):
        if learning_rate <= 0:
            raise ValueError("learning_rate must be positive")
        self.device = device
        self.model = model.to(device)
        self.optimizer = torch.optim.AdamW(
            self.model.parameters(), lr=learning_rate, weight_decay=1e-4)
        self.step_number = 0
        self.seed = seed
        self.rng = random.Random(seed)
        self.dataset_digests = []

    def train(self, shards, steps=1, batch_size=8, augment=False):
        if type(steps) is not int or steps < 1 or type(batch_size) is not int or batch_size < 1:
            raise ValueError("Positive integer steps and batch_size required")
        samples = []
        digests = []
        rules = None
        for shard in shards:
            validate_shard(shard)
            if "digest" not in shard:
                raise ValueError("Training requires a content-addressed shard")
            current = shard["record"]["rules"]
            if rules is not None and current != rules:
                raise ValueError("Mixed rule configurations need explicit dataset stratification")
            rules = current
            if current["board_size"] != self.model.config.board_size:
                raise ValueError("Dataset board size differs from network")
            samples.extend(shard["examples"])
            digests.append(shard["digest"])
        if not samples:
            raise ValueError("Refusing to train on an empty/incomplete dataset")
        self.dataset_digests = sorted(set(self.dataset_digests + digests))
        self.model.train()
        metrics = []
        for _ in range(steps):
            sampled = self.rng.choices(samples, k=batch_size)
            if augment:
                n = self.model.config.board_size
                sampled = [transform_sample(
                    s, n, self.rng.randrange(4), bool(self.rng.getrandbits(1)))
                    for s in sampled]
            x = torch.tensor([s["planes"] for s in sampled],
                             dtype=torch.float32, device=self.device)
            pi = torch.tensor([s["pi"] for s in sampled],
                              dtype=torch.float32, device=self.device)
            mask = torch.tensor([s["mask"] for s in sampled],
                                dtype=torch.bool, device=self.device)
            z = torch.tensor([s["z"] for s in sampled],
                             dtype=torch.float32, device=self.device)
            if not bool(mask.any(dim=1).all()):
                raise ValueError("Invalid policy mask in training batch")
            logits, values = self.model(x)
            masked = logits.masked_fill(~mask, torch.finfo(logits.dtype).min)
            loss_policy = -(pi * F.log_softmax(masked, dim=1)).sum(dim=1).mean()
            loss_value = F.mse_loss(values, z)
            loss = loss_policy + loss_value
            if not bool(torch.isfinite(loss)):
                raise ValueError("Nonfinite training loss; checkpoint not advanced")
            self.optimizer.zero_grad(set_to_none=True)
            loss.backward()
            torch.nn.utils.clip_grad_norm_(self.model.parameters(), 5.0,
                                           error_if_nonfinite=True)
            self.optimizer.step()
            self.step_number += 1
            metrics.append({
                "step": self.step_number,
                "loss": float(loss.detach().cpu()),
                "policy_loss": float(loss_policy.detach().cpu()),
                "value_loss": float(loss_value.detach().cpu()),
            })
        return metrics

    def checkpoint(self):
        return {
            "schema": CHECKPOINT_SCHEMA,
            "architecture": self.model.config.to_dict(),
            "observation_spec_id": OBS_SPEC,
            "state_dict": self.model.state_dict(),
            "optimizer": self.optimizer.state_dict(),
            "step": self.step_number,
            "seed": self.seed,
            "python_rng_state": self.rng.getstate(),
            "torch_rng_state": torch.get_rng_state(),
            "cuda_rng_states": torch.cuda.get_rng_state_all() if torch.cuda.is_available() else [],
            "dataset_digests": self.dataset_digests,
            "model_id": model_digest(self.model),
        }

    def save(self, path):
        path = os.path.abspath(os.fspath(path))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix="checkpoint-", suffix=".pt",
                                    dir=os.path.dirname(path))
        os.close(fd)
        try:
            torch.save(self.checkpoint(), temp)
            with open(temp, "rb") as stream:
                os.fsync(stream.fileno())
            os.replace(temp, path)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        with open(path, "rb") as stream:
            digest = hashlib.sha256(stream.read()).hexdigest()
        return {"schema": "model-manifest-v1",
                "model_id": model_digest(self.model),
                "checkpoint_sha256": "sha256:" + digest,
                "architecture": self.model.config.to_dict(),
                "observation_spec_id": OBS_SPEC,
                "dataset_digests": list(self.dataset_digests),
                "training_step": self.step_number}

    @classmethod
    def load(cls, path, device="cpu"):
        # Only load trusted local checkpoints, using weights_only safeguards.
        payload = torch.load(path, map_location=device, weights_only=True)
        if payload.get("schema") != CHECKPOINT_SCHEMA:
            raise ValueError("Unsupported checkpoint schema")
        arch = payload["architecture"]
        if (arch.get("architecture_id") != "pv-resnet-small-v1"
                or arch.get("observation_spec_id") != OBS_SPEC):
            raise ValueError("Checkpoint architecture/feature mismatch")
        config = NetworkConfig(board_size=arch["board_size"],
                               channels=arch["channels"], blocks=arch["blocks"])
        learner = cls(PolicyValueNet(config), seed=payload["seed"], device=device)
        learner.model.load_state_dict(payload["state_dict"], strict=True)
        if model_digest(learner.model) != payload["model_id"]:
            raise ValueError("Checkpoint model checksum mismatch")
        learner.optimizer.load_state_dict(payload["optimizer"])
        learner.step_number = payload["step"]
        learner.dataset_digests = list(payload["dataset_digests"])
        learner.rng.setstate(payload["python_rng_state"])
        torch.set_rng_state(payload["torch_rng_state"])
        if torch.cuda.is_available() and payload["cuda_rng_states"]:
            torch.cuda.set_rng_state_all(payload["cuda_rng_states"])
        return learner
