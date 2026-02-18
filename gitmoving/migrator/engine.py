"""Core migration engine: orchestrates clone → create → push."""

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, TimeElapsedColumn

from ..providers.base import BaseProvider, RepoInfo
from ..utils.git import GitRunner

console = Console()


@dataclass
class MigrationConfig:
    """Parameters that control a single repository migration."""

    # Source
    src_provider: BaseProvider
    src_owner: str
    src_repo: str

    # Destination
    dst_provider: BaseProvider
    dst_owner: Optional[str] = None   # Defaults to the authenticated user
    dst_repo: Optional[str] = None    # Defaults to src_repo name

    # Behaviour flags
    create_if_missing: bool = True    # Create destination repo if it doesn't exist
    force_push: bool = False          # Allow overwriting existing refs at destination
    verbose: bool = False


class MigrationEngine:
    """Executes repository migration while preserving full git history."""

    def __init__(self, config: MigrationConfig):
        self.cfg = config
        self.git = GitRunner(verbose=config.verbose)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(self) -> None:
        """Execute the full migration pipeline."""
        cfg = self.cfg

        dst_repo_name = cfg.dst_repo or cfg.src_repo
        dst_owner = cfg.dst_owner

        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            TimeElapsedColumn(),
            console=console,
            transient=True,
        ) as progress:

            # 1. Validate source credentials and locate the repo
            task = progress.add_task("Validating source credentials…")
            src_username = cfg.src_provider.validate_credentials()
            console.print(f"  [green]✓[/green] Source authenticated as [bold]{src_username}[/bold]")
            progress.remove_task(task)

            task = progress.add_task(f"Fetching source repo metadata: {cfg.src_owner}/{cfg.src_repo}…")
            src_info = cfg.src_provider.get_repo(cfg.src_owner, cfg.src_repo)
            console.print(
                f"  [green]✓[/green] Source: [bold]{src_info.full_name}[/bold] "
                f"({'private' if src_info.private else 'public'})"
            )
            progress.remove_task(task)

            # 2. Validate destination credentials
            task = progress.add_task("Validating destination credentials…")
            dst_username = cfg.dst_provider.validate_credentials()
            console.print(f"  [green]✓[/green] Destination authenticated as [bold]{dst_username}[/bold]")
            progress.remove_task(task)

            # Resolve destination owner (default to authenticated user)
            if not dst_owner:
                dst_owner = dst_username

            # 3. Create destination repository if required
            task = progress.add_task(f"Checking destination repo: {dst_owner}/{dst_repo_name}…")
            dst_info = self._ensure_destination(dst_owner, dst_repo_name, src_info)
            progress.remove_task(task)

            # 4. Mirror-clone the source repository
            with tempfile.TemporaryDirectory(prefix="gitmoving_") as tmpdir:
                mirror_path = Path(tmpdir) / f"{cfg.src_repo}.git"

                src_clone_url = cfg.src_provider.get_authenticated_clone_url(src_info)
                task = progress.add_task("Cloning source repository (mirror)…")
                self._clone_source(src_clone_url, mirror_path)
                progress.remove_task(task)

                branch_count = len(self.git.list_branches(mirror_path))
                tag_count = len(self.git.list_tags(mirror_path))
                console.print(
                    f"  [green]✓[/green] Cloned [bold]{branch_count}[/bold] branch(es), "
                    f"[bold]{tag_count}[/bold] tag(s)"
                )

                # 5. Push to destination
                dst_push_url = cfg.dst_provider.get_authenticated_clone_url(dst_info)
                task = progress.add_task("Pushing to destination (all refs)…")
                self._push_to_destination(mirror_path, dst_push_url)
                progress.remove_task(task)

        console.print()
        console.print(
            f"[bold green]Migration complete![/bold green]\n"
            f"  Source:      {src_info.full_name}\n"
            f"  Destination: {dst_info.full_name}\n"
            f"\n[dim]Note: Team permissions must be configured manually on the destination.[/dim]"
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_destination(
        self, dst_owner: str, dst_repo_name: str, src_info: RepoInfo
    ) -> RepoInfo:
        cfg = self.cfg

        if cfg.dst_provider.repo_exists(dst_owner, dst_repo_name):
            dst_info = cfg.dst_provider.get_repo(dst_owner, dst_repo_name)
            console.print(
                f"  [yellow]![/yellow] Destination repo already exists: [bold]{dst_info.full_name}[/bold]"
            )
            if not cfg.force_push:
                console.print(
                    "  [yellow]![/yellow] Use [bold]--force[/bold] if you want to overwrite existing refs."
                )
        else:
            if not cfg.create_if_missing:
                raise RuntimeError(
                    f"Destination repository '{dst_owner}/{dst_repo_name}' does not exist "
                    "and --no-create was specified."
                )
            dst_info = cfg.dst_provider.create_repo(
                name=dst_repo_name,
                owner=dst_owner,
                description=src_info.description,
                private=True,  # Always private (core requirement)
            )
            console.print(
                f"  [green]✓[/green] Created destination repo: [bold]{dst_info.full_name}[/bold]"
            )

        return dst_info

    def _clone_source(self, url: str, dest: Path) -> None:
        """Clone source as a bare mirror into dest."""
        try:
            self.git.clone_mirror(url, dest)
        except RuntimeError as exc:
            raise RuntimeError(f"Failed to clone source repository: {exc}") from exc

    def _push_to_destination(self, mirror_path: Path, dst_url: str) -> None:
        """Push all refs from the mirror to the destination."""
        # Update the push remote
        self.git.set_remote(mirror_path, "destination", dst_url)
        try:
            if self.cfg.force_push:
                self.git.run(["push", "--force", "--mirror", dst_url], cwd=mirror_path)
            else:
                self.git.push_mirror(mirror_path, dst_url)
        except RuntimeError as exc:
            raise RuntimeError(f"Failed to push to destination: {exc}") from exc
