"""
Integration tests for MigratorThread.

GitRunner.clone_mirror and GitRunner.push_mirror are patched so no real
git processes are spawned.  Provider calls use MockProvider in-memory.
"""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from gitmoving.auth.base import Credentials
from gitmoving.ui.qt_app import (
    MigratorThread,
    RepoRow,
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_RUNNING,
)
from tests.conftest import make_repo_info, MockProvider


TIMEOUT_MS = 10_000


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _creds(platform="github"):
    return Credentials(provider=platform, token="tok")


def _make_thread(
    selected_names: list[str],
    src_provider: MockProvider,
    dst_provider: MockProvider,
    src_owner: str = "srcowner",
    dst_owner: str = "dstowner",
) -> MigratorThread:
    rows = [
        RepoRow(
            info=src_provider._repos[[r.name for r in src_provider._repos].index(n)]
            if n in [r.name for r in src_provider._repos]
            else make_repo_info(n),
            selected=True,
        )
        for n in selected_names
    ]
    return MigratorThread(rows, src_provider, dst_provider, src_owner, dst_owner)


def _mock_git(branches=("main",), tags=("v1.0",)):
    """Patch GitRunner so no subprocess is run; returns branch/tag lists."""
    git_mock = MagicMock()
    git_mock.clone_mirror.return_value = None
    git_mock.push_mirror.return_value  = None
    git_mock.list_branches.return_value = list(branches)
    git_mock.list_tags.return_value     = list(tags)

    return patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def two_repos():
    return [
        make_repo_info("alpha", owner="srcowner"),
        make_repo_info("beta",  owner="srcowner"),
    ]


@pytest.fixture
def src(two_repos):
    return MockProvider(_creds(), username="srcuser", repos=two_repos)


@pytest.fixture
def dst(two_repos):
    return MockProvider(
        _creds(), username="dstuser",
        existing_names={"alpha"},    # alpha already exists; beta is new
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Happy path – both repos succeed
# ─────────────────────────────────────────────────────────────────────────────

class TestMigratorSuccess:

    def test_finished_signal_counts(self, qtbot, src, dst, two_repos):
        thread = _make_thread(["alpha", "beta"], src, dst)
        finished = []

        with _mock_git(branches=["main"], tags=["v1.0"]):
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        done, errors = finished[0]
        assert done   == 2
        assert errors == 0

    def test_cell_update_signals_emitted(self, qtbot, src, dst):
        updates = []
        thread = _make_thread(["alpha", "beta"], src, dst)

        with _mock_git():
            thread.signals.cell_update.connect(
                lambda rk, ck, v: updates.append((rk, ck, v))
            )
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        status_updates = [(rk, v) for rk, ck, v in updates if ck == "status"]
        assert any(v == STATUS_RUNNING for _, v in status_updates)
        assert any(v == STATUS_DONE    for _, v in status_updates)

    def test_branch_count_in_cell_updates(self, qtbot, src, dst):
        updates = []
        thread = _make_thread(["alpha"], src, dst)

        with _mock_git(branches=["main", "dev"], tags=[]):
            thread.signals.cell_update.connect(
                lambda rk, ck, v: updates.append((rk, ck, v))
            )
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        branch_updates = [v for _, ck, v in updates if ck == "branches"]
        assert "2" in branch_updates

    def test_tag_count_in_cell_updates(self, qtbot, src, dst):
        updates = []
        thread = _make_thread(["alpha"], src, dst)

        with _mock_git(branches=["main"], tags=["v1.0", "v2.0", "v3.0"]):
            thread.signals.cell_update.connect(
                lambda rk, ck, v: updates.append((rk, ck, v))
            )
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        tag_updates = [v for _, ck, v in updates if ck == "tags"]
        assert "3" in tag_updates

    def test_log_messages_emitted(self, qtbot, src, dst):
        logs = []
        thread = _make_thread(["alpha", "beta"], src, dst)

        with _mock_git():
            thread.signals.log.connect(logs.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        combined = "\n".join(logs)
        assert "alpha" in combined
        assert "beta"  in combined
        assert "Done"  in combined or "done" in combined.lower()

    def test_existing_repo_not_created_again(self, qtbot, src, dst):
        """'alpha' already exists on dst → create_repo must NOT be called."""
        thread = _make_thread(["alpha"], src, dst)

        with _mock_git():
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        # dst._created should NOT contain "alpha" (it was never created)
        assert "alpha" not in dst._created

    def test_new_repo_is_created_on_dst(self, qtbot, src, dst):
        """'beta' is new on dst → create_repo should be called."""
        thread = _make_thread(["beta"], src, dst)

        with _mock_git():
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert "beta" in dst._created

    def test_row_mig_status_updated_to_done(self, qtbot, src, dst, two_repos):
        rows = [RepoRow(info=r, selected=True) for r in two_repos]
        thread = MigratorThread(rows, src, dst, "srcowner", "dstowner")

        with _mock_git():
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert all(r.mig_status == STATUS_DONE for r in rows)

    def test_single_repo_migration(self, qtbot, src, dst):
        thread = _make_thread(["alpha"], src, dst)
        finished = []

        with _mock_git():
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert finished[0] == (1, 0)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Error paths
# ─────────────────────────────────────────────────────────────────────────────

class TestMigratorErrors:

    def test_clone_failure_counts_as_error(self, qtbot, src, dst):
        thread = _make_thread(["alpha"], src, dst)
        finished = []

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect = RuntimeError("clone failed")

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        done, errors = finished[0]
        assert done   == 0
        assert errors == 1

    def test_push_failure_counts_as_error(self, qtbot, src, dst):
        thread = _make_thread(["beta"], src, dst)
        finished = []

        git_mock = MagicMock()
        git_mock.clone_mirror.return_value  = None
        git_mock.list_branches.return_value = ["main"]
        git_mock.list_tags.return_value     = []
        git_mock.push_mirror.side_effect    = RuntimeError("push failed")

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert finished[0] == (0, 1)

    def test_error_cell_update_emitted(self, qtbot, src, dst):
        updates = []
        thread = _make_thread(["alpha"], src, dst)

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect = RuntimeError("boom")

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.cell_update.connect(
                lambda rk, ck, v: updates.append((rk, ck, v))
            )
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        error_statuses = [v for rk, ck, v in updates if ck == "status" and v == STATUS_ERROR]
        assert len(error_statuses) == 1

    def test_notes_cell_contains_truncated_error(self, qtbot, src, dst):
        updates = []
        thread = _make_thread(["alpha"], src, dst)
        long_msg = "X" * 200

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect = RuntimeError(long_msg)

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.cell_update.connect(
                lambda rk, ck, v: updates.append((rk, ck, v))
            )
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        notes = [v for _, ck, v in updates if ck == "notes"]
        assert len(notes) == 1
        assert len(notes[0]) <= 80   # truncated

    def test_row_mig_status_updated_to_error(self, qtbot, src, dst, two_repos):
        rows = [RepoRow(info=r, selected=True) for r in two_repos]
        thread = MigratorThread(rows, src, dst, "srcowner", "dstowner")

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect = RuntimeError("fail")

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert all(r.mig_status == STATUS_ERROR for r in rows)

    def test_partial_success_counts_correctly(self, qtbot, src, dst, two_repos):
        """First repo fails, second succeeds → done=1 errors=1."""
        rows = [RepoRow(info=r, selected=True) for r in two_repos]
        thread = MigratorThread(rows, src, dst, "srcowner", "dstowner")
        finished = []

        call_count = 0

        def clone_side_effect(url, dest):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("first fails")

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect = clone_side_effect
        git_mock.push_mirror.return_value  = None
        git_mock.list_branches.return_value = ["main"]
        git_mock.list_tags.return_value     = []

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        done, errors = finished[0]
        assert done   == 1
        assert errors == 1

    def test_error_in_one_repo_does_not_abort_others(self, qtbot, src, dst, two_repos):
        """Error in first repo must not prevent second from running."""
        logs = []
        rows = [RepoRow(info=r, selected=True) for r in two_repos]
        thread = MigratorThread(rows, src, dst, "srcowner", "dstowner")

        call_count = 0

        def clone_side_effect(url, dest):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("only first fails")

        git_mock = MagicMock()
        git_mock.clone_mirror.side_effect   = clone_side_effect
        git_mock.push_mirror.return_value   = None
        git_mock.list_branches.return_value = ["main"]
        git_mock.list_tags.return_value     = []

        with patch("gitmoving.ui.qt_app.GitRunner", return_value=git_mock):
            thread.signals.log.connect(logs.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        # Both repos must appear in the log
        combined = "\n".join(logs)
        assert two_repos[0].name in combined
        assert two_repos[1].name in combined

    def test_create_failure_counts_as_error(self, qtbot, src):
        """Destination create_repo raises → repo counted as failed."""
        creds = Credentials(provider="github", token="t")
        bad_dst = MockProvider(
            creds,
            raise_create=RuntimeError("quota exceeded"),
        )
        thread = _make_thread(["beta"], src, bad_dst)    # beta is new → triggers create
        finished = []

        with _mock_git():
            thread.signals.finished.connect(finished.append)
            with qtbot.waitSignal(thread.signals.finished, timeout=TIMEOUT_MS):
                thread.start()

        assert finished[0] == (0, 1)
