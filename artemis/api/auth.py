"""
artemis/api/auth.py
API-key authentication for the ARTEMIS Hub REST + WebSocket endpoints.

Design
------
API keys are loaded from the environment variable ``ARTEMIS_API_KEYS``
(comma-separated list, e.g. ``key-abc,key-xyz``).  If the variable is unset
or empty the hub starts in **open mode** (no auth required) and logs a
warning.

Usage — FastAPI dependency
--------------------------
    from artemis.api.auth import require_auth

    @app.get("/threats")
    async def get_threats(api_key: str = Depends(require_auth)):
        ...

Open endpoints (no auth needed)
---------------------------------
- GET /           (root health ping)
- GET /health     (detailed health)
- GET /metrics    (Prometheus scrape)
- GET /ws         (WebSocket — has its own token= query-param check)
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from fastapi import Depends, HTTPException, Security, status
from fastapi.security import APIKeyHeader

_log = logging.getLogger("api.auth")

# ---------------------------------------------------------------------------
# Key registry
# ---------------------------------------------------------------------------

_API_KEYS: frozenset[str] = frozenset()
_AUTH_ENABLED: bool = False

def _load_keys() -> None:
    global _API_KEYS, _AUTH_ENABLED
    raw = os.environ.get("ARTEMIS_API_KEYS", "").strip()
    if not raw:
        _log.warning(
            "ARTEMIS_API_KEYS not set — hub running in open (unauthenticated) mode"
        )
        _AUTH_ENABLED = False
        return
    keys = {k.strip() for k in raw.split(",") if k.strip()}
    if not keys:
        _log.warning("ARTEMIS_API_KEYS is set but contains no valid keys — open mode")
        _AUTH_ENABLED = False
        return
    _API_KEYS = frozenset(keys)
    _AUTH_ENABLED = True
    _log.info("API auth enabled — %d key(s) loaded", len(keys))

# Load on import
_load_keys()


# ---------------------------------------------------------------------------
# FastAPI header extractor
# ---------------------------------------------------------------------------

_api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def require_auth(
    api_key: Optional[str] = Security(_api_key_header),
) -> Optional[str]:
    """
    FastAPI dependency that enforces API-key auth when auth is enabled.

    Returns the validated key (or None in open mode).
    Raises HTTP 401 if auth is enabled and the key is missing or wrong.
    """
    if not _AUTH_ENABLED:
        return None   # open mode — allow all
    if not api_key or api_key not in _API_KEYS:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-API-Key",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return api_key


def validate_ws_token(token: Optional[str]) -> bool:
    """
    Validate a token provided as a WebSocket query parameter (?token=…).

    Returns True if auth is disabled (open mode) OR if the token is valid.
    Returns False if auth is enabled and the token is missing/invalid.
    """
    if not _AUTH_ENABLED:
        return True
    if not token:
        return False
    return token in _API_KEYS


def auth_enabled() -> bool:
    """Return True if authentication is currently enforced."""
    return _AUTH_ENABLED
