from __future__ import annotations

import os
from pathlib import Path


def load_questbank_env(*, override: bool = False) -> Path | None:
    """Load repo-root ``.env`` into ``os.environ`` if python-dotenv is installed.

    Returns the path loaded, or None if no file / dotenv unavailable.
    Does not invent credentials — missing keys stay missing.
    """
    root = Path(__file__).resolve().parents[3]
    env_path = root / ".env"
    if not env_path.is_file():
        return None
    try:
        from dotenv import load_dotenv
    except ImportError:
        _load_env_fallback(env_path, override=override)
        return env_path
    load_dotenv(env_path, override=override)
    return env_path


def _load_env_fallback(env_path: Path, *, override: bool) -> None:
    """Minimal KEY=VALUE loader when python-dotenv is not installed."""
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip("'").strip('"')
        if not key:
            continue
        if override or key not in os.environ:
            os.environ[key] = value
