"""
tests/unit/test_ws_auth.py
Unit tests for WebSocket authentication helpers in artemis.api.auth.

These tests exercise validate_ws_token() which is used by the /ws endpoint
to check the ?token= query parameter.  The HTTP dependency require_auth is
covered in test_auth.py.
"""

import importlib
import os
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Reload helper
# ---------------------------------------------------------------------------


def _reload_with_keys(keys: str | None):
    """Reload auth module with a specific ARTEMIS_API_KEYS value."""
    import artemis.api.auth as auth_mod

    clean_env = {k: v for k, v in os.environ.items() if k != "ARTEMIS_API_KEYS"}
    if keys is not None:
        clean_env["ARTEMIS_API_KEYS"] = keys
    with patch.dict(os.environ, clean_env, clear=True):
        importlib.reload(auth_mod)
    return auth_mod


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_ws_token_open_mode_no_env():
    """In open mode any token (even None) is accepted."""
    auth = _reload_with_keys(None)
    assert auth.validate_ws_token(None) is True
    assert auth.validate_ws_token("anything") is True


def test_ws_token_valid_key_accepted():
    """A token matching one of the configured keys should pass."""
    auth = _reload_with_keys("ws-token-abc,ws-token-xyz")
    assert auth.validate_ws_token("ws-token-abc") is True
    assert auth.validate_ws_token("ws-token-xyz") is True


def test_ws_token_invalid_key_rejected():
    """An unrecognised token should be rejected when auth is enabled."""
    auth = _reload_with_keys("correct-key")
    assert auth.validate_ws_token("wrong-key") is False


def test_ws_token_empty_string_rejected():
    """An empty-string token should be rejected when auth is enabled."""
    auth = _reload_with_keys("some-key")
    assert auth.validate_ws_token("") is False


def test_ws_token_none_rejected_when_auth_enabled():
    """None token should be rejected when auth is enabled."""
    auth = _reload_with_keys("some-key")
    assert auth.validate_ws_token(None) is False


def test_auth_enabled_flag():
    """auth_enabled() reflects whether keys are configured."""
    auth = _reload_with_keys("any-key")
    # Check enabled BEFORE reloading back to open mode — both share the same module object
    assert auth.auth_enabled() is True
    _reload_with_keys(None)
    assert auth.auth_enabled() is False
