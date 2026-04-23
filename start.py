"""Hosted deployment launcher with conservative runtime defaults."""

import os

os.environ.setdefault("H2L_SAFE_START", "true")
os.environ.setdefault("USE_RERANK", "false")

import uvicorn

from api import app
from config import get_config


if __name__ == "__main__":
    config = get_config()
    uvicorn.run(
        app,
        host=getattr(config, "HOST", "0.0.0.0"),
        port=getattr(config, "PORT", 8000),
    )
