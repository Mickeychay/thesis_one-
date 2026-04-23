"""Deployment entrypoint for platforms that auto-detect `app.py` or `app:app`."""

from api import app


if __name__ == "__main__":
    import uvicorn
    from config import get_config

    config = get_config()
    uvicorn.run(app, host=getattr(config, "HOST", "0.0.0.0"), port=getattr(config, "PORT", 8000))
