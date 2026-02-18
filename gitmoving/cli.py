"""
GitMoving CLI

Entry point:
  gitmoving migrate  – migrate a repository from one platform to another
  gitmoving auth     – manage saved credentials
"""

import sys

import click
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

from .auth import get_auth_handler
from .migrator.engine import MigrationConfig, MigrationEngine
from .providers import get_provider

console = Console()

PROVIDER_CHOICES = click.Choice(["github", "gitlab", "bitbucket"], case_sensitive=False)


# ---------------------------------------------------------------------------
# Root group
# ---------------------------------------------------------------------------

@click.group()
@click.version_option(package_name="gitmoving")
def main():
    """GitMoving – migrate private Git repositories across platforms."""


# ---------------------------------------------------------------------------
# migrate command
# ---------------------------------------------------------------------------

@main.command()
@click.option(
    "--src-provider", "-sp",
    required=True,
    type=PROVIDER_CHOICES,
    help="Source platform (github / gitlab / bitbucket)",
)
@click.option(
    "--src-owner", "-so",
    required=True,
    help="Owner (user or org/group) of the source repository",
)
@click.option(
    "--src-repo", "-sr",
    required=True,
    help="Source repository name",
)
@click.option(
    "--dst-provider", "-dp",
    required=True,
    type=PROVIDER_CHOICES,
    help="Destination platform (github / gitlab / bitbucket)",
)
@click.option(
    "--dst-owner", "-do",
    default=None,
    help="Owner on the destination (defaults to authenticated user)",
)
@click.option(
    "--dst-repo", "-dr",
    default=None,
    help="Destination repository name (defaults to source repo name)",
)
@click.option(
    "--src-base-url",
    default=None,
    help="Custom API base URL for self-hosted source (e.g. https://gitlab.myco.com)",
)
@click.option(
    "--dst-base-url",
    default=None,
    help="Custom API base URL for self-hosted destination",
)
@click.option(
    "--force", "-f",
    is_flag=True,
    default=False,
    help="Force-push to destination (overwrites existing refs)",
)
@click.option(
    "--no-create",
    is_flag=True,
    default=False,
    help="Do not create the destination repository; fail if it does not exist",
)
@click.option(
    "--reauth-src",
    is_flag=True,
    default=False,
    help="Force re-authentication for the source platform",
)
@click.option(
    "--reauth-dst",
    is_flag=True,
    default=False,
    help="Force re-authentication for the destination platform",
)
@click.option(
    "--verbose", "-v",
    is_flag=True,
    default=False,
    help="Show detailed git command output",
)
def migrate(
    src_provider, src_owner, src_repo,
    dst_provider, dst_owner, dst_repo,
    src_base_url, dst_base_url,
    force, no_create,
    reauth_src, reauth_dst,
    verbose,
):
    """
    Migrate a private repository from SOURCE to DESTINATION.

    All branches, tags, and commit history are preserved via git mirror clone.
    The destination repository is always created as PRIVATE.

    \b
    Example – GitHub → GitLab:
      gitmoving migrate \\
        --src-provider github --src-owner my-org --src-repo my-repo \\
        --dst-provider gitlab --dst-owner my-group

    \b
    Example – GitHub → GitHub (different org):
      gitmoving migrate \\
        --src-provider github --src-owner org-a --src-repo api-service \\
        --dst-provider github --dst-owner org-b --dst-repo api-service-copy

    \b
    Example – Bitbucket → GitLab (self-hosted):
      gitmoving migrate \\
        --src-provider bitbucket --src-owner my-team --src-repo legacy-app \\
        --dst-provider gitlab --dst-owner devteam \\
        --dst-base-url https://gitlab.internal.myco.com
    """
    console.print()
    console.print(Panel(
        Text.assemble(
            ("GitMoving", "bold cyan"),
            " – Repository Migration",
        ),
        subtitle=f"[dim]{src_provider}/{src_owner}/{src_repo}  →  {dst_provider}/{dst_owner or '?'}/{dst_repo or src_repo}[/dim]",
    ))
    console.print()

    # ---- Authenticate source ----
    try:
        src_auth_cls = get_auth_handler(src_provider)
        src_auth = src_auth_cls(base_url=src_base_url)
        console.print(f"[bold]Step 1/4:[/bold] Authenticate [cyan]{src_provider}[/cyan] (source)")
        src_creds = src_auth.get_or_prompt(label="source", force_reauth=reauth_src)
    except Exception as exc:
        console.print(f"[red]Error authenticating source:[/red] {exc}")
        sys.exit(1)

    # ---- Authenticate destination ----
    try:
        same_provider_and_url = (
            src_provider == dst_provider
            and src_base_url == dst_base_url
        )
        dst_auth_cls = get_auth_handler(dst_provider)
        dst_auth = dst_auth_cls(base_url=dst_base_url)

        console.print(f"[bold]Step 2/4:[/bold] Authenticate [cyan]{dst_provider}[/cyan] (destination)")

        if same_provider_and_url and not reauth_dst:
            # Offer to reuse source credentials for same platform
            if click.confirm(
                f"  Source and destination are both {dst_provider}. Reuse the same credentials?",
                default=True,
            ):
                dst_creds = src_creds
            else:
                dst_creds = dst_auth.get_or_prompt(label="destination", force_reauth=True)
        else:
            dst_creds = dst_auth.get_or_prompt(label="destination", force_reauth=reauth_dst)
    except Exception as exc:
        console.print(f"[red]Error authenticating destination:[/red] {exc}")
        sys.exit(1)

    # ---- Build providers ----
    try:
        src_provider_cls = get_provider(src_provider)
        dst_provider_cls = get_provider(dst_provider)
        src_prov = src_provider_cls(src_creds)
        dst_prov = dst_provider_cls(dst_creds)
    except Exception as exc:
        console.print(f"[red]Error initializing providers:[/red] {exc}")
        sys.exit(1)

    # ---- Run migration ----
    console.print(f"[bold]Step 3/4:[/bold] Clone source repository")
    console.print(f"[bold]Step 4/4:[/bold] Push to destination\n")

    cfg = MigrationConfig(
        src_provider=src_prov,
        src_owner=src_owner,
        src_repo=src_repo,
        dst_provider=dst_prov,
        dst_owner=dst_owner,
        dst_repo=dst_repo,
        create_if_missing=not no_create,
        force_push=force,
        verbose=verbose,
    )
    engine = MigrationEngine(cfg)
    try:
        engine.run()
    except Exception as exc:
        console.print(f"\n[red]Migration failed:[/red] {exc}")
        if verbose:
            console.print_exception()
        sys.exit(1)


# ---------------------------------------------------------------------------
# auth command group
# ---------------------------------------------------------------------------

@main.group()
def auth():
    """Manage saved authentication credentials."""


@auth.command("clear")
@click.argument("provider", type=PROVIDER_CHOICES)
@click.option("--label", default="default", help="Credential label (source / destination / default)")
def auth_clear(provider, label):
    """Remove saved credentials for a provider."""
    auth_cls = get_auth_handler(provider)
    handler = auth_cls()
    handler.clear_credentials(label)
    console.print(f"[green]Cleared[/green] credentials for [bold]{provider}[/bold] (label: {label})")


@auth.command("status")
@click.argument("provider", type=PROVIDER_CHOICES)
@click.option("--label", default="default", help="Credential label")
def auth_status(provider, label):
    """Check whether credentials are saved for a provider."""
    auth_cls = get_auth_handler(provider)
    handler = auth_cls()
    creds = handler.load_credentials(label)
    if creds:
        token_preview = f"{creds.token[:8]}…" if creds.token else "—"
        user_preview = creds.username or "—"
        console.print(
            f"[green]Found[/green] credentials for [bold]{provider}[/bold] (label: {label})\n"
            f"  token   : {token_preview}\n"
            f"  username: {user_preview}"
        )
    else:
        console.print(f"[yellow]No saved credentials[/yellow] for [bold]{provider}[/bold] (label: {label})")


if __name__ == "__main__":
    main()
