"""Single-writer local model registry: champion updates require an Arena gate."""
import hashlib
import json
import os
import tempfile

from .arena import promotion_decision
from .dataset import canonical_bytes


def _atomic_json(path, value):
    folder = os.path.dirname(os.path.abspath(path))
    os.makedirs(folder, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".registry-", dir=folder)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(canonical_bytes(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def verify_checkpoint(manifest, checkpoint_path):
    if manifest.get("schema") != "model-manifest-v1":
        raise ValueError("Unsupported model manifest")
    with open(checkpoint_path, "rb") as stream:
        sha = hashlib.sha256(stream.read()).hexdigest()
    if manifest.get("checkpoint_sha256") != "sha256:" + sha:
        raise ValueError("Checkpoint bytes differ from model manifest")
    if not manifest.get("model_id") or not manifest.get("dataset_digests"):
        raise ValueError("Missing lineage in model manifest")
    # File checksum alone does not prove manifest-to-weights identity. Verify
    # the model tensors and frozen action/observation/reward rule contracts.
    import torch
    from .network import NetworkConfig, PolicyValueNet, model_digest

    payload = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    arch = payload.get("architecture", {})
    if (manifest.get("architecture") != arch
            or manifest.get("observation_spec_id") != payload.get("observation_spec_id")
            or manifest.get("training_rules") != payload.get("training_rules")
            or manifest.get("dataset_digests") != payload.get("dataset_digests")
            or manifest.get("action_spec_id") != payload.get("action_spec_id")
            or manifest.get("reward_spec_id") != payload.get("reward_spec_id")
            or manifest["model_id"] != payload.get("model_id")):
        raise ValueError("Manifest / checkpoint contract mismatch")
    model = PolicyValueNet(NetworkConfig(
        board_size=arch["board_size"], channels=arch["channels"],
        blocks=arch["blocks"]))
    model.load_state_dict(payload["state_dict"], strict=True)
    if model_digest(model) != manifest["model_id"]:
        raise ValueError("Model weights do not match manifest ID")
    return True


class LocalRegistry:
    """Atomic local pointer, not a multi-host CAS service (deferred to Plan C)."""

    def __init__(self, path):
        self.path = os.path.abspath(os.fspath(path))

    def current(self):
        if not os.path.exists(self.path):
            return None
        with open(self.path, encoding="utf-8") as stream:
            value = json.load(stream)
        if value.get("schema") != "champion-pointer-v1":
            raise ValueError("Unsupported registry schema")
        return value

    def bootstrap(self, manifest, checkpoint_path):
        if self.current() is not None:
            raise ValueError("Registry already bootstrapped")
        verify_checkpoint(manifest, checkpoint_path)
        item = {"schema": "champion-pointer-v1",
                "model_id": manifest["model_id"], "checkpoint": str(checkpoint_path),
                "manifest": manifest, "evidence": "explicit_bootstrap"}
        _atomic_json(self.path, item)
        return item

    def promote(self, manifest, checkpoint_path, report, min_completed=20,
                threshold=0.5):
        current = self.current()
        if current is None:
            raise ValueError("Bootstrap first")
        verify_checkpoint(manifest, checkpoint_path)
        if (report.get("candidate_id") != manifest["model_id"]
                or report.get("champion_id") != current["model_id"]
                or report["candidate_id"] == report["champion_id"]):
            raise ValueError("Arena not paired with current champion and candidate")
        decision = promotion_decision(report, min_completed, threshold)
        if decision != "promote":
            return {"decision": decision, "champion_id": current["model_id"]}
        item = {"schema": "champion-pointer-v1",
                "model_id": manifest["model_id"], "checkpoint": str(checkpoint_path),
                "manifest": manifest, "evidence": report}
        _atomic_json(self.path, item)
        return {"decision": "promote", "champion_id": manifest["model_id"]}
