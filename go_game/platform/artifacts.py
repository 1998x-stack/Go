"""Verified immutable local artifacts. No arbitrary user-defined filesystem paths."""
import hashlib
import os
import re
import tempfile

from .errors import PlatformError
from .storage import encode


_HEX = re.compile(r"^sha256:([0-9a-f]{64})$")


class ArtifactStore:
    def __init__(self, root, max_bytes=64 * 1024 * 1024):
        self.root = os.path.abspath(os.fspath(root))
        self.max_bytes = max_bytes
        os.makedirs(self.root, exist_ok=True)

    def put(self, payload):
        if not isinstance(payload, bytes) or len(payload) > self.max_bytes:
            raise PlatformError("invalid_artifact", "Expected bounded artifact bytes", 422)
        digest = "sha256:" + hashlib.sha256(payload).hexdigest()
        dest = self._path(digest)
        fd, name = tempfile.mkstemp(prefix="stage-", dir=self.root)
        try:
            with os.fdopen(fd, "wb") as fp:
                fp.write(payload)
                fp.flush()
                os.fsync(fp.fileno())
            # os.link refuses to overwrite an existing hash object. No half-files
            # become visible even under concurrent writers.
            try:
                os.link(name, dest)
            except FileExistsError:
                if self.get(digest) != payload:
                    raise PlatformError("artifact_collision", "Existing content differs", 500)
        finally:
            if os.path.exists(name):
                os.unlink(name)
        return digest

    def put_json(self, value):
        try:
            payload = encode(value).encode("ascii")
        except (TypeError, ValueError) as exc:
            raise PlatformError("invalid_artifact", "Not serializable JSON", 422) from exc
        return self.put(payload)

    def _path(self, digest):
        if not isinstance(digest, str) or not _HEX.fullmatch(digest):
            raise PlatformError("invalid_artifact", "Invalid SHA256 digest", 422)
        return os.path.join(self.root, digest.split(":")[1])

    def get(self, digest):
        name = self._path(digest)
        try:
            with open(name, "rb") as fp:
                raw = fp.read(self.max_bytes + 1)
        except FileNotFoundError as exc:
            raise PlatformError("artifact_not_found", "Unknown artifact", 404) from exc
        if (len(raw) > self.max_bytes
                or "sha256:" + hashlib.sha256(raw).hexdigest() != digest):
            raise PlatformError("artifact_integrity", "Artifact failed content verification", 500)
        return raw
