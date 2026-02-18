"""
Integration tests for LoaderThread.

Patches get_provider so no real network calls are made.
Uses qtbot.waitSignal to receive async Qt signals from the background thread.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from gitmoving.auth.base import Credentials
from gitmoving.ui.qt_app import LoaderThread, STATUS_PENDING
from tests.conftest import make_repo_info, MockProvider, provider_class_for


TIMEOUT_MS = 8_000   # generous timeout for slow CI


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def src_repos():
    return [
        make_repo_info("repo-a", owner="srcowner"),
        make_repo_info("repo-b", owner="srcowner"),
    ]


@pytest.fixture
def token_params():
    return {
        "src_platform": "github",
        "src_owner":    "srcowner",
        "src_token":    "ghp_src",
        "src_username": "",
        "src_base_url": None,
        "dst_platform": "github",
        "dst_owner":    "dstowner",
        "dst_token":    "ghp_dst",
        "dst_username": "",
        "dst_base_url": None,
    }


def _make_src_dst(src_repos, existing=None):
    """Build MockProvider instances injected via provider_class_for()."""
    creds = Credentials(provider="github", token="t")
    src = MockProvider(creds, username="srcuser", repos=src_repos)
    dst = MockProvider(
        creds,
        username="dstuser",
        repos=[],
        existing_names=set(existing or []),
    )
    return src, dst


# ─────────────────────────────────────────────────────────────────────────────
# 1. Happy path
# ─────────────────────────────────────────────────────────────────────────────

class TestLoaderSuccess:

    def test_finished_signal_carries_repos(self, qtbot, token_params, src_repos):
        src, dst = _make_src_dst(src_repos)
        received = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.finished.connect(received.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert len(received) == 1
        result = received[0]
        assert set(result["repos"].keys()) == {"repo-a", "repo-b"}

    def test_repos_all_selected_by_default(self, qtbot, token_params, src_repos):
        src, dst = _make_src_dst(src_repos)
        received = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.finished.connect(received.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        for row in received[0]["repos"].values():
            assert row.selected is True

    def test_dst_exists_flag_set_correctly(self, qtbot, token_params, src_repos):
        """repo-a exists on destination, repo-b does not."""
        src, dst = _make_src_dst(src_repos, existing=["repo-a"])
        received = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.finished.connect(received.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        repos = received[0]["repos"]
        assert repos["repo-a"].dst_exists is True
        assert repos["repo-b"].dst_exists is False

    def test_providers_and_owners_returned(self, qtbot, token_params, src_repos):
        src, dst = _make_src_dst(src_repos)
        received = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.finished.connect(received.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        result = received[0]
        assert result["src_provider"] is src
        assert result["dst_provider"] is dst
        assert result["src_owner"] == "srcowner"     # explicit owner from params
        assert result["dst_owner"] == "dstowner"     # explicit owner from params

    def test_owner_resolved_from_validated_user_when_blank(self, qtbot, src_repos):
        """When owner is blank, the validated username is used as owner."""
        params = {
            "src_platform": "github",
            "src_owner":    "",          # blank → fall back to validate_credentials()
            "src_token":    "ghp_src",
            "src_username": "",
            "src_base_url": None,
            "dst_platform": "github",
            "dst_owner":    "",
            "dst_token":    "ghp_dst",
            "dst_username": "",
            "dst_base_url": None,
        }
        creds = Credentials(provider="github", token="t")
        src = MockProvider(creds, username="autouser", repos=src_repos)
        dst = MockProvider(creds, username="autouser", repos=[])
        received = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(params)
            thread.signals.finished.connect(received.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert received[0]["src_owner"] == "autouser"

    def test_status_signals_emitted(self, qtbot, token_params, src_repos):
        src, dst = _make_src_dst(src_repos)
        statuses = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.status.connect(statuses.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert len(statuses) >= 2    # "Authenticating…", "Listing…", "N repos loaded"

    def test_no_error_signal_on_success(self, qtbot, token_params, src_repos):
        src, dst = _make_src_dst(src_repos)
        errors = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.error.connect(errors.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert errors == []


# ─────────────────────────────────────────────────────────────────────────────
# 2. Error paths
# ─────────────────────────────────────────────────────────────────────────────

class TestLoaderErrors:

    def test_auth_failure_emits_error_signal(self, qtbot, token_params):
        creds = Credentials(provider="github", token="bad")
        src = MockProvider(
            creds,
            raise_validate=RuntimeError("Bad credentials"),
        )

        errors = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(src)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.error.connect(errors.append)
            with qtbot.waitSignal(thread.signals.error, timeout=TIMEOUT_MS):
                thread.start()

        assert len(errors) == 1
        assert "Bad credentials" in errors[0]

    def test_list_failure_emits_error_signal(self, qtbot, token_params):
        creds = Credentials(provider="github", token="t")
        src = MockProvider(creds, raise_list=ValueError("Forbidden"))
        dst = MockProvider(creds)
        errors = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(dst)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.error.connect(errors.append)
            with qtbot.waitSignal(thread.signals.error, timeout=TIMEOUT_MS):
                thread.start()

        assert "Forbidden" in errors[0]

    def test_error_emitted_not_finished_on_failure(self, qtbot, token_params):
        creds = Credentials(provider="github", token="bad")
        src = MockProvider(creds, raise_validate=RuntimeError("fail"))
        finished_calls = []
        error_calls = []

        with patch(
            "gitmoving.ui.qt_app.get_provider",
            side_effect=[provider_class_for(src), provider_class_for(src)],
        ):
            thread = LoaderThread(token_params)
            thread.signals.finished.connect(finished_calls.append)
            thread.signals.error.connect(error_calls.append)
            with qtbot.waitSignal(thread.signals.error, timeout=TIMEOUT_MS):
                thread.start()

        assert finished_calls == []
        assert len(error_calls) == 1

    def test_missing_dst_token_raises_value_error(self, qtbot, src_repos):
        """If no dst token and nothing in env/keyring, loader emits error."""
        from unittest.mock import MagicMock

        params = {
            "src_platform": "github",
            "src_owner":    "srcowner",
            "src_token":    "ghp_src",
            "src_username": "",
            "src_base_url": None,
            "dst_platform": "gitlab",  # different platform → no fallback
            "dst_owner":    "dstowner",
            "dst_token":    "",         # no token
            "dst_username": "",
            "dst_base_url": None,
        }
        creds = Credentials(provider="github", token="t")
        src = MockProvider(creds, repos=src_repos)
        errors = []

        auth_obj = MagicMock()
        auth_obj._load_from_env.return_value = None
        auth_obj.load_credentials.return_value = None
        auth_cls = MagicMock(return_value=auth_obj)

        with (
            patch(
                "gitmoving.ui.qt_app.get_provider",
                side_effect=[provider_class_for(src)],
            ),
            patch(
                "gitmoving.ui.qt_app.get_auth_handler",
                return_value=auth_cls,
            ),
        ):
            thread = LoaderThread(params)
            thread.signals.error.connect(errors.append)
            with qtbot.waitSignal(thread.signals.error, timeout=TIMEOUT_MS):
                thread.start()

        assert len(errors) == 1
        assert "No credentials" in errors[0] or "credentials" in errors[0].lower()
