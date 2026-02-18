from .base import BaseProvider, RepoInfo
from .github import GitHubProvider
from .gitlab import GitLabProvider
from .bitbucket import BitbucketProvider

PROVIDERS = {
    "github": GitHubProvider,
    "gitlab": GitLabProvider,
    "bitbucket": BitbucketProvider,
}

def get_provider(name: str) -> type:
    name = name.lower()
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider: {name}. Supported: {list(PROVIDERS.keys())}")
    return PROVIDERS[name]

__all__ = ["BaseProvider", "RepoInfo", "GitHubProvider", "GitLabProvider", "BitbucketProvider", "get_provider"]
