"""Low-level git command runner using subprocess."""

import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from rich.console import Console

console = Console()


class GitRunner:
    """Thin wrapper around the local `git` binary."""

    def __init__(self, cwd: Optional[Path] = None, verbose: bool = False):
        self.cwd = cwd
        self.verbose = verbose

    def run(self, args: List[str], cwd: Optional[Path] = None, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git sub-command and return the CompletedProcess result."""
        cmd = ["git"] + args
        work_dir = str(cwd or self.cwd or ".")

        if self.verbose:
            console.print(f"  [dim]$ git {' '.join(args)}[/dim]")

        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
        )

        if check and result.returncode != 0:
            raise RuntimeError(
                f"git {' '.join(args)} failed (exit {result.returncode}):\n"
                f"{result.stderr.strip()}"
            )
        return result

    def clone_mirror(self, url: str, dest: Path) -> None:
        """
        Clone a repository as a bare mirror (all refs, branches, tags).
        Equivalent to: git clone --mirror <url> <dest>
        """
        self.run(["clone", "--mirror", url, str(dest)], cwd=dest.parent)

    def push_mirror(self, repo_dir: Path, url: str) -> None:
        """
        Push all refs from a bare mirror to the destination.
        Equivalent to: git push --mirror <url>
        """
        self.run(["push", "--mirror", url], cwd=repo_dir)

    def set_remote(self, repo_dir: Path, name: str, url: str) -> None:
        """Add or update a named remote."""
        # Remove if already exists
        check_result = self.run(
            ["remote", "get-url", name], cwd=repo_dir, check=False
        )
        if check_result.returncode == 0:
            self.run(["remote", "set-url", name, url], cwd=repo_dir)
        else:
            self.run(["remote", "add", name, url], cwd=repo_dir)

    def list_branches(self, repo_dir: Path) -> List[str]:
        """Return all branch names in the repository."""
        result = self.run(["branch", "-a", "--format=%(refname:short)"], cwd=repo_dir)
        return [b.strip() for b in result.stdout.splitlines() if b.strip()]

    def list_tags(self, repo_dir: Path) -> List[str]:
        """Return all tag names."""
        result = self.run(["tag", "--list"], cwd=repo_dir)
        return [t.strip() for t in result.stdout.splitlines() if t.strip()]

    def get_default_branch(self, repo_dir: Path) -> str:
        """Return the symbolic HEAD branch name."""
        result = self.run(
            ["symbolic-ref", "--short", "HEAD"], cwd=repo_dir, check=False
        )
        if result.returncode == 0:
            return result.stdout.strip()
        return "main"
