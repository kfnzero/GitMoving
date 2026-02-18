"""
GitMoving Terminal UI

Three-tab Textual application:
  Setup       – configure source / destination providers and credentials
  Repositories – browse repos, view destination status, select for migration
  Migration   – real-time progress per repository with log output
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    Log,
    Select,
    Static,
    TabbedContent,
    TabPane,
)

from ..auth import get_auth_handler
from ..auth.base import Credentials
from ..providers import get_provider
from ..providers.base import BaseProvider, RepoInfo
from ..utils.git import GitRunner

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

PROVIDERS: List[tuple] = [
    ("GitHub", "github"),
    ("GitLab", "gitlab"),
    ("Bitbucket", "bitbucket"),
]

STATUS_PENDING = "⏳ pending"
STATUS_RUNNING = "⟳ running"
STATUS_DONE    = "✓  done"
STATUS_ERROR   = "✗  error"
STATUS_SKIP    = "—  skip"


# ─────────────────────────────────────────────────────────────────────────────
# Internal state
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class RepoRow:
    """Holds display state for one repository in the selection table."""
    info: RepoInfo
    selected: bool = True
    dst_exists: bool = False
    mig_status: str = STATUS_PENDING
    branches: str = "-"
    tags: str = "-"
    error: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# App
# ─────────────────────────────────────────────────────────────────────────────

class GitMovingApp(App[None]):
    """GitMoving – cross-platform repository migration tool."""

    TITLE = "GitMoving"
    SUB_TITLE = "Private repository migration"

    CSS = """
    Screen {
        background: $surface;
    }

    TabbedContent {
        height: 1fr;
    }

    TabPane {
        padding: 1 2;
    }

    /* ── Setup tab ── */
    .section-heading {
        text-style: bold;
        color: $accent;
        margin: 1 0 0 0;
        padding: 0;
    }

    .form-row {
        height: 3;
        margin-bottom: 0;
    }

    .field-label {
        width: 22;
        padding-top: 1;
        color: $text-muted;
    }

    Input, Select {
        width: 1fr;
    }

    .divider {
        height: 1;
        border-bottom: dashed $panel;
        margin: 1 0;
    }

    /* ── Repo tab toolbar ── */
    #repo-toolbar {
        height: 3;
        align: right middle;
        padding: 0 0 0 1;
    }

    #repo-status {
        width: 1fr;
        color: $text-muted;
        padding-top: 1;
    }

    /* ── Tables ── */
    #repo-table {
        height: 1fr;
    }

    #mig-table {
        height: 14;
    }

    /* ── Migration log ── */
    #mig-log {
        height: 1fr;
        border: solid $accent;
        margin-top: 1;
    }

    /* ── Buttons ── */
    Button {
        margin-left: 1;
    }

    #btn-load {
        margin-top: 1;
    }

    /* ── Setup action bar ── */
    .setup-actions {
        height: 3;
        align: right middle;
        margin-top: 1;
    }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("ctrl+r", "reload", "Reload repos"),
    ]

    # ── Reactive counters used only to trigger watchers (not rendered directly)
    _loaded_count: reactive[int] = reactive(0)

    # ── Runtime state
    src_provider: Optional[BaseProvider] = None
    dst_provider: Optional[BaseProvider] = None
    src_owner_resolved: str = ""
    dst_owner_resolved: str = ""
    repos: Dict[str, RepoRow] = {}   # keyed by repo name

    # ─────────────────────────────────────────────────────────────────────────
    # Compose
    # ─────────────────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(id="tabs", initial="tab-setup"):
            with TabPane("⚙  Setup", id="tab-setup"):
                yield from self._compose_setup()
            with TabPane("📋  Repositories", id="tab-repos"):
                yield from self._compose_repos()
            with TabPane("🚀  Migration", id="tab-migration"):
                yield from self._compose_migration()
        yield Footer()

    # ── Setup tab ─────────────────────────────────────────────────────────────

    def _compose_setup(self) -> ComposeResult:
        with Vertical():
            # Source
            yield Static("◀  Source Platform", classes="section-heading")
            with Horizontal(classes="form-row"):
                yield Label("Platform:", classes="field-label")
                yield Select(PROVIDERS, id="src-platform", value="github")
            with Horizontal(classes="form-row"):
                yield Label("Owner / Org:", classes="field-label")
                yield Input(placeholder="Username or organisation", id="src-owner")
            with Horizontal(classes="form-row"):
                yield Label("Access Token:", classes="field-label")
                yield Input(
                    placeholder="PAT  (leave blank → keyring / env var)",
                    id="src-token", password=True,
                )
            with Horizontal(classes="form-row"):
                yield Label("Username:", classes="field-label")
                yield Input(placeholder="Bitbucket only", id="src-username")
            with Horizontal(classes="form-row"):
                yield Label("Base URL:", classes="field-label")
                yield Input(
                    placeholder="Self-hosted only, e.g. https://gitlab.myco.com",
                    id="src-base-url",
                )

            yield Static("", classes="divider")

            # Destination
            yield Static("▶  Destination Platform", classes="section-heading")
            with Horizontal(classes="form-row"):
                yield Label("Platform:", classes="field-label")
                yield Select(PROVIDERS, id="dst-platform", value="github")
            with Horizontal(classes="form-row"):
                yield Label("Owner / Org:", classes="field-label")
                yield Input(
                    placeholder="Leave blank → use token owner",
                    id="dst-owner",
                )
            with Horizontal(classes="form-row"):
                yield Label("Access Token:", classes="field-label")
                yield Input(
                    placeholder="Leave blank → reuse source token if same platform",
                    id="dst-token", password=True,
                )
            with Horizontal(classes="form-row"):
                yield Label("Username:", classes="field-label")
                yield Input(placeholder="Bitbucket only", id="dst-username")
            with Horizontal(classes="form-row"):
                yield Label("Base URL:", classes="field-label")
                yield Input(placeholder="Self-hosted only", id="dst-base-url")

            with Horizontal(classes="setup-actions"):
                yield Button(
                    "Load Repositories →", id="btn-load", variant="primary"
                )

    # ── Repositories tab ──────────────────────────────────────────────────────

    def _compose_repos(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="repo-toolbar"):
                yield Static("", id="repo-status")
                yield Button("☑ All",   id="btn-all",     variant="default")
                yield Button("☐ None",  id="btn-none",    variant="default")
                yield Button(
                    "▶ Migrate Selected", id="btn-migrate", variant="success"
                )
            yield DataTable(id="repo-table", cursor_type="row", zebra_stripes=True)

    # ── Migration tab ─────────────────────────────────────────────────────────

    def _compose_migration(self) -> ComposeResult:
        with Vertical():
            yield DataTable(id="mig-table", cursor_type="none", zebra_stripes=True)
            yield Log(id="mig-log", auto_scroll=True)

    # ─────────────────────────────────────────────────────────────────────────
    # Mount – initialise table columns
    # ─────────────────────────────────────────────────────────────────────────

    def on_mount(self) -> None:
        rt = self.query_one("#repo-table", DataTable)
        rt.add_column("",            key="sel",     width=3)
        rt.add_column("Repository",  key="name",    width=32)
        rt.add_column("Branch",      key="branch",  width=14)
        rt.add_column("Visibility",  key="vis",     width=10)
        rt.add_column("Destination", key="dst",     width=14)
        rt.add_column("Description", key="desc")

        mt = self.query_one("#mig-table", DataTable)
        mt.add_column("Repository",  key="name",     width=32)
        mt.add_column("Status",      key="status",   width=14)
        mt.add_column("Branches",    key="branches", width=10)
        mt.add_column("Tags",        key="tags",     width=8)
        mt.add_column("Notes",       key="notes")

    # ─────────────────────────────────────────────────────────────────────────
    # Event handlers
    # ─────────────────────────────────────────────────────────────────────────

    @on(Button.Pressed, "#btn-load")
    def handle_load(self) -> None:
        """Read form data (main thread) then start background loader."""
        params = self._read_form()
        self._load_repos_worker(params)

    @on(Button.Pressed, "#btn-all")
    def handle_select_all(self) -> None:
        for row in self.repos.values():
            row.selected = True
        self._rebuild_repo_table()

    @on(Button.Pressed, "#btn-none")
    def handle_deselect_all(self) -> None:
        for row in self.repos.values():
            row.selected = False
        self._rebuild_repo_table()

    @on(Button.Pressed, "#btn-migrate")
    def handle_migrate(self) -> None:
        selected = [r for r in self.repos.values() if r.selected]
        if not selected:
            self.notify("No repositories selected!", severity="warning")
            return
        dst_owner = (
            self.query_one("#dst-owner", Input).value.strip()
            or self.dst_owner_resolved
        )
        self._init_mig_table(selected)
        self._switch_tab("tab-migration")
        self._run_migrations_worker(selected, dst_owner)

    @on(DataTable.RowSelected, "#repo-table")
    def handle_row_click(self, event: DataTable.RowSelected) -> None:
        """Toggle selection when user clicks a row."""
        key = str(event.row_key.value)
        if key in self.repos:
            self.repos[key].selected = not self.repos[key].selected
            self._rebuild_repo_table()

    def action_reload(self) -> None:
        params = self._read_form()
        self._load_repos_worker(params)

    # ─────────────────────────────────────────────────────────────────────────
    # Background workers
    # ─────────────────────────────────────────────────────────────────────────

    @work(thread=True, exclusive=True, name="loader")
    def _load_repos_worker(self, params: dict) -> None:
        """Authenticate, list source repos and check destination existence."""

        def notify(msg: str, sev: str = "information") -> None:
            self.call_from_thread(self.notify, msg, severity=sev, timeout=7)

        def status(msg: str) -> None:
            self.call_from_thread(self._set_repo_status, msg)

        status("Authenticating…")
        try:
            src_creds = self._make_credentials("src", params)
            dst_creds = self._make_credentials("dst", params, fallback=src_creds)

            src_cls = get_provider(params["src_platform"])
            dst_cls = get_provider(params["dst_platform"])

            self.src_provider = src_cls(src_creds)
            self.dst_provider = dst_cls(dst_creds)

            src_user = self.src_provider.validate_credentials()
            dst_user = self.dst_provider.validate_credentials()

            self.src_owner_resolved = params["src_owner"] or src_user
            self.dst_owner_resolved = params["dst_owner"] or dst_user

            notify(
                f"✓  Authenticated — "
                f"source: {params['src_platform']} ({src_user})  "
                f"destination: {params['dst_platform']} ({dst_user})"
            )
            status(f"Listing repos for {self.src_owner_resolved}…")

            repos = self.src_provider.list_repos(self.src_owner_resolved)

            status(f"Checking {len(repos)} repos on destination…")
            new_repos: Dict[str, RepoRow] = {}
            for repo in repos:
                exists = self.dst_provider.repo_exists(
                    self.dst_owner_resolved, repo.name
                )
                new_repos[repo.name] = RepoRow(
                    info=repo, selected=True, dst_exists=exists
                )

            self.repos = new_repos
            self.call_from_thread(self._rebuild_repo_table)
            self.call_from_thread(self._switch_tab, "tab-repos")
            status(
                f"{len(repos)} repos loaded  ·  "
                f"{sum(1 for r in new_repos.values() if r.dst_exists)} already on destination"
            )

        except Exception as exc:
            notify(f"Error: {exc}", sev="error")
            status(f"Error: {exc}")

    @work(thread=True, name="migrator")
    def _run_migrations_worker(
        self, selected: List[RepoRow], dst_owner: str
    ) -> None:
        """Migrate each selected repository sequentially."""

        def log(msg: str) -> None:
            self.call_from_thread(
                lambda m=msg: self.query_one("#mig-log", Log).write_line(m)
            )

        def set_cell(row_key: str, col_key: str, val: object) -> None:
            self.call_from_thread(self._mig_set_cell, row_key, col_key, val)

        total   = len(selected)
        done    = 0
        errors  = 0
        git     = GitRunner(verbose=False)

        for idx, row in enumerate(selected, 1):
            name = row.info.name
            log(f"[{idx}/{total}] Migrating  {name} …")
            set_cell(name, "status", STATUS_RUNNING)

            try:
                # ── Source repo info
                src_info = self.src_provider.get_repo(
                    self.src_owner_resolved, name
                )

                # ── Ensure destination exists
                if self.dst_provider.repo_exists(dst_owner, name):
                    log(f"  → Destination exists: {dst_owner}/{name}")
                    dst_info = self.dst_provider.get_repo(dst_owner, name)
                else:
                    dst_info = self.dst_provider.create_repo(
                        name=name,
                        owner=dst_owner,
                        description=src_info.description,
                        private=True,
                    )
                    log(f"  → Created: {dst_owner}/{name}")

                src_url = self.src_provider.get_authenticated_clone_url(src_info)
                dst_url = self.dst_provider.get_authenticated_clone_url(dst_info)

                # ── Mirror clone + push
                with tempfile.TemporaryDirectory(prefix="gitmoving_") as tmp:
                    mirror = Path(tmp) / f"{name}.git"
                    log("  → Cloning (mirror)…")
                    git.clone_mirror(src_url, mirror)

                    branches = git.list_branches(mirror)
                    tags     = git.list_tags(mirror)
                    log(f"  → Pushing  ({len(branches)} branches, {len(tags)} tags)…")
                    git.push_mirror(mirror, dst_url)

                done += 1
                row.mig_status = STATUS_DONE
                row.branches   = str(len(branches))
                row.tags       = str(len(tags))
                set_cell(name, "status",   STATUS_DONE)
                set_cell(name, "branches", str(len(branches)))
                set_cell(name, "tags",     str(len(tags)))
                log(f"  ✓  Done: {name}\n")

            except Exception as exc:
                errors += 1
                row.mig_status = STATUS_ERROR
                row.error      = str(exc)
                set_cell(name, "status", STATUS_ERROR)
                set_cell(name, "notes",  str(exc)[:70])
                log(f"  ✗  Error [{name}]: {exc}\n")

        sev = "information" if errors == 0 else "warning"
        self.call_from_thread(
            self.notify,
            f"Migration complete — {done} succeeded, {errors} failed",
            severity=sev,
            timeout=10,
        )

    # ─────────────────────────────────────────────────────────────────────────
    # UI helpers  (must run on main thread)
    # ─────────────────────────────────────────────────────────────────────────

    def _rebuild_repo_table(self) -> None:
        """Repopulate the repository DataTable from self.repos."""
        table = self.query_one("#repo-table", DataTable)
        table.clear()

        selected_count = 0
        for name, row in self.repos.items():
            if row.selected:
                selected_count += 1

            check = "☑" if row.selected else "☐"
            vis   = Text("🔒 private", style="dim") if row.info.private else Text("🌐 public",  style="cyan")

            if row.dst_exists:
                dst_cell = Text("✓  exists", style="green")
            else:
                dst_cell = Text("✗  new",    style="yellow")

            desc = (row.info.description or "")[:60]

            table.add_row(
                check,
                name,
                row.info.default_branch,
                vis,
                dst_cell,
                desc,
                key=name,
            )

        total = len(self.repos)
        self._set_repo_status(
            f"{total} repositories  ·  {selected_count} selected  ·  "
            "click a row to toggle"
        )

    def _set_repo_status(self, text: str) -> None:
        self.query_one("#repo-status", Static).update(text)

    def _switch_tab(self, tab_id: str) -> None:
        self.query_one("#tabs", TabbedContent).active = tab_id

    def _init_mig_table(self, selected: List[RepoRow]) -> None:
        """Prepare the migration progress table before starting workers."""
        mt = self.query_one("#mig-table", DataTable)
        mt.clear()
        log = self.query_one("#mig-log", Log)
        log.clear()

        for row in selected:
            row.mig_status = STATUS_PENDING
            row.branches   = "-"
            row.tags       = "-"
            row.error      = ""
            mt.add_row(
                row.info.name,
                STATUS_PENDING,
                "-", "-", "",
                key=row.info.name,
            )

    def _mig_set_cell(self, row_key: str, col_key: str, value: object) -> None:
        """Thread-safe cell update for the migration table."""
        try:
            self.query_one("#mig-table", DataTable).update_cell(
                row_key, col_key, value, update_width=False
            )
        except Exception:
            pass

    # ─────────────────────────────────────────────────────────────────────────
    # Credential helpers
    # ─────────────────────────────────────────────────────────────────────────

    def _read_form(self) -> dict:
        """Read all form widget values (call from main thread only)."""
        def val(wid: str, cls=Input) -> str:
            return self.query_one(wid, cls).value  # type: ignore[attr-defined]

        return {
            "src_platform": val("#src-platform", Select),
            "src_owner":    val("#src-owner").strip(),
            "src_token":    val("#src-token").strip(),
            "src_username": val("#src-username").strip(),
            "src_base_url": val("#src-base-url").strip() or None,
            "dst_platform": val("#dst-platform", Select),
            "dst_owner":    val("#dst-owner").strip(),
            "dst_token":    val("#dst-token").strip(),
            "dst_username": val("#dst-username").strip(),
            "dst_base_url": val("#dst-base-url").strip() or None,
        }

    def _make_credentials(
        self,
        side: str,
        params: dict,
        fallback: Optional[Credentials] = None,
    ) -> Credentials:
        """Build a Credentials object for 'src' or 'dst' from form params."""
        platform  = params[f"{side}_platform"]
        token     = params[f"{side}_token"]
        username  = params[f"{side}_username"] or None
        base_url  = params[f"{side}_base_url"]

        # 1. User entered a token directly
        if token:
            return Credentials(
                provider=platform,
                token=token    if platform != "bitbucket" else None,
                username=username,
                password=token if platform == "bitbucket" else None,
                base_url=base_url,
            )

        # 2. Try environment variables
        auth_cls = get_auth_handler(platform)
        auth_obj = auth_cls(base_url=base_url)
        env_creds = auth_obj._load_from_env()
        if env_creds:
            return env_creds

        # 3. Try saved keyring
        saved = auth_obj.load_credentials()
        if saved:
            return saved

        # 4. Re-use source credentials if same platform (destination only)
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
