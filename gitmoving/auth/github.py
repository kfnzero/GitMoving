"""GitHub authentication via Personal Access Token (PAT)."""

import os
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from .base import BaseAuth, Credentials

console = Console()


class GitHubAuth(BaseAuth):
    PROVIDER_NAME = "github"

    # GitHub.com default; self-hosted GitHub Enterprise uses a custom URL
    DEFAULT_API_URL = "https://api.github.com"

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url or self.DEFAULT_API_URL)

    def authenticate_interactive(self) -> Credentials:
        console.print(Panel(
            "[bold cyan]GitHub Authentication[/bold cyan]\n\n"
            "Please create a Personal Access Token (PAT) with the following scopes:\n"
            "  [green]repo[/green] (full repository access)\n\n"
            "Create one at: [link=https://github.com/settings/tokens/new]"
            "https://github.com/settings/tokens/new[/link]",
            title="[bold]GitHub Login[/bold]",
        ))

        base_url = self.base_url
        if click.confirm("Are you using GitHub Enterprise (self-hosted)?", default=False):
            host = click.prompt("  Enter GitHub Enterprise host (e.g. github.mycompany.com)")
            base_url = f"https://{host.rstrip('/')}/api/v3"

        token = click.prompt("  Paste your GitHub PAT", hide_input=True)

        return Credentials(
            provider=self.PROVIDER_NAME,
            token=token.strip(),
            base_url=base_url,
        )

    def _load_from_env(self) -> Optional[Credentials]:
        token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
        if token:
            return Credentials(
                provider=self.PROVIDER_NAME,
                token=token,
                base_url=self.base_url,
            )
        return None
