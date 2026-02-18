"""
GitMoving Qt GUI (PySide6)

Three-tab window:
  Setup        – configure source / destination platforms and credentials
  Repositories – browse repos, view destination status, select for migration
  Migration    – real-time progress per repository with log output
"""

from __future__ import annotations

import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QThread, Signal, QObject
from PySide6.QtGui import QColor, QFont, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QTabWidget,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QLabel,
    QLineEdit,
    QComboBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QHeaderView,
    QTextEdit,
    QFrame,
    QAbstractItemView,
    QMessageBox,
    QSizePolicy,
)

from ..auth import get_auth_handler
from ..auth.base import Credentials
from ..providers import get_provider
from ..providers.base import BaseProvider, RepoInfo
from ..utils.git import GitRunner

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS = [
    ("GitHub",    "github"),
    ("GitLab",    "gitlab"),
    ("Bitbucket", "bitbucket"),
]

STATUS_PENDING = "⏳ pending"
STATUS_RUNNING = "⟳ running"
STATUS_DONE    = "✓  done"
STATUS_ERROR   = "✗  error"

# ─────────────────────────────────────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RepoRow:
    info: RepoInfo
    selected: bool = True
    dst_exists: bool = False
    mig_status: str = STATUS_PENDING
    branches: str = "-"
    tags: str = "-"
    error: str = ""


def _make_credentials(
    side: str,
    params: dict,
    fallback: Optional[Credentials] = None,
) -> Credentials:
    """Build Credentials for 'src' or 'dst' from form params dict."""
    platform = params[f"{side}_platform"]
    token    = params[f"{side}_token"]
    username = params[f"{side}_username"] or None
    base_url = params[f"{side}_base_url"] or None

    if token:
        return Credentials(
            provider=platform,
            token=token    if platform != "bitbucket" else None,
            username=username,
            password=token if platform == "bitbucket" else None,
            base_url=base_url,
        )

    auth_cls = get_auth_handler(platform)
    auth_obj = auth_cls(base_url=base_url)

    env_creds = auth_obj._load_from_env()
    if env_creds:
        return env_creds

    saved = auth_obj.load_credentials()
    if saved:
        return saved

    if fallback and fallback.provider == platform:
        return Credentials(
            provider=platform,
            token=fallback.token,
            username=fallback.username,
            password=fallback.password,
            base_url=base_url or fallback.base_url,
        )

    raise ValueError(
        f"No credentials found for {side} ({platform}). "
        "Enter a token, set an environment variable, "
        "or run  gitmoving auth  from the terminal."
    )


# ─────────────────────────────────────────────────────────────────────────────
# Worker signals  (must live on a QObject, not on QThread directly)
# ─────────────────────────────────────────────────────────────────────────────

class LoaderSignals(QObject):
    status   = Signal(str)
    notify   = Signal(str)
    finished = Signal(dict)   # repo data dict
    error    = Signal(str)


class MigratorSignals(QObject):
    log         = Signal(str)
    cell_update = Signal(str, str, str)   # row_key, col_key, value
    finished    = Signal(int, int)        # done, errors


# ─────────────────────────────────────────────────────────────────────────────
# Background threads
# ─────────────────────────────────────────────────────────────────────────────

class LoaderThread(QThread):
    """Authenticate, list source repos, check destination in background."""

    def __init__(self, params: dict) -> None:
        super().__init__()
        self.params  = params
        self.signals = LoaderSignals()

    def run(self) -> None:
        params = self.params
        sig    = self.signals
        try:
            sig.status.emit("Authenticating…")
            src_creds = _make_credentials("src", params)
            dst_creds = _make_credentials("dst", params, fallback=src_creds)

            src_cls = get_provider(params["src_platform"])
            dst_cls = get_provider(params["dst_platform"])

            src_provider = src_cls(src_creds)
            dst_provider = dst_cls(dst_creds)

            src_user = src_provider.validate_credentials()
            dst_user = dst_provider.validate_credentials()

            src_owner = params["src_owner"] or src_user
            dst_owner = params["dst_owner"] or dst_user

            sig.notify.emit(
                f"Authenticated — "
                f"source: {params['src_platform']} ({src_user})  "
                f"destination: {params['dst_platform']} ({dst_user})"
            )
            sig.status.emit(f"Listing repos for {src_owner}…")

            repos = src_provider.list_repos(src_owner)

            sig.status.emit(f"Checking {len(repos)} repos on destination…")
            new_repos: Dict[str, RepoRow] = {}
            for repo in repos:
                exists = dst_provider.repo_exists(dst_owner, repo.name)
                new_repos[repo.name] = RepoRow(
                    info=repo, selected=True, dst_exists=exists
                )

            sig.finished.emit({
                "repos":        new_repos,
                "src_provider": src_provider,
                "dst_provider": dst_provider,
                "src_owner":    src_owner,
                "dst_owner":    dst_owner,
            })
            sig.status.emit(
                f"{len(repos)} repos loaded  ·  "
                f"{sum(1 for r in new_repos.values() if r.dst_exists)} already on destination"
            )

        except Exception as exc:
            sig.error.emit(str(exc))
            sig.status.emit(f"Error: {exc}")


class MigratorThread(QThread):
    """Migrate selected repos sequentially in background."""

    def __init__(
        self,
        selected:     List[RepoRow],
        src_provider: BaseProvider,
        dst_provider: BaseProvider,
        src_owner:    str,
        dst_owner:    str,
    ) -> None:
        super().__init__()
        self.selected     = selected
        self.src_provider = src_provider
        self.dst_provider = dst_provider
        self.src_owner    = src_owner
        self.dst_owner    = dst_owner
        self.signals      = MigratorSignals()

    def run(self) -> None:
        sig    = self.signals
        total  = len(self.selected)
        done   = 0
        errors = 0
        git    = GitRunner(verbose=False)

        for idx, row in enumerate(self.selected, 1):
            name = row.info.name
            sig.log.emit(f"[{idx}/{total}] Migrating  {name} …")
            sig.cell_update.emit(name, "status", STATUS_RUNNING)

            try:
                src_info = self.src_provider.get_repo(self.src_owner, name)

                if self.dst_provider.repo_exists(self.dst_owner, name):
                    sig.log.emit(f"  → Destination exists: {self.dst_owner}/{name}")
                    dst_info = self.dst_provider.get_repo(self.dst_owner, name)
                else:
                    dst_info = self.dst_provider.create_repo(
                        name=name,
                        owner=self.dst_owner,
                        description=src_info.description,
                        private=True,
                    )
                    sig.log.emit(f"  → Created: {self.dst_owner}/{name}")

                src_url = self.src_provider.get_authenticated_clone_url(src_info)
                dst_url = self.dst_provider.get_authenticated_clone_url(dst_info)

                with tempfile.TemporaryDirectory(prefix="gitmoving_") as tmp:
                    mirror = Path(tmp) / f"{name}.git"
                    sig.log.emit("  → Cloning (mirror)…")
                    git.clone_mirror(src_url, mirror)

                    branches = git.list_branches(mirror)
                    tags     = git.list_tags(mirror)
                    sig.log.emit(
                        f"  → Pushing  ({len(branches)} branches, {len(tags)} tags)…"
                    )
                    git.push_mirror(mirror, dst_url)

                done += 1
                row.mig_status = STATUS_DONE
                row.branches   = str(len(branches))
                row.tags       = str(len(tags))
                sig.cell_update.emit(name, "status",   STATUS_DONE)
                sig.cell_update.emit(name, "branches", str(len(branches)))
                sig.cell_update.emit(name, "tags",     str(len(tags)))
                sig.log.emit(f"  ✓  Done: {name}\n")

            except Exception as exc:
                errors += 1
                row.mig_status = STATUS_ERROR
                row.error      = str(exc)
                sig.cell_update.emit(name, "status", STATUS_ERROR)
                sig.cell_update.emit(name, "notes",  str(exc)[:80])
                sig.log.emit(f"  ✗  Error [{name}]: {exc}\n")

        sig.finished.emit(done, errors)


# ─────────────────────────────────────────────────────────────────────────────
# Main window
# ─────────────────────────────────────────────────────────────────────────────

# Migration table column indices
_MIG_COLS = {"name": 0, "status": 1, "branches": 2, "tags": 3, "notes": 4}


class GitMovingWindow(QMainWindow):

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("GitMoving – Repository Migration")
        self.resize(1060, 700)

        # Runtime state
        self.repos:              Dict[str, RepoRow] = {}
        self.src_provider:      Optional[BaseProvider] = None
        self.dst_provider:      Optional[BaseProvider] = None
        self.src_owner_resolved: str = ""
        self.dst_owner_resolved: str = ""
        self._loader:   Optional[LoaderThread]   = None
        self._migrator: Optional[MigratorThread] = None

        self._build_ui()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)

        self.tabs.addTab(self._build_setup_tab(),     "⚙  Setup")
        self.tabs.addTab(self._build_repos_tab(),     "📋  Repositories")
        self.tabs.addTab(self._build_migration_tab(), "🚀  Migration")

        self.statusBar().showMessage("Ready")

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _build_setup_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(6)

        # Source
        layout.addWidget(self._section_label("◀  Source Platform"))
        src_form = QFormLayout()
        src_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        src_form.setHorizontalSpacing(12)

        self.src_platform = self._platform_combo()
        self.src_owner    = QLineEdit()
        self.src_owner.setPlaceholderText("Username or organisation")
        self.src_token    = self._password_field("PAT  (leave blank → keyring / env var)")
        self.src_username = QLineEdit()
        self.src_username.setPlaceholderText("Bitbucket only")
        self.src_base_url = QLineEdit()
        self.src_base_url.setPlaceholderText("Self-hosted only, e.g. https://gitlab.myco.com")

        src_form.addRow("Platform:",     self.src_platform)
        src_form.addRow("Owner / Org:",  self.src_owner)
        src_form.addRow("Access Token:", self.src_token)
        src_form.addRow("Username:",     self.src_username)
        src_form.addRow("Base URL:",     self.src_base_url)
        layout.addLayout(src_form)

        layout.addWidget(self._divider())

        # Destination
        layout.addWidget(self._section_label("▶  Destination Platform"))
        dst_form = QFormLayout()
        dst_form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        dst_form.setHorizontalSpacing(12)

        self.dst_platform = self._platform_combo()
        self.dst_owner    = QLineEdit()
        self.dst_owner.setPlaceholderText("Leave blank → use token owner")
        self.dst_token    = self._password_field(
            "Leave blank → reuse source token if same platform"
        )
        self.dst_username = QLineEdit()
        self.dst_username.setPlaceholderText("Bitbucket only")
        self.dst_base_url = QLineEdit()
        self.dst_base_url.setPlaceholderText("Self-hosted only")

        dst_form.addRow("Platform:",     self.dst_platform)
        dst_form.addRow("Owner / Org:",  self.dst_owner)
        dst_form.addRow("Access Token:", self.dst_token)
        dst_form.addRow("Username:",     self.dst_username)
        dst_form.addRow("Base URL:",     self.dst_base_url)
        layout.addLayout(dst_form)

        layout.addStretch()

        # Action row
        action_row = QHBoxLayout()
        action_row.addStretch()
        self.btn_load = QPushButton("Load Repositories →")
        self.btn_load.setFixedHeight(34)
        self.btn_load.setMinimumWidth(180)
        self.btn_load.clicked.connect(self._handle_load)
        action_row.addWidget(self.btn_load)
        layout.addLayout(action_row)

        return w

    # ── Repositories tab ──────────────────────────────────────────────────────

    def _build_repos_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Toolbar
        toolbar = QHBoxLayout()
        self.repo_status_label = QLabel("No repositories loaded")
        toolbar.addWidget(self.repo_status_label)
        toolbar.addStretch()

        self.btn_all     = QPushButton("☑ All")
        self.btn_none    = QPushButton("☐ None")
        self.btn_migrate = QPushButton("▶  Migrate Selected")
        for btn in (self.btn_all, self.btn_none, self.btn_migrate):
            btn.setFixedHeight(30)
        self.btn_all.clicked.connect(self._handle_select_all)
        self.btn_none.clicked.connect(self._handle_deselect_all)
        self.btn_migrate.clicked.connect(self._handle_migrate)
        toolbar.addWidget(self.btn_all)
        toolbar.addWidget(self.btn_none)
        toolbar.addWidget(self.btn_migrate)
        layout.addLayout(toolbar)

        # Repository table
        self.repo_table = QTableWidget(0, 6)
        self.repo_table.setHorizontalHeaderLabels(
            ["", "Repository", "Branch", "Visibility", "Destination", "Description"]
        )
        hdr = self.repo_table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.Fixed)
        hdr.setSectionResizeMode(1, QHeaderView.Interactive)
        hdr.setSectionResizeMode(2, QHeaderView.Interactive)
        hdr.setSectionResizeMode(3, QHeaderView.Interactive)
        hdr.setSectionResizeMode(4, QHeaderView.Interactive)
        hdr.setSectionResizeMode(5, QHeaderView.Stretch)
        self.repo_table.setColumnWidth(0, 32)
        self.repo_table.setColumnWidth(1, 240)
        self.repo_table.setColumnWidth(2, 110)
        self.repo_table.setColumnWidth(3, 100)
        self.repo_table.setColumnWidth(4, 110)
        self.repo_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.repo_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.repo_table.setAlternatingRowColors(True)
        self.repo_table.verticalHeader().setVisible(False)
        self.repo_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.repo_table.cellClicked.connect(self._handle_row_click)
        layout.addWidget(self.repo_table)

        return w

    # ── Migration tab ─────────────────────────────────────────────────────────

    def _build_migration_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        # Progress table
        self.mig_table = QTableWidget(0, 5)
        self.mig_table.setHorizontalHeaderLabels(
            ["Repository", "Status", "Branches", "Tags", "Notes"]
        )
        mhdr = self.mig_table.horizontalHeader()
        mhdr.setSectionResizeMode(0, QHeaderView.Interactive)
        mhdr.setSectionResizeMode(1, QHeaderView.Interactive)
        mhdr.setSectionResizeMode(2, QHeaderView.Interactive)
        mhdr.setSectionResizeMode(3, QHeaderView.Interactive)
        mhdr.setSectionResizeMode(4, QHeaderView.Stretch)
        self.mig_table.setColumnWidth(0, 240)
        self.mig_table.setColumnWidth(1, 110)
        self.mig_table.setColumnWidth(2, 80)
        self.mig_table.setColumnWidth(3, 60)
        self.mig_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.mig_table.setAlternatingRowColors(True)
        self.mig_table.verticalHeader().setVisible(False)
        self.mig_table.setMaximumHeight(260)
        layout.addWidget(self.mig_table)

        # Log label + text area
        log_lbl = QLabel("Migration Log:")
        log_lbl.setStyleSheet("font-weight: bold; margin-top: 4px;")
        layout.addWidget(log_lbl)

        self.mig_log = QTextEdit()
        self.mig_log.setReadOnly(True)
        self.mig_log.setFont(QFont("Monospace", 9))
        layout.addWidget(self.mig_log)

        return w

    # ── Widget helpers ────────────────────────────────────────────────────────

    @staticmethod
    def _section_label(text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setStyleSheet("font-weight: bold; font-size: 13px; margin-top: 6px;")
        return lbl

    @staticmethod
    def _platform_combo() -> QComboBox:
        combo = QComboBox()
        for label, val in PROVIDERS:
            combo.addItem(label, val)
        return combo

    @staticmethod
    def _password_field(placeholder: str) -> QLineEdit:
        field = QLineEdit()
        field.setPlaceholderText(placeholder)
        field.setEchoMode(QLineEdit.Password)
        return field

    @staticmethod
    def _divider() -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setFrameShadow(QFrame.Sunken)
        return line

    # ── Form read ─────────────────────────────────────────────────────────────

    def _read_form(self) -> dict:
        return {
            "src_platform": self.src_platform.currentData(),
            "src_owner":    self.src_owner.text().strip(),
            "src_token":    self.src_token.text().strip(),
            "src_username": self.src_username.text().strip(),
            "src_base_url": self.src_base_url.text().strip() or None,
            "dst_platform": self.dst_platform.currentData(),
            "dst_owner":    self.dst_owner.text().strip(),
            "dst_token":    self.dst_token.text().strip(),
            "dst_username": self.dst_username.text().strip(),
            "dst_base_url": self.dst_base_url.text().strip() or None,
        }

    # ── Repository table rebuild ──────────────────────────────────────────────

    def _rebuild_repo_table(self) -> None:
        self.repo_table.setRowCount(0)
        selected_count = 0

        for name, row in self.repos.items():
            if row.selected:
                selected_count += 1

            r = self.repo_table.rowCount()
            self.repo_table.insertRow(r)

            # Checkbox column
            chk = QTableWidgetItem()
            chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
            chk.setCheckState(Qt.Checked if row.selected else Qt.Unchecked)
            chk.setData(Qt.UserRole, name)
            self.repo_table.setItem(r, 0, chk)

            self.repo_table.setItem(r, 1, QTableWidgetItem(name))
            self.repo_table.setItem(r, 2, QTableWidgetItem(row.info.default_branch))

            vis_item = QTableWidgetItem(
                "🔒 private" if row.info.private else "🌐 public"
            )
            if not row.info.private:
                vis_item.setForeground(QColor("#0099cc"))
            self.repo_table.setItem(r, 3, vis_item)

            if row.dst_exists:
                dst_item = QTableWidgetItem("✓  exists")
                dst_item.setForeground(QColor("#22aa22"))
            else:
                dst_item = QTableWidgetItem("✗  new")
                dst_item.setForeground(QColor("#cc8800"))
            self.repo_table.setItem(r, 4, dst_item)

            self.repo_table.setItem(r, 5, QTableWidgetItem((row.info.description or "")[:80]))

        total = len(self.repos)
        self.repo_status_label.setText(
            f"{total} repositories  ·  {selected_count} selected  ·  "
            "click a row to toggle selection"
        )

    # ── Migration table helpers ────────────────────────────────────────────────

    def _init_mig_table(self, selected: List[RepoRow]) -> None:
        self.mig_table.setRowCount(0)
        self.mig_log.clear()
        for row in selected:
            row.mig_status = STATUS_PENDING
            row.branches   = "-"
            row.tags       = "-"
            row.error      = ""
            r = self.mig_table.rowCount()
            self.mig_table.insertRow(r)
            self.mig_table.setItem(r, 0, QTableWidgetItem(row.info.name))
            self.mig_table.setItem(r, 1, QTableWidgetItem(STATUS_PENDING))
            self.mig_table.setItem(r, 2, QTableWidgetItem("-"))
            self.mig_table.setItem(r, 3, QTableWidgetItem("-"))
            self.mig_table.setItem(r, 4, QTableWidgetItem(""))

    def _mig_set_cell(self, row_key: str, col_key: str, value: str) -> None:
        col = _MIG_COLS.get(col_key)
        if col is None:
            return
        for r in range(self.mig_table.rowCount()):
            name_item = self.mig_table.item(r, 0)
            if name_item and name_item.text() == row_key:
                cell = QTableWidgetItem(value)
                if col_key == "status":
                    if value == STATUS_DONE:
                        cell.setForeground(QColor("#22aa22"))
                    elif value == STATUS_ERROR:
                        cell.setForeground(QColor("#cc2222"))
                    elif value == STATUS_RUNNING:
                        cell.setForeground(QColor("#0077cc"))
                self.mig_table.setItem(r, col, cell)
                break

    # ── Event handlers ────────────────────────────────────────────────────────

    def _handle_load(self) -> None:
        params = self._read_form()
        self.btn_load.setEnabled(False)
        self.btn_load.setText("Loading…")
        self.statusBar().showMessage("Connecting…")

        self._loader = LoaderThread(params)
        sig = self._loader.signals
        sig.status.connect(self.statusBar().showMessage)
        sig.notify.connect(lambda m: self.statusBar().showMessage(m, 8000))
        sig.finished.connect(self._on_repos_loaded)
        sig.error.connect(self._on_load_error)
        self._loader.finished.connect(self._on_loader_thread_done)
        self._loader.start()

    def _on_loader_thread_done(self) -> None:
        self.btn_load.setEnabled(True)
        self.btn_load.setText("Load Repositories →")

    def _on_repos_loaded(self, result: dict) -> None:
        self.repos               = result["repos"]
        self.src_provider        = result["src_provider"]
        self.dst_provider        = result["dst_provider"]
        self.src_owner_resolved  = result["src_owner"]
        self.dst_owner_resolved  = result["dst_owner"]
        self._rebuild_repo_table()
        self.tabs.setCurrentIndex(1)

    def _on_load_error(self, msg: str) -> None:
        QMessageBox.critical(self, "Load Error", msg)

    def _handle_select_all(self) -> None:
        for row in self.repos.values():
            row.selected = True
        self._rebuild_repo_table()

    def _handle_deselect_all(self) -> None:
        for row in self.repos.values():
            row.selected = False
        self._rebuild_repo_table()

    def _handle_row_click(self, r: int, _col: int) -> None:
        """Toggle the selection of the clicked row."""
        chk_item = self.repo_table.item(r, 0)
        if chk_item is None:
            return
        name = chk_item.data(Qt.UserRole)
        if name and name in self.repos:
            self.repos[name].selected = not self.repos[name].selected
            self._rebuild_repo_table()

    def _handle_migrate(self) -> None:
        selected = [r for r in self.repos.values() if r.selected]
        if not selected:
            QMessageBox.warning(self, "No Selection", "No repositories selected!")
            return
        if self.src_provider is None or self.dst_provider is None:
            QMessageBox.warning(self, "Not Loaded", "Please load repositories first.")
            return

        dst_owner = self.dst_owner.text().strip() or self.dst_owner_resolved
        self._init_mig_table(selected)
        self.tabs.setCurrentIndex(2)

        self._migrator = MigratorThread(
            selected,
            self.src_provider,
            self.dst_provider,
            self.src_owner_resolved,
            dst_owner,
        )
        sig = self._migrator.signals
        sig.log.connect(self._append_log)
        sig.cell_update.connect(self._mig_set_cell)
        sig.finished.connect(self._on_migration_finished)
        self._migrator.start()

    def _append_log(self, msg: str) -> None:
        self.mig_log.append(msg)
        self.mig_log.moveCursor(QTextCursor.End)

    def _on_migration_finished(self, done: int, errors: int) -> None:
        icon = "✓" if errors == 0 else "⚠"
        self.statusBar().showMessage(
            f"{icon} Migration complete — {done} succeeded, {errors} failed"
        )
        QMessageBox.information(
            self,
            "Migration Complete",
            f"Succeeded: {done}\nFailed:    {errors}",
        )


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def run_qt_app() -> None:
    """Launch the PySide6 GUI. Called from cli.py."""
    app = QApplication.instance() or QApplication(sys.argv)
    window = GitMovingWindow()
    window.show()
    sys.exit(app.exec())
