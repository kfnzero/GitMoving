"""Shared fixtures and helpers for GitMoving tests."""

from __future__ import annotations

import pytest
from gitmoving.auth.base import Credentials
from gitmoving.providers.base import BaseProvider, RepoInfo


# ─────────────────────────────────────────────────────────────────────────────
# RepoInfo factory
# ─────────────────────────────────────────────────────────────────────────────

def make_repo_info(
    name: str = "testrepo",
    owner: str = "owner",
    private: bool = True,
    default_branch: str = "main",
    description: str = "A test repository",
) -> RepoInfo:
    return RepoInfo(
        name=name,
        full_name=f"{owner}/{name}",
        clone_url=f"https://github.com/{owner}/{name}.git",
        ssh_url=f"git@github.com:{owner}/{name}.git",
        private=private,
        default_branch=default_branch,
        description=description,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Mock provider
# ─────────────────────────────────────────────────────────────────────────────

class MockProvider(BaseProvider):
    """Configurable in-memory mock provider for testing."""

    PROVIDER_NAME = "mock"

    def __init__(
        self,
        creds: Credentials,
        username: str = "testuser",
        repos: list | None = None,
        existing_names: set | None = None,   # repo names already on "destination"
        raise_validate: Exception | None = None,
        raise_list:     Exception | None = None,
        raise_get:      Exception | None = None,
        raise_create:   Exception | None = None,
    ) -> None:
        super().__init__(creds)
        self._username       = username
        self._repos          = list(repos or [])
        self._existing_names = set(existing_names or [])
        self._raise_validate = raise_validate
        self._raise_list     = raise_list
        self._raise_get      = raise_get
        self._raise_create   = raise_create
        self._created: dict[str, RepoInfo] = {}

    def validate_credentials(self) -> str:
        if self._raise_validate:
            raise self._raise_validate
        return self._username

    def list_repos(self, owner: str) -> list[RepoInfo]:
        if self._raise_list:
            raise self._raise_list
        return list(self._repos)

    def get_repo(self, owner: str, repo_name: str) -> RepoInfo:
        if self._raise_get:
            raise self._raise_get
        for repo in self._repos:
            if repo.name == repo_name:
                return repo
        if repo_name in self._created:
            return self._created[repo_name]
        raise ValueError(f"Repo not found: {repo_name}")

    def create_repo(
        self,
        name: str,
        owner: str | None = None,
        description: str | None = None,
        private: bool = True,
    ) -> RepoInfo:
        if self._raise_create:
            raise self._raise_create
        info = make_repo_info(name=name, owner=owner or "dst", description=description)
        self._created[name] = info
        return info

    def get_authenticated_clone_url(self, repo: RepoInfo) -> str:
        return f"https://token@example.com/{repo.full_name}.git"

    def repo_exists(self, owner: str, repo_name: str) -> bool:
        return repo_name in self._existing_names or repo_name in self._created


# ─────────────────────────────────────────────────────────────────────────────
# Provider class factory helper
#
# Qt threads call:  cls = get_provider(platform)  →  instance = cls(creds)
# We inject prepared instances by overriding __new__.
# ─────────────────────────────────────────────────────────────────────────────

def provider_class_for(instance: MockProvider) -> type:
    """Return a class that, when instantiated, always yields *instance*."""

    class _Cls:
        def __new__(cls, creds):   # noqa: N804
            return instance

    return _Cls


# ─────────────────────────────────────────────────────────────────────────────
# Reusable fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def repo_info():
    return make_repo_info()


@pytest.fixture
def src_repos():
    return [
        make_repo_info("alpha",   owner="srcowner"),
        make_repo_info("beta",    owner="srcowner", private=False),
        make_repo_info("gamma",   owner="srcowner", description=""),
    ]


@pytest.fixture
def token_params():
    """Form params dict with explicit tokens (fastest path in _make_credentials)."""
    return {
        "src_platform": "github",
        "src_owner":    "srcowner",
        "src_token":    "ghp_src123",
        "src_username": "",
        "src_base_url": None,
        "dst_platform": "github",
        "dst_owner":    "dstowner",
        "dst_token":    "ghp_dst456",
        "dst_username": "",
        "dst_base_url": None,
    }
