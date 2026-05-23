"""
tests/unit/test_auth.py
Unit tests for artemis.api.auth — API-key authentication helpers.
"""
import importlib
import os
from unittest.mock import patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from fastapi import FastAPI, Depends
from fastapi.security import APIKeyHeader


# ---------------------------------------------------------------------------
# Helper: reload the auth module with a custom env var value
# ---------------------------------------------------------------------------

def _reload_auth(api_keys: str | None):
    """Re-import artemis.api.auth with a fresh environment."""
    env = {}
    if api_keys is not None:
        env["ARTEMIS_API_KEYS"] = api_keys

    import artemis.api.auth as auth_mod
    with patch.dict(os.environ, env, clear=True if api_keys is None else False):
        # Force environment to exactly the test value
        if api_keys is None:
            os.environ.pop("ARTEMIS_API_KEYS", None)
        importlib.reload(auth_mod)
    return auth_mod


# ---------------------------------------------------------------------------
# Test: open mode (no env var)
# ---------------------------------------------------------------------------

def test_open_mode_no_keys():
    """When ARTEMIS_API_KEYS is unset, auth_enabled() returns False."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ARTEMIS_API_KEYS", None)
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.auth_enabled() is False


def test_open_mode_validate_ws_token_always_passes():
    """validate_ws_token returns True for any token when auth is disabled."""
    with patch.dict(os.environ, {}, clear=True):
        os.environ.pop("ARTEMIS_API_KEYS", None)
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.validate_ws_token(None) is True
        assert auth_mod.validate_ws_token("garbage") is True


def test_auth_enabled_with_single_key():
    """When ARTEMIS_API_KEYS is set with one key, auth is enabled."""
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "secret-key-1"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.auth_enabled() is True


def test_valid_key_passes():
    """validate_ws_token returns True for a valid key."""
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "key-a,key-b"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.validate_ws_token("key-a") is True
        assert auth_mod.validate_ws_token("key-b") is True


def test_invalid_key_rejected():
    """validate_ws_token returns False for an unknown key."""
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "real-key"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)
        assert auth_mod.validate_ws_token("wrong-key") is False
        assert auth_mod.validate_ws_token("") is False
        assert auth_mod.validate_ws_token(None) is False


def test_require_auth_raises_401_on_missing_key():
    """POST /commands endpoint should return 401 if auth enabled and key missing."""
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "valid-key"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)

        from artemis.api.rest import create_app
        from unittest.mock import MagicMock

        tm = MagicMock()
        tm.count = 0
        tm.get_snapshot.return_value = []

        agg = MagicMock()
        agg._running = True
        agg._last_fusion_ts = None
        agg.nodes = {}

        app = create_app(tm, agg)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post("/commands/jammer-01", json={"action": "activate"})
        assert r.status_code == 401


def test_require_auth_passes_with_valid_key():
    """POST /commands with a valid X-API-Key should not be blocked."""
    with patch.dict(os.environ, {"ARTEMIS_API_KEYS": "my-key"}):
        import artemis.api.auth as auth_mod
        importlib.reload(auth_mod)

        from artemis.api.rest import create_app
        from unittest.mock import MagicMock

        tm = MagicMock()
        tm.count = 0
        tm.get_snapshot.return_value = []
        agg = MagicMock()
        agg._running = True
        agg._last_fusion_ts = None
        agg.nodes = {}

        app = create_app(tm, agg)
        client = TestClient(app, raise_server_exceptions=False)
        r = client.post(
            "/commands/jammer-01",
            json={"action": "activate"},
            headers={"X-API-Key": "my-key"},
        )
        # 200 in simulation mode (no publisher wired)
        assert r.status_code == 200
        assert r.json()["status"] == "queued_simulation"
