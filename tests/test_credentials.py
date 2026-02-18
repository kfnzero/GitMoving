"""
Unit tests for the _make_credentials() helper in gitmoving.ui.qt_app.

Tests cover every credential resolution path:
  1. Explicit token in form (GitHub / Bitbucket field differences)
  2. Token from environment variable (mocked via auth handler)
  3. Token from saved keyring (mocked via auth handler)
  4. Fallback: reuse source creds when destination uses same platform
  5. Error: nothing available → ValueError
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from gitmoving.auth.base import Credentials
from gitmoving.ui.qt_app import _make_credentials


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _params(
    platform: str = "github",
    token: str = "",
    username: str = "",
    base_url: str | None = None,
    side: str = "src",
) -> dict:
    """Build a minimal params dict for one side."""
    return {
        f"{side}_platform": platform,
        f"{side}_owner":    "owner",
        f"{side}_token":    token,
        f"{side}_username": username,
        f"{side}_base_url": base_url,
    }


def _mock_auth_handler(env_creds=None, saved_creds=None):
    """Return a mock get_auth_handler that yields a configurable auth object."""
    auth_obj = MagicMock()
    auth_obj._load_from_env.return_value = env_creds
    auth_obj.load_credentials.return_value = saved_creds

    auth_cls = MagicMock(return_value=auth_obj)

    patcher = patch("gitmoving.ui.qt_app.get_auth_handler", return_value=auth_cls)
    return patcher


# ─────────────────────────────────────────────────────────────────────────────
# 1. Explicit token
# ─────────────────────────────────────────────────────────────────────────────

class TestExplicitToken:

    def test_github_token_sets_token_field(self):
        params = _params(platform="github", token="ghp_abc123")
        creds = _make_credentials("src", params)
        assert creds.token    == "ghp_abc123"
        assert creds.password is None
        assert creds.provider == "github"

    def test_gitlab_token_sets_token_field(self):
        params = _params(platform="gitlab", token="glpat-xyz")
        creds = _make_credentials("src", params)
        assert creds.token == "glpat-xyz"
        assert creds.provider == "gitlab"

    def test_bitbucket_token_sets_password_not_token(self):
        """Bitbucket uses app-password via the `password` field."""
        params = _params(platform="bitbucket", token="bbtoken", username="bbuser")
        creds = _make_credentials("src", params)
        assert creds.token    is None
        assert creds.password == "bbtoken"
        assert creds.username == "bbuser"
        assert creds.provider == "bitbucket"

    def test_explicit_token_skips_auth_handler(self):
        """get_auth_handler must NOT be called when a token is supplied."""
        params = _params(token="ghp_direct")
        with patch("gitmoving.ui.qt_app.get_auth_handler") as mock_handler:
            _make_credentials("src", params)
            mock_handler.assert_not_called()

    def test_base_url_passed_through(self):
        params = _params(platform="gitlab", token="t", base_url="https://gl.internal")
        creds = _make_credentials("src", params)
        assert creds.base_url == "https://gl.internal"

    def test_empty_base_url_becomes_none(self):
        params = _params(token="t", base_url=None)
        creds = _make_credentials("src", params)
        assert creds.base_url is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. Environment variable path
# ─────────────────────────────────────────────────────────────────────────────

class TestEnvVar:

    def test_env_creds_returned_when_no_token(self):
        env_creds = Credentials(provider="github", token="env_token")
        params = _params(token="")          # no explicit token

        with _mock_auth_handler(env_creds=env_creds):
            creds = _make_credentials("src", params)

        assert creds.token == "env_token"

    def test_env_creds_take_priority_over_keyring(self):
        env_creds    = Credentials(provider="github", token="from_env")
        saved_creds  = Credentials(provider="github", token="from_keyring")
        params = _params(token="")

        with _mock_auth_handler(env_creds=env_creds, saved_creds=saved_creds):
            creds = _make_credentials("src", params)

        assert creds.token == "from_env"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Keyring / saved credentials path
# ─────────────────────────────────────────────────────────────────────────────

class TestKeyring:

    def test_saved_creds_used_when_no_env(self):
        saved_creds = Credentials(provider="github", token="keyring_token")
        params = _params(token="")

        with _mock_auth_handler(env_creds=None, saved_creds=saved_creds):
            creds = _make_credentials("src", params)

        assert creds.token == "keyring_token"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Fallback to source credentials (same platform)
# ─────────────────────────────────────────────────────────────────────────────

class TestFallback:

    def test_dst_reuses_src_creds_on_same_platform(self):
        fallback = Credentials(provider="github", token="ghp_src")
        params = _params(platform="github", token="", side="dst")

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            creds = _make_credentials("dst", params, fallback=fallback)

        assert creds.token    == "ghp_src"
        assert creds.provider == "github"

    def test_dst_does_not_reuse_src_creds_on_different_platform(self):
        fallback = Credentials(provider="github", token="ghp_src")
        params   = _params(platform="gitlab", token="", side="dst")

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            with pytest.raises(ValueError, match="No credentials found"):
                _make_credentials("dst", params, fallback=fallback)

    def test_fallback_inherits_base_url_from_src_when_dst_has_none(self):
        fallback = Credentials(
            provider="gitlab", token="t", base_url="https://gl.internal"
        )
        params = _params(platform="gitlab", token="", side="dst", base_url=None)

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            creds = _make_credentials("dst", params, fallback=fallback)

        assert creds.base_url == "https://gl.internal"

    def test_dst_base_url_overrides_fallback(self):
        fallback = Credentials(
            provider="gitlab", token="t", base_url="https://old.gl"
        )
        params = _params(
            platform="gitlab", token="", side="dst", base_url="https://new.gl"
        )

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            creds = _make_credentials("dst", params, fallback=fallback)

        assert creds.base_url == "https://new.gl"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Error path – nothing available
# ─────────────────────────────────────────────────────────────────────────────

class TestMissingCredentials:

    def test_raises_value_error_when_nothing_found(self):
        params = _params(platform="github", token="")

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            with pytest.raises(ValueError, match="No credentials found"):
                _make_credentials("src", params)

    def test_error_message_includes_side_and_platform(self):
        params = _params(platform="bitbucket", token="", side="dst")

        with _mock_auth_handler(env_creds=None, saved_creds=None):
            with pytest.raises(ValueError, match="dst") as exc_info:
                _make_credentials("dst", params)

        assert "bitbucket" in str(exc_info.value)
