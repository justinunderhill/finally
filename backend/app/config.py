"""Application configuration helpers."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = BACKEND_ROOT / "static"

default_db_path = (
    Path("/tmp/finally.db") if os.environ.get("VERCEL") else PROJECT_ROOT / "db" / "finally.db"
)
DB_PATH = Path(os.environ.get("FINALLY_DB_PATH", default_db_path))


def load_env() -> None:
    """Load simple KEY=value pairs from the project .env file if present."""
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)
