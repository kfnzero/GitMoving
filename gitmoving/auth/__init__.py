from .base import BaseAuth, Credentials
from .github import GitHubAuth
from .gitlab import GitLabAuth
from .bitbucket import BitbucketAuth

AUTH_HANDLERS = {
    "github": GitHubAuth,
    "gitlab": GitLabAuth,
    "bitbucket": BitbucketAuth,
}

def get_auth_handler(provider: str) -> type:
    provider = provider.lower()
    if provider not in AUTH_HANDLERS:
        raise ValueError(f"Unknown provider: {provider}")
    return AUTH_HANDLERS[provider]

__all__ = ["BaseAuth", "Credentials", "GitHubAuth", "GitLabAuth", "BitbucketAuth", "get_auth_handler"]
