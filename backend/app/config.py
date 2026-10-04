"""Environment-backed settings.

Every value comes from the process environment. `backend/.env` is loaded first
if it exists, but a real environment variable always wins — `load_dotenv` does
not override what is already set. No secret is ever defaulted to a real value:
defaults here are development conveniences only.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

# backend/.env, i.e. one level up from this package.
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

DEFAULT_FRONTEND_URL = "http://localhost:5173"


@dataclass(frozen=True)
class Settings:
    """Settings read once at import. Extend as later sections add env vars."""

    frontend_url: str


@lru_cache
def get_settings() -> Settings:
    """Cached settings. Call `get_settings.cache_clear()` in tests that patch env."""
    return Settings(
        frontend_url=os.getenv("FRONTEND_URL", DEFAULT_FRONTEND_URL),
    )
