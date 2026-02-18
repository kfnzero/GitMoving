"""GitLab authentication via Personal Access Token (PAT)."""

import os
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from .base import BaseAuth, Credentials

console = Console()


class GitLabAuth(BaseAuth):
    PROVIDER_NAME = "gitlab"

    DEFAULT_BASE_URL = "https://gitlab.com"

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url or self.DEFAULT_BASE_URL)

    def authenticate_interactive(self) -> Credentials:
        console.print(Panel(
            "[bold cyan]GitLab Authentication[/bold cyan]\n\n"
            "Please create a Personal Access Token with the following scopes:\n"
            "  [green]api[/green]  (full API access)\n"
            "  [green]read_repository[/green]  (read source)\n"
            "  [green]write_repository[/green]  (write destination)\n\n"
            "Create one at: [link=https://gitlab.com/-/user_settings/personal_access_tokens]"
            "https://gitlab.com/-/user_settings/personal_access_tokens[/link]",
            title="[bold]GitLab Login[/bold]",
        ))

        base_url = self.base_url
        if click.confirm("Are you using a self-hosted GitLab instance?", default=False):
            host = click.prompt("  Enter GitLab host (e.g. gitlab.mycompany.com)")
            base_url = f"https://{host.rstrip('/')}"

        token = click.prompt("  Paste your GitLab PAT", hide_input=True)

        return Credentials(
            provider=self.PROVIDER_NAME,
            token=token.strip(),
            base_url=base_url,
        )

    def _load_from_env(self) -> Optional[Credentials]:
        token = os.environ.get("GITLAB_TOKEN") or os.environ.get("CI_JOB_TOKEN")
        if token:
            return Credentials(
                provider=self.PROVIDER_NAME,
                token=token,
                base_url=self.base_url,
            )
        return None
