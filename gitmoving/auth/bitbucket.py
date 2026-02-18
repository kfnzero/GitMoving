"""Bitbucket authentication via App Password or Repository Access Token."""

import os
from typing import Optional

import click
from rich.console import Console
from rich.panel import Panel

from .base import BaseAuth, Credentials

console = Console()


class BitbucketAuth(BaseAuth):
    PROVIDER_NAME = "bitbucket"

    DEFAULT_API_URL = "https://api.bitbucket.org/2.0"

    def __init__(self, base_url: Optional[str] = None):
        super().__init__(base_url or self.DEFAULT_API_URL)

    def authenticate_interactive(self) -> Credentials:
        console.print(Panel(
            "[bold cyan]Bitbucket Authentication[/bold cyan]\n\n"
            "Please create an App Password with the following permissions:\n"
            "  [green]Repositories: Read, Write, Admin[/green]\n\n"
            "Create one at: [link=https://bitbucket.org/account/settings/app-passwords/new]"
            "https://bitbucket.org/account/settings/app-passwords/new[/link]\n\n"
            "You will need both your [bold]username[/bold] and the [bold]app password[/bold].",
            title="[bold]Bitbucket Login[/bold]",
        ))

        is_server = click.confirm(
            "Are you using Bitbucket Data Center / Server (self-hosted)?", default=False
        )

        base_url = self.base_url
        if is_server:
            host = click.prompt("  Enter Bitbucket host (e.g. bitbucket.mycompany.com)")
            base_url = f"https://{host.rstrip('/')}/rest/api/1.0"

        username = click.prompt("  Bitbucket username")
        password = click.prompt(
            "  App Password (or HTTP access token for Data Center)", hide_input=True
        )

        return Credentials(
            provider=self.PROVIDER_NAME,
            username=username.strip(),
            password=password.strip(),
            base_url=base_url,
        )

    def _load_from_env(self) -> Optional[Credentials]:
        username = os.environ.get("BITBUCKET_USERNAME")
        password = os.environ.get("BITBUCKET_APP_PASSWORD")
        if username and password:
            return Credentials(
                provider=self.PROVIDER_NAME,
                username=username,
                password=password,
                base_url=self.base_url,
            )
        return None
