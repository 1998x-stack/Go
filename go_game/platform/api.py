"""Optional authenticated FastAPI HTTP + resumable Server Sent Events."""
import asyncio
import json
import os
import secrets

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, StrictInt

from go_game.core import RuleSpec
from go_game.training.registry import LocalRegistry

from .analysis import AnalysisService, ModelCatalog
from .artifacts import ArtifactStore
from .errors import PlatformError
from .games import GameService
from .jobs import JobService
from .storage import PlatformStore, encode
from .web import HTML_PAGE


class StrictBody(BaseModel):
    class Config:
        extra = "forbid"


class CreateGame(StrictBody):
    rules: dict
    black_actor: str
    white_actor: str
    model_id: str = "uniform-baseline-v1"


class SubmitMove(StrictBody):
    command_id: str
    expected_seq: StrictInt
    actor_id: str
    action: dict


class Analyze(StrictBody):
    expected_seq: StrictInt
    simulations: StrictInt = 8
    model_id: str = None


class SubmitJob(StrictBody):
    request_key: str
    kind: str
    spec: dict


class LeaseRequest(StrictBody):
    worker_id: str
    lease_seconds: StrictInt = 30


class FinishJob(StrictBody):
    worker_id: str
    attempt: StrictInt
    digest: str = None
    failed: bool = False


class Heartbeat(StrictBody):
    worker_id: str
    attempt: StrictInt
    lease_seconds: StrictInt = 30


def create_app(database_path=None, tokens=None, registry_path=None, artifact_path=None):
    """Fail closed without explicitly configured credentials.

    tokens = {"secret-token": {"subject": "alice", "role": "player"}, ...}.
    Expose only behind trusted TLS reverse proxy; local demo is not multi-tenant.
    """
    if tokens is None:
        tokens = json.loads(os.environ.get("GO_PLATFORM_TOKENS_JSON", "{}"))
    if not isinstance(tokens, dict) or not tokens:
        raise RuntimeError("Configure GO_PLATFORM_TOKENS_JSON or explicit tokens first")
    valid_roles = {"viewer", "player", "researcher", "operator", "admin"}
    for token, who in tokens.items():
        if (not isinstance(token, str) or len(token) < 12
                or not isinstance(who, dict) or who.get("role") not in valid_roles
                or not isinstance(who.get("subject"), str)
                or not 1 <= len(who["subject"]) <= 80):
            raise ValueError("Malformed auth token configuration")
    if database_path is None:
        database_path = os.environ.get("GO_PLATFORM_DB", "runs/platform.sqlite3")
    store = PlatformStore(database_path)
    games = GameService(store)
    jobs = JobService(store)
    registry = LocalRegistry(registry_path) if registry_path else None
    artifacts = ArtifactStore(
        artifact_path or os.environ.get("GO_PLATFORM_ARTIFACTS", "runs/artifacts"))
    analysis = AnalysisService(games, registry, artifacts)
    catalog = ModelCatalog(store, artifacts, registry)
    app = FastAPI(title="Go AI Platform", version="1.0")
    auth = HTTPBearer(auto_error=False)

    @app.exception_handler(PlatformError)
    async def platform_error(request, exc):
        from fastapi.responses import JSONResponse
        return JSONResponse(exc.to_dict(), status_code=exc.status)

    def current(credentials: HTTPAuthorizationCredentials = Depends(auth)):
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=401, detail="Bearer token required")
        for token, principal in tokens.items():
            if secrets.compare_digest(credentials.credentials, token):
                return principal
        raise HTTPException(status_code=401, detail="Invalid bearer token")

    def role(*allowed):
        def dependency(who=Depends(current)):
            if who["role"] not in allowed and who["role"] != "admin":
                raise HTTPException(status_code=403, detail="Insufficient role")
            return who
        return dependency

    def may_view(game, who):
        # Player can access games they participate in; researcher can inspect
        # training records; viewer role is a global read-only observer.
        if who["role"] in ("viewer", "researcher", "operator", "admin"):
            return
        if who["subject"] not in (game["black_actor"], game["white_actor"]):
            raise HTTPException(status_code=403, detail="Not a game participant")

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTML_PAGE

    @app.get("/v1/health")
    def health():
        return {"status": "ok", "component": "go-ai-platform"}

    @app.get("/v1/me")
    def me(who=Depends(current)):
        return who

    @app.post("/v1/games")
    def create_game(body: CreateGame, who=Depends(role("player", "researcher", "operator"))):
        if (who["role"] == "player"
                and who["subject"] not in (body.black_actor, body.white_actor)):
            raise HTTPException(status_code=403, detail="Player must occupy a seat")
        try:
            rules = RuleSpec.from_dict(body.rules)
        except (ValueError, TypeError, KeyError) as exc:
            raise PlatformError("invalid_rules", str(exc), 422) from exc
        if body.model_id != "uniform-baseline-v1":
            catalog.pin_champion(body.model_id)
        return games.create(rules, body.black_actor, body.white_actor, body.model_id)

    @app.get("/v1/games/{game_id}")
    def get_game(game_id: str, who=Depends(current)):
        state = games.snapshot(game_id)
        may_view(state, who)
        return state

    @app.post("/v1/games/{game_id}/commands")
    def submit_move(game_id: str, body: SubmitMove, who=Depends(role(
            "player", "researcher", "operator"))):
        state = games.snapshot(game_id)
        if who["role"] not in ("operator", "admin") and body.actor_id != who["subject"]:
            raise HTTPException(status_code=403, detail="Cannot impersonate another actor")
        may_view(state, who)
        return games.command(game_id, body.command_id, body.expected_seq,
                             body.actor_id, body.action)

    @app.get("/v1/games/{game_id}/events")
    def event_page(game_id: str, after_seq: int = 0, limit: int = 200,
                   who=Depends(current)):
        may_view(games.snapshot(game_id), who)
        return games.events(game_id, after_seq, limit)

    @app.get("/v1/games/{game_id}/record")
    def game_record(game_id: str, who=Depends(current)):
        may_view(games.snapshot(game_id), who)
        return games.record(game_id)

    @app.get("/v1/games/{game_id}/sgf", response_class=PlainTextResponse)
    def game_sgf(game_id: str, who=Depends(current)):
        may_view(games.snapshot(game_id), who)
        return games.sgf(game_id)

    @app.get("/v1/games/{game_id}/stream")
    async def stream(game_id: str, request: Request, after_seq: int = -1,
                     who=Depends(current)):
        state = games.snapshot(game_id)
        may_view(state, who)
        if after_seq < -1:
            raise PlatformError("invalid_cursor", "Invalid stream cursor", 422)

        async def events():
            cursor = after_seq
            if cursor == -1:
                current_state = games.snapshot(game_id)
                yield "event: snapshot\ndata: " + encode(current_state) + "\n\n"
                cursor = current_state["seq"]
            ticks = 0
            while not await request.is_disconnected():
                page = games.events(game_id, cursor, limit=100)
                for item in page["events"]:
                    if item["seq"] != cursor + 1:
                        raise RuntimeError("Gap in authoritative event sequence")
                    cursor = item["seq"]
                    yield ("id: {}\nevent: move\ndata: {}\n\n".format(
                        cursor, encode(item)))
                if not page["has_more"]:
                    await asyncio.sleep(0.35)
                ticks += 1
                if ticks % 30 == 0:
                    yield ": keepalive\n\n"

        return StreamingResponse(events(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.post("/v1/games/{game_id}/analysis")
    def analyze_game(game_id: str, body: Analyze,
                     who=Depends(role("player", "researcher", "operator"))):
        may_view(games.snapshot(game_id), who)
        return analysis.analyze(game_id, body.expected_seq,
                                body.model_id, body.simulations)

    @app.get("/v1/models/champion")
    def champion(who=Depends(current)):
        if registry is None:
            return {"champion": None}
        current_model = registry.current()
        if current_model is None:
            return {"champion": None}
        return {"champion": {"model_id": current_model["model_id"],
                             "manifest": current_model["manifest"]}}

    @app.post("/v1/jobs")
    def submit_job(body: SubmitJob, who=Depends(role("researcher", "operator"))):
        return jobs.submit(who["subject"], body.request_key, body.kind, body.spec)

    @app.get("/v1/jobs/{job_id}")
    def get_job(job_id: str, who=Depends(current)):
        job = jobs.get(job_id)
        if (who["subject"] != job["owner"]
                and who["role"] not in ("operator", "admin")):
            raise HTTPException(status_code=403, detail="Not a job owner")
        return job

    @app.post("/v1/jobs/{job_id}/cancel")
    def cancel_job(job_id: str, who=Depends(role("researcher", "operator"))):
        return jobs.cancel(job_id, who["subject"],
                           operator=who["role"] in ("operator", "admin"))

    @app.post("/v1/workers/lease")
    def lease_job(body: LeaseRequest, who=Depends(role("operator"))):
        return {"job": jobs.claim(body.worker_id, body.lease_seconds)}

    @app.post("/v1/jobs/{job_id}/heartbeat")
    def heartbeat_job(job_id: str, body: Heartbeat, who=Depends(role("operator"))):
        return jobs.heartbeat(job_id, body.worker_id, body.attempt,
                              body.lease_seconds)

    @app.post("/v1/jobs/{job_id}/complete")
    def finish_job(job_id: str, body: FinishJob, who=Depends(role("operator"))):
        if not body.failed:
            artifacts.get(body.digest)
        return jobs.finish(job_id, body.worker_id, body.attempt,
                           body.digest, body.failed)

    @app.post("/v1/artifacts")
    async def upload_artifact(request: Request, who=Depends(role("researcher", "operator"))):
        chunks = bytearray()
        async for chunk in request.stream():
            chunks.extend(chunk)
            if len(chunks) > 1024 * 1024:
                raise PlatformError("invalid_artifact", "HTTP artifact upload limit 1 MiB", 413)
        return {"digest": artifacts.put(bytes(chunks))}

    @app.get("/v1/artifacts/{digest}")
    def artifact_info(digest: str, who=Depends(role("researcher", "operator"))):
        data = artifacts.get(digest)
        return {"digest": digest, "size_bytes": len(data), "verified": True}

    return app


def from_environment():
    return create_app()


# Running with 'uvicorn go_game.platform.api:app' should fail closed rather
# than produce an anonymous server with implicit development credentials.
# Use 'uvicorn go_game.platform.run:app' after configuring env tokens.
