"""ASGI entrypoint: uvicorn go_game.platform.run:app --host 127.0.0.1 --port 8008

Requires GO_PLATFORM_TOKENS_JSON, deliberately refuses anonymous startup.
"""
from .api import from_environment

app = from_environment()
