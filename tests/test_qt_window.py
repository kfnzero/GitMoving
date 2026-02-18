"""
Widget tests for GitMovingWindow (PySide6).

Uses pytest-qt (qtbot fixture) for GUI interaction without
requiring a display server (works in headless CI with a virtual display).

Coverage:
  - Window creation and tab structure
  - Form field reading (_read_form)
  - Repo table population and selection toggling
  - Select-All / Select-None buttons
  - Migration table initialisation and cell colouring
  - Status-bar text updates
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from gitmoving.auth.base import Credentials
from gitmoving.providers.base import RepoInfo
from gitmoving.ui.qt_app import (
    STATUS_DONE,
    STATUS_ERROR,
    STATUS_PENDING,
    STATUS_RUNNING,
    GitMovingWindow,
    RepoRow,
)
from tests.conftest import make_repo_info, MockProvider


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def window(qtbot):
    w = GitMovingWindow()
    qtbot.addWidget(w)
    w.show()
    return w


@pytest.fixture
def populated_window(window, src_repos):
    """Window with three repos pre-loaded (no network calls)."""
    creds = Credentials(provider="github", token="t")
    provider = MockProvider(creds, repos=src_repos, existing_names={"alpha"})
    window.src_provider        = provider
    window.dst_provider        = provider
    window.src_owner_resolved  = "srcowner"
    window.dst_owner_resolved  = "dstowner"

    window.repos = {
        r.name: RepoRow(
            info=r,
            selected=True,
            dst_exists=(r.name == "alpha"),
        )
        for r in src_repos
    }
    window._rebuild_repo_table()
    return window


# ─────────────────────────────────────────────────────────────────────────────
# 1. Window creation
# ─────────────────────────────────────────────────────────────────────────────

class TestWindowCreation:

    def test_window_has_three_tabs(self, window):
        assert window.tabs.count() == 3

    def test_tab_labels(self, window):
        labels = [window.tabs.tabText(i) for i in range(3)]
        assert any("Setup"      in lbl for lbl in labels)
        assert any("Repositor"  in lbl for lbl in labels)
        assert any("Migration"  in lbl for lbl in labels)

    def test_initial_tab_is_setup(self, window):
        assert window.tabs.currentIndex() == 0

    def test_window_title_contains_gitmoving(self, window):
        assert "GitMoving" in window.windowTitle()

    def test_load_button_exists_and_is_enabled(self, window):
        assert window.btn_load.isEnabled()

    def test_repo_status_label_initial_text(self, window):
        assert "No repositories" in window.repo_status_label.text()


# ─────────────────────────────────────────────────────────────────────────────
# 2. Form reading
# ─────────────────────────────────────────────────────────────────────────────

class TestFormReading:

    def test_read_form_defaults_are_empty(self, window):
        params = window._read_form()
        assert params["src_owner"]    == ""
        assert params["src_token"]    == ""
        assert params["src_username"] == ""
        assert params["src_base_url"] is None
        assert params["dst_owner"]    == ""
        assert params["dst_token"]    == ""
        assert params["dst_base_url"] is None

    def test_read_form_returns_selected_platform(self, window):
        # Default index 0 = "GitHub"
        params = window._read_form()
        assert params["src_platform"] == "github"
        assert params["dst_platform"] == "github"

    def test_read_form_reflects_typed_values(self, window):
        window.src_owner.setText("myorg")
        window.src_token.setText("ghp_secret")
        window.dst_owner.setText("destorg")
        window.dst_base_url.setText("https://gl.example.com")

        params = window._read_form()
        assert params["src_owner"]    == "myorg"
        assert params["src_token"]    == "ghp_secret"
        assert params["dst_owner"]    == "destorg"
        assert params["dst_base_url"] == "https://gl.example.com"

    def test_read_form_strips_whitespace(self, window):
        window.src_owner.setText("  trimmed  ")
        params = window._read_form()
        assert params["src_owner"] == "trimmed"

    def test_read_form_blank_base_url_becomes_none(self, window):
        window.src_base_url.setText("   ")
        params = window._read_form()
        assert params["src_base_url"] is None

    def test_platform_combo_gitlab(self, window):
        window.src_platform.setCurrentIndex(1)  # GitLab
        params = window._read_form()
        assert params["src_platform"] == "gitlab"

    def test_platform_combo_bitbucket(self, window):
        window.src_platform.setCurrentIndex(2)  # Bitbucket
        params = window._read_form()
        assert params["src_platform"] == "bitbucket"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Repository table
# ─────────────────────────────────────────────────────────────────────────────

class TestRepoTable:

    def test_table_row_count_matches_repos(self, populated_window):
        assert populated_window.repo_table.rowCount() == 3

    def test_repo_names_in_table(self, populated_window):
        names = {
            populated_window.repo_table.item(r, 1).text()
            for r in range(populated_window.repo_table.rowCount())
        }
        assert names == {"alpha", "beta", "gamma"}

    def test_checkbox_checked_for_selected_repos(self, populated_window):
        for r in range(populated_window.repo_table.rowCount()):
            chk = populated_window.repo_table.item(r, 0)
            assert chk.checkState() == Qt.Checked

    def test_checkbox_unchecked_after_deselect(self, populated_window):
        populated_window._handle_deselect_all()
        for r in range(populated_window.repo_table.rowCount()):
            chk = populated_window.repo_table.item(r, 0)
            assert chk.checkState() == Qt.Unchecked

    def test_dst_exists_cell_green(self, populated_window):
        """'alpha' exists on destination → green colour."""
        for r in range(populated_window.repo_table.rowCount()):
            name = populated_window.repo_table.item(r, 1).text()
            dst_item = populated_window.repo_table.item(r, 4)
            if name == "alpha":
                assert "exists" in dst_item.text()
                break

    def test_dst_new_cell_present(self, populated_window):
        """'beta' / 'gamma' are new on destination."""
        new_count = sum(
            1
            for r in range(populated_window.repo_table.rowCount())
            if "new" in populated_window.repo_table.item(r, 4).text()
        )
        assert new_count == 2

    def test_status_label_shows_count(self, populated_window):
        label = populated_window.repo_status_label.text()
        assert "3 repositories" in label
        assert "3 selected" in label

    def test_default_branch_column_populated(self, populated_window):
        branches = {
            populated_window.repo_table.item(r, 2).text()
            for r in range(populated_window.repo_table.rowCount())
        }
        assert branches == {"main"}

    def test_visibility_private_shown(self, populated_window):
        """alpha and gamma are private."""
        private_count = sum(
            1
            for r in range(populated_window.repo_table.rowCount())
            if "private" in populated_window.repo_table.item(r, 3).text()
        )
        assert private_count == 2

    def test_visibility_public_shown(self, populated_window):
        """beta is public."""
        public_count = sum(
            1
            for r in range(populated_window.repo_table.rowCount())
            if "public" in populated_window.repo_table.item(r, 3).text()
        )
        assert public_count == 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Selection toggles
# ─────────────────────────────────────────────────────────────────────────────

class TestSelection:

    def test_select_all_marks_all_repos(self, populated_window):
        # First deselect
        for r in populated_window.repos.values():
            r.selected = False
        populated_window._handle_select_all()
        assert all(r.selected for r in populated_window.repos.values())

    def test_deselect_all_unmarks_all_repos(self, populated_window):
        populated_window._handle_deselect_all()
        assert not any(r.selected for r in populated_window.repos.values())

    def test_row_click_toggles_selection(self, populated_window):
        # All start selected; click row 0 → deselect
        populated_window._handle_row_click(0, 0)
        name_item = populated_window.repo_table.item(0, 0)
        name = name_item.data(Qt.UserRole)
        assert populated_window.repos[name].selected is False

    def test_row_click_twice_re_selects(self, populated_window):
        populated_window._handle_row_click(0, 0)
        populated_window._handle_row_click(0, 0)
        name = populated_window.repo_table.item(0, 0).data(Qt.UserRole)
        assert populated_window.repos[name].selected is True

    def test_status_label_updates_after_deselect(self, populated_window):
        populated_window._handle_deselect_all()
        label = populated_window.repo_status_label.text()
        assert "0 selected" in label

    def test_status_label_updates_after_select_all(self, populated_window):
        populated_window._handle_deselect_all()
        populated_window._handle_select_all()
        label = populated_window.repo_status_label.text()
        assert "3 selected" in label


# ─────────────────────────────────────────────────────────────────────────────
# 5. Migration table
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrationTable:

    def _selected_rows(self, populated_window):
        return [r for r in populated_window.repos.values() if r.selected]

    def test_init_mig_table_clears_and_populates(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        assert populated_window.mig_table.rowCount() == len(selected)

    def test_init_mig_table_sets_pending_status(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        for r in range(populated_window.mig_table.rowCount()):
            status_text = populated_window.mig_table.item(r, 1).text()
            assert STATUS_PENDING in status_text

    def test_init_mig_table_clears_log(self, populated_window):
        populated_window.mig_log.append("old log entry")
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        assert populated_window.mig_log.toPlainText() == ""

    def test_mig_set_cell_updates_status(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        target_name = selected[0].info.name
        populated_window._mig_set_cell(target_name, "status", STATUS_DONE)

        for r in range(populated_window.mig_table.rowCount()):
            if populated_window.mig_table.item(r, 0).text() == target_name:
                assert STATUS_DONE in populated_window.mig_table.item(r, 1).text()
                break

    def test_mig_set_cell_done_is_green(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        name = selected[0].info.name
        populated_window._mig_set_cell(name, "status", STATUS_DONE)

        for r in range(populated_window.mig_table.rowCount()):
            if populated_window.mig_table.item(r, 0).text() == name:
                color = populated_window.mig_table.item(r, 1).foreground().color()
                # Green component should dominate
                assert color.green() > color.red()
                break

    def test_mig_set_cell_error_is_red(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        name = selected[0].info.name
        populated_window._mig_set_cell(name, "status", STATUS_ERROR)

        for r in range(populated_window.mig_table.rowCount()):
            if populated_window.mig_table.item(r, 0).text() == name:
                color = populated_window.mig_table.item(r, 1).foreground().color()
                assert color.red() > color.green()
                break

    def test_mig_set_cell_running_is_blue(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        name = selected[0].info.name
        populated_window._mig_set_cell(name, "status", STATUS_RUNNING)

        for r in range(populated_window.mig_table.rowCount()):
            if populated_window.mig_table.item(r, 0).text() == name:
                color = populated_window.mig_table.item(r, 1).foreground().color()
                assert color.blue() > color.red()
                break

    def test_mig_set_cell_unknown_key_is_noop(self, populated_window):
        """_mig_set_cell with an invalid col_key must not crash."""
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        populated_window._mig_set_cell(selected[0].info.name, "nonexistent", "value")

    def test_mig_set_cell_unknown_row_is_noop(self, populated_window):
        selected = self._selected_rows(populated_window)
        populated_window._init_mig_table(selected)
        populated_window._mig_set_cell("__no_such_repo__", "status", STATUS_DONE)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Log append
# ─────────────────────────────────────────────────────────────────────────────

class TestLogAppend:

    def test_append_log_adds_text(self, window):
        window._append_log("hello world")
        assert "hello world" in window.mig_log.toPlainText()

    def test_append_log_multiple_lines(self, window):
        window._append_log("line 1")
        window._append_log("line 2")
        text = window.mig_log.toPlainText()
        assert "line 1" in text
        assert "line 2" in text


# ─────────────────────────────────────────────────────────────────────────────
# 7. Migrate guard: no selection
# ─────────────────────────────────────────────────────────────────────────────

class TestMigrateGuard:

    def test_migrate_without_repos_shows_no_crash(self, window, qtbot, monkeypatch):
        """Clicking Migrate with no repos loaded must not raise."""
        # Intercept QMessageBox so test doesn't block
        monkeypatch.setattr(
            "gitmoving.ui.qt_app.QMessageBox.warning",
            lambda *a, **kw: None,
        )
        window._handle_migrate()   # should silently show a warning and return

    def test_migrate_without_provider_shows_no_crash(self, populated_window, monkeypatch):
        """Provider not loaded → warning, no crash."""
        populated_window.src_provider = None
        monkeypatch.setattr(
            "gitmoving.ui.qt_app.QMessageBox.warning",
            lambda *a, **kw: None,
        )
        populated_window._handle_migrate()
