"""Vercel-compatible entrypoint.

Vercel's Python framework preset detects this root-level module and serves the
FastAPI ASGI app. Local development can use ``uvicorn app.main:app``.
"""

from app.main import app

__all__ = ["app"]
